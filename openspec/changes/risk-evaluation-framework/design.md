## Context

The current risk evaluation pipeline consists of:
1. **Block-bootstrap Monte Carlo** (`src/monte_carlo/block_bootstrap.py`) — stationary resampling of daily returns, producing VaR/CVaR/P(Ruin) metrics
2. **Parameter sensitivity** — single-parameter perturbation measuring Sortino impact
3. **Stress tests** (`src/simulator/stress.py`) — 5 isolated synthetic scenarios run through BacktestRunner
4. **MCP facade** (`src/mcp_server/facade.py`) — already accepts `slippage_bps`, `commission_bps`, `commission_fixed_per_contract` but defaults them all to 0.0

The fill model infrastructure (`MarketImpactFillModel`, `ImpactParams`) is already wired into `BacktestRunner`. The problem is not missing plumbing — it's missing defaults, missing evaluation layers, and missing aggregation.

```
Current flow:
  MCP tool call → facade → BacktestRunner(fill_model=0 cost) → metrics

Target flow:
  MCP tool call → facade → CostConfig(defaults per instrument)
                         → BacktestRunner(fill_model=realistic cost)
                         → [L1] Regime MC  ──┐
                         → [L2] Adversarial ──┤
                         → [L3] Param Grid  ──┼→ RiskReport → sign-off gate
                         → [L4] Walk-Forward ─┤
                         → [L5] Cost Impact ──┘
```

## Goals / Non-Goals

**Goals:**
- Enforce realistic transaction costs as non-zero defaults in all simulation paths
- Add regime-conditioned Monte Carlo using HMM-labeled market states
- Embed adversarial stress scenarios within MC paths (not just isolated runs)
- Provide walk-forward OOS validation with IS/OOS Sharpe ratio analysis
- Extend parameter sensitivity with cliff-edge detection and stability scoring
- Aggregate all layers into a unified risk report for strategy sign-off
- Expose all new capabilities via MCP tools and FastAPI endpoints

**Non-Goals:**
- Real-time risk monitoring (that's the Risk Monitor's domain)
- Portfolio-level risk aggregation across multiple strategies
- Changing the existing BacktestRunner or PositionEngine internals
- Live execution cost tracking (handled by execution engine)
- Replacing the existing MC or stress test modules — we extend them

## Decisions

### D1: Cost defaults live in a per-instrument config, not hardcoded

**Decision**: Create `InstrumentCostConfig` dataclass mapping instrument symbols to their default costs. The MCP facade injects these defaults when no explicit cost params are provided.

**Rationale**: TX and MTX have different commission structures (NT$100 vs NT$40 round-trip). Hardcoding in the facade would require changes every time an instrument is added. A config-driven approach scales to future instruments (US equities, crypto).

**Alternative considered**: Embed costs in strategy TOML files. Rejected because costs are instrument properties, not strategy properties — the same strategy trading TX vs MTX has different costs.

```python
@dataclass(frozen=True)
class InstrumentCostConfig:
    slippage_pct: float = 0.1        # 0.1% default
    commission_per_contract: float = 100.0  # NT$ round-trip
    symbol: str = "TX"

INSTRUMENT_COSTS: dict[str, InstrumentCostConfig] = {
    "TX":  InstrumentCostConfig(slippage_pct=0.1, commission_per_contract=100.0, symbol="TX"),
    "MTX": InstrumentCostConfig(slippage_pct=0.1, commission_per_contract=40.0, symbol="MTX"),
}
```

### D2: HMM regime labeling as a standalone module

**Decision**: Create `src/simulator/regime.py` that fits a 2–3 state HMM on daily returns using `hmmlearn.GaussianHMM`. The module exposes `fit_regime_model()` and `label_regimes()` functions. The MC module calls into regime labeling rather than inheriting from it.

**Rationale**: Regime detection is useful beyond MC (e.g., live position sizing, dashboard regime indicators). Keeping it as a composable module avoids coupling it to the bootstrap implementation.

**Alternative considered**: Integrate HMM directly into `BlockBootstrapMC.fit()`. Rejected because it would make the MC class responsible for two concerns (resampling + regime detection) and prevent reuse.

```
src/simulator/regime.py
  ├── fit_regime_model(daily_returns) → RegimeModel
  ├── label_regimes(model, returns) → regime_labels[]
  └── RegimeModel (wrapper around hmmlearn + metadata)

src/monte_carlo/block_bootstrap.py
  └── simulate(..., regime_model=None) → if provided, bootstrap within-regime
```

### D3: Adversarial injection modifies MC paths post-generation

**Decision**: After generating N MC paths via block bootstrap, apply stress scenario transforms at random insertion points within each path. This is a post-processing step, not a change to the bootstrap algorithm.

**Rationale**: Keeps the bootstrap statistically valid (it generates "normal" market conditions) while layering on adversarial events. The injection probability and position are configurable per scenario.

```
MC path generation (unchanged) → N paths of length T
Adversarial injection:
  For each path:
    With probability p_inject (default 0.3):
      Pick random insertion point t ∈ [warmup, T-scenario_duration]
      Apply scenario transform (gap_down, flash_crash, etc.) at t
      Record injection metadata for reporting
```

### D4: Walk-forward uses expanding windows with strategy re-optimization

**Decision**: Implement expanding-window walk-forward in `src/simulator/walk_forward.py`. Each fold optimizes parameters on the in-sample window (using the existing parameter sweep), then validates on the out-of-sample window. Default: 3 folds.

**Rationale**: Expanding windows (vs. rolling) are more appropriate for our data size (~4 years). Rolling windows would discard early data too aggressively.

```
Fold 1: |---IS---|---OOS---|
Fold 2: |------IS------|---OOS---|
Fold 3: |----------IS----------|---OOS---|

For each fold:
  1. Run parameter sweep on IS bars → best params
  2. Run backtest on OOS bars with best params → OOS metrics
  3. Compare IS Sharpe vs OOS Sharpe → overfit ratio
```

### D5: Risk report is a pure aggregation — no new simulation

**Decision**: The `RiskReport` is a data structure that collects results from all five layers and applies pass/fail logic per the quality gates in CLAUDE.md. It doesn't run any simulations itself.

**Rationale**: Simulation orchestration belongs in the MCP tools/facade. The report is a read-only summary that can be generated from cached results, making it fast to re-evaluate if thresholds change.

### D6: MCP tool additions

Two new tools:
- `run_walk_forward` — runs expanding-window walk-forward validation
- `run_risk_report` — aggregates all cached results into a sign-off report

Existing tools (`run_backtest`, `run_monte_carlo`, `run_parameter_sweep`, `run_stress_test`) get default cost injection via the facade — no interface changes needed, just different defaults.

## Risks / Trade-offs

**[Risk] HMM regime detection is sensitive to hyperparameters** → Mitigation: Default to 2 states (high-vol / low-vol) which is robust. Allow 3-state as an option. Log BIC scores for model selection transparency.

**[Risk] Adversarial injection at high probability distorts MC distribution** → Mitigation: Default injection probability is 0.3 (30% of paths). Configurable. Report injected vs. clean path statistics separately.

**[Risk] Walk-forward re-optimization is computationally expensive** → Mitigation: Use a reduced parameter grid (±20% around current params, not full grid). Each fold's sweep is bounded by `max_combinations` from the existing sweep tool. Typical run: 3 folds × ~50 combinations = ~150 backtests.

**[Risk] Default slippage of 0.1% may be too aggressive for liquid TX contracts** → Mitigation: The default is configurable per instrument. 0.1% is conservative (1–2 ticks on TX at ~20000). Users can override to 0.05% if they have evidence of better execution.

**[Risk] Adding `hmmlearn` dependency** → Mitigation: `hmmlearn` is already in the tech stack (listed in project context). It's a well-maintained sklearn-compatible library with minimal transitive dependencies.

**[Trade-off] Expanding window walk-forward biases later folds toward more data** → Accepted: This matches how we'd actually deploy — always using all available history for optimization. The alternative (fixed-size rolling windows) would limit IS data artificially.
