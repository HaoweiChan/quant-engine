## ADDED Requirements

### Requirement: Market data store exposes live tick state
The `marketDataStore` SHALL expose a `lastLiveTick` field of type `OHLCVBar | null` that holds the currently-building candle bar updated by live ticks. The `lastLiveTick` SHALL be a separate top-level Zustand field, isolated from the `bars` array, to prevent unnecessary React reconciliation of the full bar history.

#### Scenario: Initial state has no live tick
- **WHEN** the store is initialized
- **THEN** `lastLiveTick` SHALL be `null`

#### Scenario: Historical load sets lastLiveTick
- **WHEN** `setBars(bars)` is called with a non-empty array
- **THEN** `lastLiveTick` SHALL be set to the last element of the provided array

#### Scenario: Historical load with empty array clears lastLiveTick
- **WHEN** `setBars([])` is called
- **THEN** `lastLiveTick` SHALL be `null`

### Requirement: Client-side tick-to-bar aggregation
The store SHALL expose a `processLiveTick(tick)` action accepting `{ price: number; volume: number; timestamp: string }`. This action SHALL aggregate the tick into the current OHLCV bar or roll over to a new bar based on the active `tfMinutes` timeframe.

#### Scenario: Tick aggregates into current bar
- **WHEN** a tick arrives with a timestamp within the current bar's timeframe window (`tickTime < currentBarTime + tfMinutes * 60_000`)
- **THEN** the store SHALL update `lastLiveTick` with `high = max(current.high, tick.price)`, `low = min(current.low, tick.price)`, `close = tick.price`, `volume = current.volume + tick.volume`
- **AND** the `bars` array SHALL NOT be modified

#### Scenario: Tick rolls over to new bar
- **WHEN** a tick arrives with a timestamp at or beyond the current bar's timeframe boundary (`tickTime >= currentBarTime + tfMinutes * 60_000`)
- **THEN** the store SHALL append the completed `lastLiveTick` to the `bars` array
- **AND** create a new `lastLiveTick` with `open = close = high = low = tick.price`, `volume = tick.volume`, and `timestamp` floored to the timeframe boundary

#### Scenario: Tick arrives before historical data is loaded
- **WHEN** `processLiveTick` is called while `bars` is empty
- **THEN** the tick SHALL be silently dropped and no state change SHALL occur

#### Scenario: New bar timestamp is floored to timeframe boundary
- **WHEN** a rollover tick arrives at `14:03:22` with `tfMinutes = 5`
- **THEN** the new bar's timestamp SHALL be `14:00:00` (floored to the 5-minute boundary)
