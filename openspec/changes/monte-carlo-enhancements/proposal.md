## Why

The current Monte Carlo simulation only bootstraps daily equity returns, producing a single-dimensional view of future risk. Traders need trade-level resampling to assess sequence dependency, MDD distribution at confidence levels for position sizing, probability of ruin for capital adequacy, parameter perturbation for overfitting detection, and GBM-based synthetic price paths for stress testing under unseen market regimes. Without these, the Stress Test tab gives an incomplete and potentially misleading picture of strategy risk.

## What's Already Done (from production-dashboard-overhaul)

The `production-dashboard-overhaul` change already implemented foundational MC infrastructure:

- **Backend block-bootstrap MC** in `src/monte_carlo/block_bootstrap.py` with `BlockBootstrapMC` class supporting stationary, circular, and GARCH-filtered residual methods
- **`POST /api/monte-carlo` endpoint** that runs a baseline backtest → extracts daily returns → performs block-bootstrap simulation → returns percentile bands + VaR/CVaR/prob_ruin
- **Frontend `StressTest.tsx`** (renamed from `MonteCarlo.tsx`) calling the backend API with a method selector and fan chart visualization
- **Single-threshold ruin probability** (configurable `ruin_threshold` fraction)
- **Server-side computation** replacing the old client-side i.i.d. bootstrap

## What This Change Adds

Building on the existing block-bootstrap foundation:

- Add **trade-level P&L resampling** (bootstrap individual trade outcomes with replacement) to complement daily return bootstrapping, producing equity curves that reveal sequence dependency risk
- Compute and display **MDD distribution** across all simulated paths, with 95th-percentile confidence level MDD as a headline metric
- Extend ruin probability to **multi-threshold** (configurable drawdown thresholds like -30%, -50%, -100%)
- Implement **parameter sensitivity / perturbation analysis** that injects small random offsets into strategy parameters and re-runs backtests to detect overfitting (sharp performance cliffs from minor changes)
- Add **GBM synthetic price path generation** using historical mean/volatility to create "parallel universe" price series, then re-run the strategy on those paths
- Enhance the Stress Test frontend page with new visualization panels: MDD distribution chart, ruin probability gauge, parameter sensitivity heatmap, and a mode selector for the different simulation types

## Capabilities

### New Capabilities
- `mc-trade-resampling`: Trade-level P&L bootstrap engine that reorders individual trade outcomes to build equity curves and compute MDD/ruin statistics
- `mc-mdd-analysis`: Maximum drawdown distribution computation across simulated paths with configurable confidence levels
- `mc-ruin-probability`: Multi-threshold probability of ruin calculator
- `mc-param-sensitivity`: Parameter perturbation engine that jitters strategy params and measures performance degradation
- `mc-price-simulation`: GBM-based synthetic price path generator with optional GARCH volatility clustering and fat tails

### Modified Capabilities
- `simulator`: Add new MC methods (trade resampling, param sensitivity, price simulation) alongside existing `BlockBootstrapMC`
- `react-frontend`: Add new MC visualization panels and mode selector to the Stress Test sub-tab

## Impact

- **Backend**: `src/monte_carlo/` — new simulation modes extending existing `BlockBootstrapMC`
- **Backend**: `src/api/routes/monte_carlo.py` — extend existing endpoint or add new mode-dispatching endpoint
- **Frontend**: `frontend/src/pages/strategy/StressTest.tsx` — new panels, mode selector, and visualizations
- **Frontend**: New chart components for MDD distribution, ruin probability, and param sensitivity
- **Types**: `src/core/types.py` or `src/monte_carlo/` — new result dataclasses for MC outputs
- **Dependencies**: No new external dependencies required (numpy/scipy/arch already available)
