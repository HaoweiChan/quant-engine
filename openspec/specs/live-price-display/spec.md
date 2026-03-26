## Purpose

Real-time price ticker component showing current price, tick direction, symbol label, and WebSocket connection status for live trading monitoring.

## Requirements

### Requirement: Live price ticker component
The system SHALL provide a `LivePriceTicker` component that displays the current price from the live tick stream. The component SHALL subscribe to `lastLiveTick` from `marketDataStore`.

#### Scenario: Live tick received shows current price
- **WHEN** `lastLiveTick` is updated with a new tick
- **THEN** the component SHALL display the `close` price formatted to the instrument's decimal precision

#### Scenario: No live data available
- **WHEN** `lastLiveTick` is `null`
- **THEN** the component SHALL display a dash (`—`) or the last known historical close

### Requirement: Tick direction indicator
The component SHALL show a visual indicator of the tick direction by comparing the current `close` to the previous `close`.

#### Scenario: Price moved up
- **WHEN** the current `lastLiveTick.close` is greater than the previous close
- **THEN** the component SHALL display an upward arrow indicator in green (`#69f0ae`)

#### Scenario: Price moved down
- **WHEN** the current `lastLiveTick.close` is less than the previous close
- **THEN** the component SHALL display a downward arrow indicator in red (`#ff5252`)

#### Scenario: Price unchanged
- **WHEN** the current `lastLiveTick.close` equals the previous close
- **THEN** the component SHALL display a neutral indicator (no arrow, dim text color)

### Requirement: Symbol label display
The component SHALL display the active symbol name alongside the price.

#### Scenario: Symbol shown with price
- **WHEN** the component renders
- **THEN** it SHALL display the `symbol` from `marketDataStore` as a label next to the price

### Requirement: WebSocket connection status indicator
The system SHALL display a visual indicator of the WebSocket connection state.

#### Scenario: WebSocket connected
- **WHEN** the WebSocket connection to `/ws/live-feed` is established
- **THEN** a green dot or "LIVE" badge SHALL be visible near the price ticker

#### Scenario: WebSocket disconnected
- **WHEN** the WebSocket connection is lost
- **THEN** the indicator SHALL change to a red dot or "OFFLINE" badge

#### Scenario: WebSocket reconnecting
- **WHEN** the WebSocket is attempting to reconnect (exponential backoff in progress)
- **THEN** the indicator SHALL show a yellow/amber dot or "RECONNECTING" state
