## Why

The current Monte Carlo simulation only bootstraps daily equity returns, producing a single-dimensional view of future risk. Traders need trade-level resampling to assess sequence dependency, MDD distribution at confidence levels for position sizing, probability of ruin for capital adequacy, parameter perturbation for overfitting detection, and GBM-based synthetic price paths for stress testing under unseen market regimes. Without these, the MC tab gives an incomplete and potentially misleading picture of strategy risk.

## What Changes

- Add **trade-level P&L resampling** (bootstrap individual trade outcomes with replacement) to complement daily return bootstrapping, producing equity curves that reveal sequence dependency risk
- Compute and display **MDD distribution** across all simulated paths, with 95th-percentile confidence level MDD as a headline metric
- Calculate **probability of ruin** (% of paths breaching configurable drawdown thresholds like -30%, -50%, -100%)
- Implement **parameter sensitivity / perturbation analysis** that injects small random offsets into strategy parameters and re-runs backtests to detect overfitting (sharp performance cliffs from minor changes)
- Add **GBM synthetic price path generation** using historical mean/volatility to create "parallel universe" price series, then re-run the strategy on those paths
- Enhance the Monte Carlo frontend page with new visualization panels: MDD distribution chart, ruin probability gauge, parameter sensitivity heatmap, and a mode selector for the different simulation types

## Capabilities

### New Capabilities
- `mc-trade-resampling`: Trade-level P&L bootstrap engine that reorders individual trade outcomes to build equity curves and compute MDD/ruin statistics
- `mc-mdd-analysis`: Maximum drawdown distribution computation across simulated paths with configurable confidence levels
- `mc-ruin-probability`: Probability of ruin calculator with configurable drawdown thresholds
- `mc-param-sensitivity`: Parameter perturbation engine that jitters strategy params and measures performance degradation
- `mc-price-simulation`: GBM-based synthetic price path generator with optional GARCH volatility clustering and fat tails

### Modified Capabilities
- `simulator`: Add new MC methods (trade resampling, param sensitivity, price simulation) to the simulator interface
- `react-frontend`: Add new MC visualization panels and mode selector to the Monte Carlo sub-tab

## Impact

- **Backend**: `src/simulator/monte_carlo.py` — new simulation modes and result types
- **Backend**: `src/mcp_server/facade.py` — wire new MC methods to MCP and API
- **Backend**: `src/api/main.py` — new API endpoints for MC enhancements
- **Frontend**: `frontend/src/pages/strategy/MonteCarlo.tsx` — new panels, mode selector, and visualizations
- **Frontend**: New chart components for MDD distribution, ruin probability, and param sensitivity
- **Types**: `src/core/types.py` — new result dataclasses for MC outputs
- **Dependencies**: No new external dependencies required (numpy/scipy already available)
