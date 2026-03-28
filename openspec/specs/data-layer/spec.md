## Purpose

Ingest market data from broker APIs, normalize to common OHLCV format, build multi-timeframe bars, compute and cache features, and serve all downstream modules (Prediction Engine and Position Engine).

## Requirements

### Requirement: Market connectors
The data layer SHALL provide per-broker connectors that ingest raw market data (OHLCV) from broker APIs.

#### Scenario: Sinopac connector (Phase 1)
- **WHEN** the Sinopac connector is initialized
- **THEN** it SHALL retrieve credentials from `SecretManager` (not environment variables) and support fetching historical daily and minute OHLCV data for TX, MTX, and TMF from shioaji

#### Scenario: Session management
- **WHEN** a broker session expires or disconnects
- **THEN** the connector SHALL handle re-authentication automatically with configurable retry logic, re-fetching credentials from `SecretManager`

#### Scenario: Data validation
- **WHEN** raw data is fetched from a broker
- **THEN** the connector SHALL validate for gaps, null values, and outliers before passing downstream

#### Scenario: Rate limiting
- **WHEN** API rate limits are hit
- **THEN** the connector SHALL back off and retry without crashing

#### Scenario: No environment variable credentials
- **WHEN** the Sinopac connector initializes
- **THEN** it SHALL NOT read `SINOPAC_API_KEY` or `SINOPAC_SECRET_KEY` from environment variables — all credentials SHALL come exclusively from `SecretManager`

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

### Requirement: Parquet storage
The feature store SHALL persist historical features as parquet files, keyed by symbol, timeframe, and date range.

#### Scenario: Write features
- **WHEN** features are computed for a symbol and date range
- **THEN** they SHALL be written to parquet format with appropriate partitioning

#### Scenario: Read features
- **WHEN** historical features are requested for a symbol and date range
- **THEN** the store SHALL read from parquet efficiently, supporting predicate pushdown for date filtering

#### Scenario: Incremental updates
- **WHEN** new data arrives
- **THEN** the store SHALL append new features without recomputing the entire history

### Requirement: In-memory cache
The feature store SHALL provide an in-memory LRU cache for serving live features to Prediction Engine with minimal latency.

#### Scenario: Cache hit
- **WHEN** a feature for a recently computed symbol/timeframe is requested
- **THEN** it SHALL be served from the LRU cache without disk I/O

#### Scenario: Cache invalidation
- **WHEN** new bar data arrives and features are recomputed
- **THEN** the cache SHALL be updated with the fresh values

### Requirement: Data layer serves all downstream modules
The data layer SHALL serve both Prediction Engine (features) and Position Engine (MarketSnapshot) without coupling those modules to each other.

#### Scenario: Feature serving to Prediction Engine
- **WHEN** Prediction Engine needs features
- **THEN** data layer SHALL provide a `pd.DataFrame` from the feature store

#### Scenario: Snapshot serving to Position Engine
- **WHEN** Position Engine needs current market state
- **THEN** data layer SHALL provide a `MarketSnapshot` via the market adapter's `to_snapshot()`

### Requirement: Database layer
Extended with PIT-aware query support for mutable data.

#### Scenario: SQLite in development
- **WHEN** running in development mode
- **THEN** the database SHALL use SQLite

#### Scenario: PIT-aware mutable data queries
- **WHEN** querying margin rates during backtesting
- **THEN** the database SHALL support `AS_OF(knowledge_time)` that returns only data known at the specified time

#### Scenario: PIT schema migration
- **WHEN** migration runs
- **THEN** mutable data tables SHALL gain `knowledge_time`, `valid_from`, `valid_to` columns without breaking existing queries

### Requirement: OHLCV query methods on Database
The Database class SHALL expose methods for querying and inserting 1-minute OHLCV bars. No timeframe parameter is needed since only 1-minute data is stored.

#### Scenario: Bulk insert bars
- **WHEN** `add_ohlcv_bars(bars)` is called with a list of OHLCVBar records
- **THEN** all bars SHALL be upserted in a single transaction

#### Scenario: Query bars for backtesting
- **WHEN** `get_ohlcv(symbol, start, end)` is called
- **THEN** it SHALL return a `list[OHLCVBar]` of 1-minute bars ordered by timestamp ascending, filtered to the requested range

#### Scenario: Check data availability
- **WHEN** `get_ohlcv_range(symbol)` is called
- **THEN** it SHALL return a tuple of (earliest_timestamp, latest_timestamp) or None if no data exists

#### Scenario: Thicker timeframes via aggregation
- **WHEN** 5m, 1H, 4H, or daily bars are needed for backtesting or features
- **THEN** the caller SHALL query 1-minute bars and aggregate via bar_builder — the Database SHALL NOT store pre-aggregated timeframes

### Requirement: Margin query methods on Database
Extended with PIT semantics.

#### Scenario: Insert margin snapshot
- **WHEN** `add_margin_snapshot(snapshot)` is called
- **THEN** it SHALL be persisted with `knowledge_time` set to current time

#### Scenario: Get latest margin (unchanged behavior)
- **WHEN** `get_latest_margin(symbol)` is called without `as_of`
- **THEN** it SHALL return the most recent MarginSnapshot

#### Scenario: Get margin AS_OF
- **WHEN** `get_latest_margin(symbol, as_of=T)` is called
- **THEN** it SHALL return the most recent MarginSnapshot with `knowledge_time <= T`

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

### Requirement: Per-contract OHLCV storage
The data layer SHALL store OHLCV data with specific contract identifiers alongside generic symbols.

#### Scenario: Store per-contract bars
- **WHEN** OHLCV data is ingested for futures
- **THEN** it SHALL be stored with both the specific contract (`TX202604`) and generic symbol (`TX`)

#### Scenario: Query stitched series
- **WHEN** `get_stitched_ohlcv(symbol, method, start, end)` is called
- **THEN** it SHALL invoke `ContractStitcher` and return a `StitchedSeries`

### Requirement: Contract rolls table
The data layer SHALL track futures contract roll events.

#### Scenario: Roll event storage
- **WHEN** a roll is detected
- **THEN** `contract_rolls` table SHALL store: roll date, old contract, new contract, adjustment factor

#### Scenario: Roll history query
- **WHEN** `get_roll_history(symbol)` is called
- **THEN** it SHALL return all roll events for that symbol ordered by date

### Requirement: ADV computation
The data layer SHALL compute average daily volume for the impact model.

#### Scenario: ADV from OHLCV
- **WHEN** `get_adv(symbol, lookback_days=20)` is called
- **THEN** it SHALL return average daily volume over the last 20 trading days

#### Scenario: ADV in backtest (PIT-safe)
- **WHEN** ADV is requested at simulated time T
- **THEN** it SHALL use only volume data with `event_time < T`

#### Scenario: No volume data
- **WHEN** no data exists for the symbol
- **THEN** it SHALL return `None`
