## 1. Result Types (`quant_engine/simulator/types.py`)

- [x] 1.1 Implement `BacktestResult` dataclass: equity_curve, drawdown_series, trade_log, metrics dict, monthly/yearly return tables — acceptance: all fields populated after a backtest run
- [x] 1.2 Implement `MonteCarloResult` dataclass: terminal_pnl_distribution, percentiles, win_rate, max_drawdown_distribution, sharpe_distribution, ruin_probability — acceptance: all fields populated after Monte Carlo run
- [x] 1.3 Implement `StressResult` dataclass: scenario_name, final_pnl, max_drawdown, circuit_breaker_triggered, stops_triggered, equity_curve — acceptance: all fields populated after stress test
- [x] 1.4 Implement `StressScenario` dataclass: name, configurable parameters (magnitude, duration, recovery) — acceptance: scenarios constructable with custom parameters
- [x] 1.5 Implement `PathConfig` dataclass: drift, volatility, garch params, student-t df, jump intensity/size, OU params — acceptance: all stochastic components configurable
- [x] 1.6 Implement `Fill` dataclass: order reference, fill_price, slippage, timestamp — acceptance: tracks fill details

## 2. Performance Metrics (`quant_engine/simulator/metrics.py`)

- [x] 2.1 Implement Sharpe ratio (annualized) from equity curve — acceptance: matches manual calculation on known data
- [x] 2.2 Implement Sortino ratio — acceptance: uses downside deviation only
- [x] 2.3 Implement Calmar ratio (return / max drawdown) — acceptance: correct for known equity curve
- [x] 2.4 Implement max drawdown (absolute and percentage) — acceptance: identifies correct peak-to-trough
- [x] 2.5 Implement win rate, profit factor, avg win/loss from trade log — acceptance: matches hand count
- [x] 2.6 Implement trade count, average holding period — acceptance: correct for known trade log
- [x] 2.7 Implement monthly and yearly return breakdown — acceptance: returns aggregated correctly by calendar period

## 3. Fill Model (`quant_engine/simulator/backtester.py`)

- [x] 3.1 Implement `FillModel` ABC with `simulate()` method — acceptance: cannot instantiate directly
- [x] 3.2 Implement `ClosePriceFillModel`: fills at bar close ± configurable slippage — acceptance: adverse slippage applied correctly for buy/sell
- [x] 3.3 Implement `OpenPriceFillModel`: fills at next bar's open — acceptance: correct open price used

## 4. Backtester (`quant_engine/simulator/backtester.py`)

- [x] 4.1 Implement `BacktestRunner.__init__` accepting PyramidConfig, adapter, fill model — acceptance: constructs a fresh PositionEngine internally
- [x] 4.2 Implement `run()`: iterate historical bars, call `on_snapshot()` per bar, simulate fills, track equity curve — acceptance: processes all bars in sequence without look-ahead
- [x] 4.3 Implement precomputed signal pairing: match signals to bars by timestamp — acceptance: correct signal paired with each bar
- [x] 4.4 Implement trade log recording: every entry, add, stop, exit with timestamps and prices — acceptance: complete log matches order output
- [x] 4.5 Implement equity curve and drawdown series tracking (bar-by-bar) — acceptance: equity matches cumulative PnL, drawdown tracks peak-to-trough
- [x] 4.6 Assemble `BacktestResult` from run data + metrics — acceptance: all result fields populated

## 5. Price Path Generator (`quant_engine/simulator/price_gen.py`)

- [x] 5.1 Implement GBM base: drift + diffusion with normal innovations — acceptance: mean return and volatility match configured parameters within statistical tolerance
- [x] 5.2 Add GARCH(1,1) volatility: replace constant sigma with time-varying volatility — acceptance: generated paths exhibit volatility clustering (autocorrelation of squared returns > 0)
- [x] 5.3 Add Student-t(df=5) shocks: replace normal innovations — acceptance: kurtosis of generated returns > 3
- [x] 5.4 Add Poisson jump process: rare large jumps with configurable intensity and size — acceptance: jump frequency matches Poisson parameter within tolerance
- [x] 5.5 Add Ornstein-Uhlenbeck mean reversion component — acceptance: generated paths revert toward mean at configured rate
- [x] 5.6 Implement preset configs: strong_bull, gradual_bull, bull_with_correction, sideways, bear, volatile_bull, flash_crash — acceptance: each preset produces paths with characteristic behavior

## 6. Monte Carlo Runner (`quant_engine/simulator/monte_carlo.py`)

- [x] 6.1 Implement runner: generate N paths, run each through PositionEngine, collect terminal PnL — acceptance: N results collected
- [x] 6.2 Compute distribution statistics: P5/P25/P50/P75/P95, win rate, ruin probability — acceptance: percentiles match numpy.percentile on collected PnL
- [x] 6.3 Compute per-path Sharpe and max drawdown distributions — acceptance: distributions have N entries
- [x] 6.4 Implement optional Ray parallelization for N > configurable threshold — acceptance: results identical with and without Ray

## 7. Stress Tests (`quant_engine/simulator/stress.py`)

- [x] 7.1 Implement stress test runner: apply StressScenario to generate a price path, run through PositionEngine — acceptance: produces StressResult
- [x] 7.2 Implement gap-down scenario generator (configurable magnitude) — acceptance: single-bar drop of configured size
- [x] 7.3 Implement slow-bleed scenario generator (configurable total decline and duration) — acceptance: gradual decline over configured period
- [x] 7.4 Implement flash-crash scenario generator (configurable depth and recovery time) — acceptance: sharp drop followed by recovery
- [x] 7.5 Implement volatility regime shift scenario generator — acceptance: volatility step-change at configured point
- [x] 7.6 Implement liquidity crisis scenario (configurable spread multiplier applied to fill model) — acceptance: fills degraded by spread multiplier
- [x] 7.7 Verify max_loss constraint holds across all default scenarios — acceptance: circuit breaker fires before loss exceeds max_loss

## 8. Parameter Scanner (`quant_engine/simulator/scanner.py`)

- [x] 8.1 Implement grid search: sweep configurable parameter ranges, run backtest per combination — acceptance: results DataFrame has one row per combination
- [x] 8.2 Implement configurable sweep ranges for stop_atr_mult, trail_atr_mult, add_trigger_atr, kelly_fraction — acceptance: all configured ranges expanded correctly
- [x] 8.3 Implement robust region identification: flag parameter areas where neighbors also perform well — acceptance: not just single best point highlighted

## 9. Tests

- [x] 9.1 Backtest tests: run on synthetic data with known outcome, verify equity curve and trade log — acceptance: results match hand calculation
- [x] 9.2 Metrics tests: verify each metric function against known values — acceptance: all metrics correct
- [x] 9.3 Price path generator tests: verify statistical properties (mean, vol, kurtosis, jump frequency) — acceptance: properties within expected statistical bounds
- [x] 9.4 Monte Carlo tests: small N run, verify result structure and statistics — acceptance: all fields populated, percentiles ordered correctly
- [x] 9.5 Stress test tests: verify each scenario generates correct price pattern — acceptance: gap size, bleed rate, flash depth match config
- [x] 9.6 Scanner tests: small grid, verify result shape and parameter coverage — acceptance: results cover full grid

## 10. Quality Gates

- [x] 10.1 `ruff check` passes with zero errors
- [x] 10.2 `mypy --strict` passes with zero errors
- [x] 10.3 All pytest tests pass
