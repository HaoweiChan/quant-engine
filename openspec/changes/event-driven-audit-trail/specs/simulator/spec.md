## MODIFIED Requirements

### Requirement: Shares production PositionEngine
Simulator SHALL reuse the exact same `PositionEngine` class as production. BacktestRunner delegates internally to EventEngine.

#### Scenario: Same class, same code path
- **WHEN** a backtest runs
- **THEN** bars SHALL be processed through `EventEngine` using the same handler chain as live trading

#### Scenario: No backtest-specific logic
- **WHEN** `PositionEngine` is used in simulation
- **THEN** it SHALL contain zero conditional branches for "is backtest"

#### Scenario: API preserved
- **WHEN** `BacktestRunner.run(bars, signals, timestamps)` is called
- **THEN** the signature and return type SHALL remain identical; delegation to EventEngine is internal

### Requirement: Backtesting engine
Simulator SHALL run PositionEngine on historical data via EventEngine.

#### Scenario: Feed historical bars via events
- **WHEN** `run_backtest()` is called
- **THEN** each bar SHALL be converted to a `MarketEvent` and processed through the event handler chain

#### Scenario: Precomputed signals as events
- **WHEN** `precomputed_signals` is provided
- **THEN** each signal SHALL be paired with its bar and injected as `SignalEvent`

#### Scenario: Performance metrics unchanged
- **WHEN** a backtest completes
- **THEN** `BacktestResult` SHALL contain the same fields as before (equity_curve, drawdown_series, trade_log, metrics, monthly/yearly returns)
