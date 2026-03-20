## ADDED Requirements

### Requirement: Fill model abstraction
The backtester SHALL use a configurable `FillModel` to simulate order fills, decoupling fill logic from the PositionEngine.

```python
class FillModel(ABC):
    @abstractmethod
    def simulate(self, order: Order, bar: pl.Series) -> Fill: ...
```

#### Scenario: Close-price fill with slippage
- **WHEN** a fill model is configured with slippage in points
- **THEN** it SHALL fill market orders at `bar.close ± slippage` (adverse direction)

#### Scenario: Open-price fill
- **WHEN** configured for open-price fills
- **THEN** it SHALL fill at the next bar's open price

### Requirement: Backtest result types
The backtester SHALL return structured result types for downstream consumption (dashboard, reports).

#### Scenario: BacktestResult fields
- **WHEN** a backtest completes
- **THEN** `BacktestResult` SHALL contain: equity_curve (per-bar), drawdown_series, trade_log (list of fills), metrics dict (Sharpe, Sortino, Calmar, max drawdown, win rate, profit factor, avg win/loss, trade count, avg holding period), and monthly/yearly return tables

#### Scenario: MonteCarloResult fields
- **WHEN** a Monte Carlo run completes
- **THEN** `MonteCarloResult` SHALL contain: terminal_pnl_distribution, percentiles (P5/P25/P50/P75/P95), win_rate, max_drawdown_distribution, sharpe_distribution, ruin_probability, and per-path equity curves

#### Scenario: StressResult fields
- **WHEN** a stress test completes
- **THEN** `StressResult` SHALL contain: scenario_name, final_pnl, max_drawdown, circuit_breaker_triggered (bool), stops_triggered (list), and equity_curve

### Requirement: Path config presets
The price path generator SHALL provide named presets for common market scenarios.

#### Scenario: Available presets
- **WHEN** preset names are queried
- **THEN** the generator SHALL provide at least: `strong_bull`, `gradual_bull`, `bull_with_correction`, `sideways`, `bear`, `volatile_bull`, `flash_crash`

#### Scenario: Custom config
- **WHEN** a `PathConfig` is constructed with custom parameters
- **THEN** the generator SHALL use those parameters regardless of presets

## MODIFIED Requirements

### Requirement: Stress testing
Simulator SHALL test PositionEngine behavior under extreme market scenarios. Scenario parameters SHALL be configurable, not hardcoded to specific percentage values.

#### Scenario: Configurable gap down
- **WHEN** a stress test runs a gap down scenario with a configurable magnitude
- **THEN** the result SHALL show whether max_loss constraint holds and the exact loss incurred

#### Scenario: Configurable slow bleed
- **WHEN** a stress test runs a slow bleed scenario with configurable total decline and duration
- **THEN** the result SHALL show drawdown trajectory and whether trailing stops triggered appropriately

#### Scenario: Configurable flash crash
- **WHEN** a stress test runs a flash crash scenario with configurable depth and recovery time
- **THEN** the result SHALL show whether positions were stopped out and whether the circuit breaker fired

#### Scenario: Volatility regime shift
- **WHEN** a stress test runs a vol regime shift (low → high volatility)
- **THEN** the result SHALL show how stops and position sizing adapted

#### Scenario: Liquidity crisis
- **WHEN** a stress test runs with configurable spread multiplier
- **THEN** the result SHALL account for slippage impact on PnL
