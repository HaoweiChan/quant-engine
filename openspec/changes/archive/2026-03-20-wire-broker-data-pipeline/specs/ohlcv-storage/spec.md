## ADDED Requirements

### Requirement: OHLCVBar database model
The system SHALL define an `OHLCVBar` SQLAlchemy model for persisting historical 1-minute OHLCV data. The unique constraint SHALL be on (symbol, timestamp) — no timeframe column, since only 1-minute bars are stored. Thicker timeframes (5m, 1H, 4H, daily) SHALL be aggregated on demand from 1-minute data, never stored as separate rows.

#### Scenario: Store 1-minute bar
- **WHEN** a 1-minute OHLCV bar for symbol "TX" at a given timestamp is inserted
- **THEN** it SHALL be persisted with symbol, timestamp, open, high, low, close, volume

#### Scenario: Upsert on duplicate
- **WHEN** a bar with the same (symbol, timestamp) already exists
- **THEN** the system SHALL update the existing row instead of raising a duplicate error

#### Scenario: Query by date range
- **WHEN** `get_ohlcv(symbol, start, end)` is called
- **THEN** it SHALL return 1-minute bars ordered by timestamp ascending within the requested range

#### Scenario: No duplicate timeframe storage
- **WHEN** thicker timeframes (5m, 1H, 4H, daily) are needed
- **THEN** they SHALL be computed by aggregating 1-minute bars via the bar_builder, NOT stored as separate OHLCVBar rows

### Requirement: Data crawl pipeline
The system SHALL provide a `crawl_historical()` function that fetches 1-minute OHLCV data from SinopacConnector and persists it to the database.

#### Scenario: Crawl 1-minute data for date range
- **WHEN** `crawl_historical(symbol, start, end)` is called
- **THEN** it SHALL chunk the range into windows (max 60 days each), fetch 1-minute bars via SinopacConnector, validate, and upsert to DB

#### Scenario: Rate limiting between chunks
- **WHEN** multiple chunks are fetched sequentially
- **THEN** the crawler SHALL wait a configurable delay (default 1 second) between API calls

#### Scenario: Validation before storage
- **WHEN** fetched data contains nulls or gaps
- **THEN** the crawler SHALL log a warning via the connector's `validate()` method but still store the data (gaps are expected at session boundaries)

#### Scenario: Progress logging
- **WHEN** crawling a multi-chunk date range
- **THEN** the crawler SHALL log progress after each chunk (e.g., "Fetched TX 2024-01-01 to 2024-02-28 — 12,450 bars")

#### Scenario: Credentials from GSM
- **WHEN** the crawl pipeline initializes the SinopacConnector
- **THEN** it SHALL retrieve credentials from SecretManager, not from environment variables
