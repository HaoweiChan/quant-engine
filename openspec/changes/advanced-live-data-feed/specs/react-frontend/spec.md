## MODIFIED Requirements

### Requirement: WebSocket hooks for real-time data
The frontend SHALL provide React hooks (`useLiveFeed`, `useBacktestProgress`, `useRiskAlerts`) that manage WebSocket connections with automatic reconnection using exponential backoff. The `useLiveFeed` hook SHALL process incoming tick messages by calling `processLiveTick()` on `marketDataStore` to drive live bar aggregation and chart updates.

#### Scenario: Auto-reconnect on disconnect
- **WHEN** the WebSocket connection to `/ws/live-feed` is lost
- **THEN** the hook SHALL attempt reconnection with exponential backoff (1s, 2s, 4s, 8s, max 30s)

#### Scenario: Live feed processes tick messages
- **WHEN** a message with `type: "tick"` arrives on the live feed WebSocket containing `{ price, volume, timestamp }`
- **THEN** the `useLiveFeed` hook SHALL call `marketDataStore.processLiveTick({ price, volume, timestamp })`

#### Scenario: Live feed ignores non-tick messages
- **WHEN** a message with `type: "order"` or `type: "pong"` arrives on the live feed WebSocket
- **THEN** the `useLiveFeed` hook SHALL NOT call `processLiveTick`

#### Scenario: Malformed message handling
- **WHEN** a malformed or unparseable message arrives on the live feed WebSocket
- **THEN** the hook SHALL silently ignore the message without throwing or logging to the console
