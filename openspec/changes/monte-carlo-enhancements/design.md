## Context

The Monte Carlo tab currently runs a single-mode simulation: backtest → extract equity curve → aggregate to daily returns → bootstrap N paths. This gives final PnL percentiles but misses critical risk dimensions: trade-sequence dependency, MDD confidence bounds, ruin probability, overfitting detection, and robustness to unseen price regimes.

The existing `src/simulator/monte_carlo.py` has a `run_monte_carlo` function that generates GBM paths and runs strategies against them, but this is backend-only and not wired to the dashboard. The frontend Monte Carlo page does all simulation client-side using bootstrapped daily returns.

**Current flow:**

```
Frontend: select strategy → call /api/backtest/run → get equity_curve
         → aggregate to daily returns → bootstrap N paths → render SVG
```

**Target flow:**

```
Frontend: select mode → call /api/mc/<mode> → backend computes
         → return structured results → render per-mode panels
```

## Goals / Non-Goals

**Goals:**
- Move MC computation to the backend for consistency and to leverage numpy/scipy
- Implement 5 simulation modes: (1) trade resampling, (2) daily return bootstrap (existing, improved), (3) GBM price simulation, (4) parameter sensitivity, (5) combined risk report
- Surface MDD distribution at 95% CI, ruin probability, and Sharpe/Sortino distributions
- Frontend mode selector with per-mode result panels
- Keep the backtest-engine MCP server compatible (add new MC tools)

**Non-Goals:**
- Real-time streaming of MC simulation progress (batch results only)
- HMM regime-switching models (future enhancement)
- Multi-strategy portfolio-level MC (single strategy per run)
- GPU acceleration for path generation

## Decisions

### D1: Move MC to backend vs keep frontend-only

**Decision:** Move all MC computation to the backend.

**Rationale:** Frontend bootstrapping is limited to simple return resampling. Parameter sensitivity requires running N backtests, which needs access to strategy code and market data. GBM price generation needs numpy/scipy. Backend computation also ensures consistency with the backtest engine.

**Alternative considered:** Keep simple bootstrap in frontend, add new modes as separate API calls. Rejected because it splits MC logic across two runtimes and makes it harder to produce combined risk reports.

### D2: Single API endpoint vs per-mode endpoints

**Decision:** Single endpoint `POST /api/mc/run` with a `mode` parameter, returning mode-specific results.

**Rationale:** All modes share the same input shape (strategy, symbol, date range, params) plus mode-specific config. A single endpoint keeps the API surface small and allows the frontend to request combined runs.

**Alternative considered:** Per-mode endpoints (`/api/mc/bootstrap`, `/api/mc/gbm`, etc.). Cleaner separation but more routes to maintain, and the combined report mode would still need to call them all.

### D3: Result structure

**Decision:** Return a `MonteCarloReport` dataclass with optional fields per mode:

```python
@dataclass
class MonteCarloReport:
    mode: str
    initial_capital: float
    sim_days: int
    n_paths: int
    # Equity paths (downsampled to max 200 for frontend)
    paths: list[list[float]]
    # Final PnL distribution
    final_pnls: list[float]
    # Percentile stats
    percentiles: dict[str, float]  # p5, p25, p50, p75, p95
    # MDD stats (all modes)
    mdd_values: list[float]        # MDD for each path
    mdd_p95: float                 # 95th percentile MDD
    mdd_median: float
    # Ruin probability
    ruin_thresholds: dict[str, float]  # {"-30%": 0.12, "-50%": 0.05}
    # Parameter sensitivity (mode=sensitivity only)
    param_sensitivity: dict[str, list[dict]] | None = None
    # Sharpe/Sortino distributions
    sharpe_values: list[float] | None = None
    sortino_values: list[float] | None = None
```

### D4: GBM implementation approach

**Decision:** Use the existing `src/simulator/monte_carlo.py` GBM path generator, extend it with optional GARCH volatility and Student-t innovations for fatter tails.

**Rationale:** The spec already defines GBM with GARCH, fat tails, and jump processes. The existing generator handles basic GBM; adding GARCH/t-dist is incremental. For this change, we implement GBM + Student-t; GARCH and jump processes can follow.

### D5: Parameter sensitivity approach

**Decision:** For each parameter in `PARAM_SCHEMA`, apply N random perturbations (±5%, ±10%, ±20% of current value), run a quick backtest for each, and collect the Sortino ratio. Display as a heatmap showing sensitivity per parameter.

**Rationale:** This directly reveals overfitting — if a 5% change in one parameter causes a 50% drop in Sortino, that parameter is overfit. The perturbation ranges are configurable in the UI.

**Alternative considered:** Full grid search across perturbations. Too expensive — a strategy with 8 params and 5 perturbation levels each would require 5^8 = 390K backtests. Random sampling with ~50 total perturbations (each varying one param at a time) is practical.

## Risks / Trade-offs

- **[Compute time]** Parameter sensitivity runs N extra backtests (~50), which could take 3-5 minutes for 1-min intraday data. → Mitigation: Run perturbation backtests on aggregated TF (e.g., 5-min) by default to reduce bar count. Show progress spinner.
- **[GBM realism]** GBM assumes log-normal returns, which underestimates tail risk. → Mitigation: Use Student-t innovations (df=5 default) for fatter tails. Document limitations in UI tooltip.
- **[Trade resampling bias]** Bootstrapping individual trade P&Ls ignores time-dependency between trades (e.g., losing streaks). → Mitigation: Also provide block bootstrap option that preserves local structure.
- **[API payload size]** Returning 1000 equity paths × 252 days = 252K floats. → Mitigation: Downsample to 200 displayed paths; send full stats separately.
