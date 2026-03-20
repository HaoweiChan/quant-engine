## Why

Sprint A and B deliver the Position Engine and real market data. Without a backtester and simulator, there is no way to evaluate whether the engine's pyramid strategy, stop-loss layers, and parameter choices actually produce profitable results on historical or synthetic data. This sprint closes the validation loop — the team can backtest on real TAIFEX data, run Monte Carlo simulations, stress test edge cases, and scan parameter space to find robust configurations.

## What Changes

- Implement BacktestRunner that feeds historical bars through the production PositionEngine
- Implement comprehensive performance metrics (Sharpe, Sortino, Calmar, drawdown, win rate, etc.)
- Implement Price Path Generator with GBM, GARCH, Student-t shocks, Poisson jumps, OU mean reversion
- Implement Monte Carlo runner with PnL distribution and risk metrics
- Implement stress test framework with configurable extreme scenarios
- Implement parameter scanner with grid search and robust region identification
- Define result dataclasses: `BacktestResult`, `MonteCarloResult`, `StressResult`, `StressScenario`

## Capabilities

### New Capabilities

_(none — simulator capability already has a spec)_

### Modified Capabilities

- `simulator`: Implement from existing spec — backtester, Monte Carlo, stress tests, parameter scanner, price path generator

## Impact

- **New packages**: `quant_engine.simulator.backtester`, `quant_engine.simulator.monte_carlo`, `quant_engine.simulator.price_gen`, `quant_engine.simulator.stress`, `quant_engine.simulator.scanner`
- **Dependencies**: numpy, scipy (for Student-t, Poisson), ray (optional, for parallel Monte Carlo)
- **Consumes**: `quant_engine.core.position_engine` (Sprint A), `quant_engine.data` (Sprint B) for historical data
- **Downstream unblocked**: Sprint D (Prediction) needs backtest infrastructure for walk-forward validation; Sprint E (Integration) needs the sequential optimization pipeline
