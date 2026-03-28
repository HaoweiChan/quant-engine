## Context

The Stress Test tab (formerly Monte Carlo) now runs server-side block-bootstrap simulations via `POST /api/monte-carlo`. The existing backend infrastructure in `src/monte_carlo/block_bootstrap.py` provides `BlockBootstrapMC` with stationary, circular, and GARCH-filtered residual methods. The frontend `StressTest.tsx` renders a fan chart of percentile bands and displays VaR/CVaR/prob_ruin stat cards.

This change extends the MC system with additional simulation modes (trade resampling, GBM, parameter sensitivity) and richer risk analytics (MDD distribution, multi-threshold ruin probability).

**Current flow (already backend-driven):**

```
Frontend: select method (stationary/circular/garch) → POST /api/monte-carlo
         → backend runs backtest → extracts daily returns → BlockBootstrapMC
         → return {bands, var_95, var_99, cvar_95, cvar_99, prob_ruin}
         → render fan chart + stat cards
```

**Target flow:**

```
Frontend: select mode (bootstrap/trade_resampling/gbm/sensitivity)
         → POST /api/monte-carlo with mode + mode-specific config
         → backend dispatches to appropriate engine
         → return MonteCarloReport (bands + mdd_distribution + ruin_thresholds + sensitivity)
         → render per-mode panels (fan chart, MDD histogram, ruin gauges, sensitivity heatmap)
```

## Goals / Non-Goals

**Goals:**
- Extend existing `/api/monte-carlo` endpoint with a `mode` parameter (backward-compatible: default = "bootstrap")
- Implement 4 additional simulation modes: (1) trade resampling, (2) GBM price simulation, (3) parameter sensitivity, (4) combined risk report
- Surface MDD distribution at 95% CI, multi-threshold ruin probability, and Sharpe/Sortino distributions
- Frontend mode selector with per-mode result panels in `StressTest.tsx`
- Keep the backtest-engine MCP server compatible (add new MC tools)

**Non-Goals:**
- Real-time streaming of MC simulation progress (batch results only)
- HMM regime-switching models (future enhancement)
- Multi-strategy portfolio-level MC (single strategy per run)
- GPU acceleration for path generation

## Decisions

### D1: Extend existing endpoint vs new endpoint

**Decision:** Extend the existing `POST /api/monte-carlo` endpoint with a `mode` parameter. Default mode = "bootstrap" preserves backward compatibility.

**Rationale:** The existing endpoint already handles strategy/symbol/date range/params/cost model. Adding a `mode` field and mode-specific optional fields is cleaner than creating parallel endpoints. The frontend `StressTest.tsx` already calls this endpoint.

### D2: Result structure — extend MCSimulationResult or new MonteCarloReport

**Decision:** Create a new `MonteCarloReport` dataclass that extends the current response. The existing `MCSimulationResult` fields (bands, var_95, var_99, cvar_95, cvar_99, prob_ruin) become part of the base response. New fields are optional per mode.

```python
@dataclass
class MonteCarloReport:
    mode: str
    initial_capital: float
    n_paths: int
    n_days: int
    # Existing fields (from current endpoint)
    bands: dict[str, list[float]]  # p5, p25, p50, p75, p95
    var_95: float
    var_99: float
    cvar_95: float
    cvar_99: float
    prob_ruin: float
    method: str
    # New fields
    mdd_values: list[float] | None = None
    mdd_p95: float | None = None
    mdd_median: float | None = None
    ruin_thresholds: dict[str, float] | None = None  # {"-30%": 0.12, ...}
    param_sensitivity: dict[str, list[dict]] | None = None
    sharpe_values: list[float] | None = None
    sortino_values: list[float] | None = None
    final_pnls: list[float] | None = None
```

### D3: Where to put new MC engines

**Decision:** Add new modules alongside `block_bootstrap.py` in the `src/monte_carlo/` package:
- `src/monte_carlo/trade_resampling.py` — trade-level P&L bootstrap
- `src/monte_carlo/gbm_paths.py` — GBM synthetic price generation
- `src/monte_carlo/param_sensitivity.py` — parameter perturbation engine
- `src/monte_carlo/mdd_analysis.py` — MDD distribution utilities
- `src/monte_carlo/ruin_probability.py` — multi-threshold ruin probability

**Rationale:** Keeps each engine isolated and testable. The existing `block_bootstrap.py` pattern works well.

### D4: GBM implementation approach

**Decision:** Implement GBM with optional Student-t innovations for fatter tails. Calibrate μ and σ from historical log-returns.

**Rationale:** Basic GBM + Student-t gives meaningful stress testing without the complexity of full GARCH price simulation (the existing GARCH method in `BlockBootstrapMC` handles volatility clustering for return-based simulation).

### D5: Parameter sensitivity approach

**Decision:** For each parameter in param_grid, apply N random perturbations (±5%, ±10%, ±20% of current value), run a quick backtest for each, and collect the Sortino ratio. Display as a heatmap.

**Rationale:** This directly reveals overfitting — if a 5% change in one parameter causes a 50% drop in Sortino, that parameter is overfit.

## Risks / Trade-offs

- **[Compute time]** Parameter sensitivity runs N extra backtests (~50), which could take 3-5 minutes for 1-min intraday data. → Mitigation: Run perturbation backtests on aggregated TF by default. Show progress spinner.
- **[GBM realism]** GBM assumes log-normal returns, which underestimates tail risk. → Mitigation: Use Student-t innovations (df=5 default) for fatter tails. Document limitations in UI tooltip.
- **[Trade resampling bias]** Bootstrapping individual trade P&Ls ignores time-dependency between trades. → Mitigation: Also provide block bootstrap option that preserves local structure.
- **[API payload size]** Returning many equity paths × 252 days. → Mitigation: Downsample to 200 displayed paths; send full stats separately.
- **[Backward compatibility]** Existing frontend expects current response shape. → Mitigation: Default mode = "bootstrap" returns same fields as today; new fields are optional.
