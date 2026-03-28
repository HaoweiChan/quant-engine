# mc-price-simulation

## Purpose
TBD — synced from change `monte-carlo-enhancements`.

## Requirements

### Requirement: GBM synthetic price path generation
The system SHALL generate synthetic OHLCV price paths using Geometric Brownian Motion calibrated to historical data.

#### Scenario: Basic GBM generation
- **WHEN** `generate_gbm_paths(historical_prices, n_paths=100, n_days=252)` is called
- **THEN** it SHALL compute historical log-return mean (μ) and volatility (σ) from `historical_prices` and generate `n_paths` price series of length `n_days` using `S(t+1) = S(t) * exp((μ - σ²/2)*dt + σ*√dt*Z)` where Z ~ N(0,1)

#### Scenario: Fat-tail innovations
- **WHEN** `fat_tails=True` and `df=5` are specified
- **THEN** innovations Z SHALL be drawn from a Student-t distribution with `df` degrees of freedom, scaled to unit variance

#### Scenario: Default innovations
- **WHEN** `fat_tails` is not specified
- **THEN** innovations SHALL use standard normal distribution

#### Scenario: Start price anchoring
- **WHEN** paths are generated
- **THEN** all paths SHALL start from the last observed historical price

### Requirement: Strategy replay on synthetic paths
The system SHALL replay the strategy on each synthetic price path and collect performance metrics.

#### Scenario: Replay execution
- **WHEN** GBM paths are generated and a strategy is specified
- **THEN** the system SHALL run the strategy backtest on each synthetic path and collect final equity, Sortino, and MDD per path

#### Scenario: Synthetic path OHLCV format
- **WHEN** GBM generates a close-price series
- **THEN** the system SHALL construct synthetic OHLCV bars with `open=prev_close`, `high=max(open, close)*1.001`, `low=min(open, close)*0.999`, `close=generated_price`, `volume=historical_mean_volume` to satisfy strategy data requirements

#### Scenario: Insufficient historical data
- **WHEN** `historical_prices` has fewer than 30 data points
- **THEN** the function SHALL raise `ValueError` indicating insufficient data for calibration
