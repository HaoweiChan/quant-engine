## MODIFIED Requirements

### Requirement: Bar builder
The data layer SHALL aggregate minute-level data into multi-timeframe bars (5m, 1H, 4H, daily) and compute ATR at each timeframe. ATR values in output dicts SHALL use generic keys without hardcoded example values.

#### Scenario: Standard timeframe aggregation
- **WHEN** minute OHLCV data is provided
- **THEN** the bar builder SHALL produce valid 5m, 1H, 4H, and daily bars with correct open/high/low/close/volume values

#### Scenario: Multi-timeframe ATR
- **WHEN** bars are built at multiple timeframes
- **THEN** the bar builder SHALL compute ATR(14) at each timeframe simultaneously, outputting a dict keyed by timeframe name (e.g., `{"daily": ..., "hourly": ..., "5m": ...}`)

#### Scenario: Session gap handling
- **WHEN** aggregating bars for a market with intra-day session gaps (e.g., day session + night session)
- **THEN** the bar builder SHALL use session boundary definitions from the adapter's trading hours config to correctly handle gaps without producing spurious bars

#### Scenario: Volume-weighted bars (Phase 3)
- **WHEN** configured for crypto markets
- **THEN** the bar builder SHALL support volume-weighted bars and range bars in addition to time-based bars

### Requirement: Feature store
The data layer SHALL compute, cache, and serve features for Prediction Engine consumption. Market-specific features SHALL be provided via a pluggable feature plugin architecture.

#### Scenario: Standard technical indicators
- **WHEN** feature computation is triggered
- **THEN** the feature store SHALL compute via pandas-ta: RSI(14), MACD(12,26,9), Bollinger(20,2), SMA(20,50,200), ATR(14), ADX(14), Stochastic(14,3)

#### Scenario: Market-specific features via plugins
- **WHEN** an adapter registers a feature plugin
- **THEN** the feature store SHALL invoke that plugin's `compute()` method and merge the results with standard indicators

#### Scenario: Crypto features (Phase 3)
- **WHEN** operating on crypto data with a crypto feature plugin
- **THEN** the feature store SHALL compute: funding rate history, open interest changes, exchange inflow/outflow, and long/short ratio

#### Scenario: US features (Phase 4)
- **WHEN** operating on US equity data with a US feature plugin
- **THEN** the feature store SHALL compute: VIX index, sector ETF rotation signals, earnings calendar proximity, and treasury yield curve slope

## ADDED Requirements

### Requirement: Feature plugin interface
The data layer SHALL define a `FeaturePlugin` ABC that market adapters can implement to provide market-specific features.

```python
class FeaturePlugin(ABC):
    @abstractmethod
    def compute(self, bars: pl.DataFrame) -> pl.DataFrame: ...
    @abstractmethod
    def required_columns(self) -> list[str]: ...
```

#### Scenario: Plugin registration
- **WHEN** an adapter provides a `FeaturePlugin` implementation
- **THEN** the feature store SHALL accept and invoke it during feature computation

#### Scenario: Plugin isolation
- **WHEN** a plugin raises an exception during computation
- **THEN** the feature store SHALL log the error and continue with standard features, setting a warning flag
