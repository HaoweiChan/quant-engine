## ADDED Requirements

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
The Database class SHALL expose methods for querying and inserting margin snapshots.

#### Scenario: Insert margin snapshot
- **WHEN** `add_margin_snapshot(snapshot)` is called
- **THEN** the snapshot SHALL be persisted

#### Scenario: Get latest margin
- **WHEN** `get_latest_margin(symbol)` is called
- **THEN** it SHALL return the most recent MarginSnapshot or None

#### Scenario: Get margin history
- **WHEN** `get_margin_history(symbol, start, end)` is called with optional date filters
- **THEN** it SHALL return margin snapshots ordered by scraped_at ascending
