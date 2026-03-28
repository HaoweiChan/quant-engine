## MODIFIED Requirements

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

## ADDED Requirements

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
