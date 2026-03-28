## MODIFIED Requirements

### Requirement: Fill model abstraction
The backtester SHALL use a configurable `FillModel` to simulate order fills, decoupling fill logic from the PositionEngine.

```python
class FillModel(ABC):
    @abstractmethod
    def simulate(self, order: Order, bar: dict[str, float], timestamp: datetime) -> Fill: ...
```

#### Scenario: Default fill model changed
- **WHEN** `BacktestRunner` is constructed with `fill_model=None`
- **THEN** it SHALL default to `MarketImpactFillModel()` instead of `ClosePriceFillModel()`

#### Scenario: Close-price fill with slippage (legacy)
- **WHEN** `ClosePriceFillModel` is explicitly passed
- **THEN** it SHALL fill market orders at `bar["close"] ± slippage` (adverse direction) and emit a deprecation warning

#### Scenario: Open-price fill (legacy)
- **WHEN** `OpenPriceFillModel` is explicitly passed
- **THEN** it SHALL fill at the open price and emit a deprecation warning

### Requirement: Backtesting engine
Simulator SHALL run PositionEngine on real historical data and produce comprehensive performance metrics. BacktestRunner SHALL delegate internally to EventEngine.

#### Scenario: Feed historical bars
- **WHEN** `run_backtest()` is called with historical OHLCV data
- **THEN** BacktestRunner SHALL convert bars to MarketEvents and delegate to EventEngine for processing, using the configured fill model

#### Scenario: Precomputed signals
- **WHEN** `precomputed_signals` is provided
- **THEN** each signal SHALL be paired with its corresponding bar by timestamp and injected as SignalEvents

#### Scenario: Performance metrics
- **WHEN** a backtest completes
- **THEN** the result SHALL include: Sharpe (annualized), Sortino, Calmar, max drawdown (absolute and %), win rate, profit factor, average win/loss, number of trades, average holding period, monthly/yearly return breakdown, AND new fields: total_market_impact, total_spread_cost, impact_as_pct_of_pnl

#### Scenario: Trade log
- **WHEN** a backtest completes
- **THEN** it SHALL produce a complete trade log with every entry, add, stop, and exit with timestamps, prices, AND per-fill market_impact, spread_cost, and latency_ms

#### Scenario: Equity curve
- **WHEN** a backtest completes
- **THEN** it SHALL produce a bar-by-bar equity curve and peak-to-trough drawdown series

#### Scenario: Legacy API preserved
- **WHEN** existing code calls `BacktestRunner.run(bars, signals, timestamps)`
- **THEN** the method signature and return type SHALL remain identical; internal delegation to EventEngine is transparent

### Requirement: Backtest result types
The backtester SHALL return structured result types for downstream consumption (dashboard, reports).

#### Scenario: BacktestResult fields
- **WHEN** a backtest completes
- **THEN** `BacktestResult` SHALL contain: equity_curve (per-bar), drawdown_series, trade_log (list of fills), metrics dict (all existing metrics PLUS total_market_impact, total_spread_cost, avg_latency_ms, partial_fill_count), and monthly/yearly return tables

## ADDED Requirements

### Requirement: Impact analysis report
The simulator SHALL produce a fill quality report comparing impact-aware fills against naive fills.

#### Scenario: Side-by-side comparison
- **WHEN** a backtest completes with `MarketImpactFillModel`
- **THEN** the result SHALL include an `impact_report` dict containing: `naive_pnl` (what PnL would have been with ClosePriceFillModel), `realistic_pnl` (actual PnL with impact), `pnl_ratio` (realistic/naive), and `per_trade_impact_breakdown`

#### Scenario: Impact as percentage of PnL
- **WHEN** an impact report is generated
- **THEN** it SHALL compute `impact_as_pct_of_gross_pnl = total_impact_cost / abs(gross_pnl)` to quantify execution drag
