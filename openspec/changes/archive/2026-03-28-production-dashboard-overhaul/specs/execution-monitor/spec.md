## ADDED Requirements

### Requirement: API heartbeat endpoint
The backend SHALL expose `GET /api/heartbeat` that pings each connected broker gateway and returns per-broker latency measurements.

```python
@dataclass
class HeartbeatResponse:
    brokers: list[BrokerHeartbeat]
    timestamp: str  # ISO 8601

@dataclass
class BrokerHeartbeat:
    account_id: str
    broker: str
    latency_ms: float | None  # None if disconnected
    status: str  # "ok" | "slow" | "disconnected"
```

#### Scenario: All brokers healthy
- **WHEN** `GET /api/heartbeat` is called and all brokers respond within 100ms
- **THEN** each `BrokerHeartbeat` SHALL have `status: "ok"` and `latency_ms` set to the measured round-trip time

#### Scenario: Broker responds slowly
- **WHEN** a broker responds in 500ms or more
- **THEN** that broker's `BrokerHeartbeat` SHALL have `status: "slow"`

#### Scenario: Broker disconnected
- **WHEN** a broker fails to respond or raises a connection error
- **THEN** that broker's `BrokerHeartbeat` SHALL have `status: "disconnected"` and `latency_ms: null`

### Requirement: Heartbeat monitor UI
The War Room top bar SHALL display a heartbeat indicator for the active account's broker, showing latency in milliseconds with color coding: green (< 100ms), yellow (100-500ms), red (>= 500ms or disconnected).

#### Scenario: Green heartbeat
- **WHEN** the active account's broker latency is 47ms
- **THEN** the indicator SHALL display "47ms" in green

#### Scenario: Yellow heartbeat
- **WHEN** the active account's broker latency is 350ms
- **THEN** the indicator SHALL display "350ms" in yellow/gold

#### Scenario: Red heartbeat
- **WHEN** the active account's broker is disconnected
- **THEN** the indicator SHALL display "DISCONNECTED" in red

#### Scenario: Heartbeat polls periodically
- **WHEN** the War Room tab is active
- **THEN** the frontend SHALL poll `GET /api/heartbeat` every 5 seconds and update the indicator

### Requirement: Slippage tracker in order blotter
The order blotter SHALL include slippage tracking columns for each fill: `Expected Price` (from the signal), `Fill Price` (actual), and `Slippage (bps)` computed as `abs(fill - expected) / expected * 10000`.

#### Scenario: Fill with positive slippage
- **WHEN** a buy order expected fill at 19500 but filled at 19510
- **THEN** the blotter row SHALL show Expected: 19500, Fill: 19510, Slippage: 5.1 bps

#### Scenario: Fill with zero slippage
- **WHEN** a limit order fills exactly at the expected price
- **THEN** Slippage SHALL display "0.0 bps"

### Requirement: Slippage alert threshold
The execution monitor SHALL compute a trailing-average slippage over the last 20 fills. When this average exceeds 2× the cost model's `slippage_bps` assumption, a risk alert SHALL fire.

#### Scenario: Slippage within tolerance
- **WHEN** trailing-average slippage is 4 bps and the cost model assumes 5 bps
- **THEN** no alert SHALL be fired

#### Scenario: Slippage exceeds threshold
- **WHEN** trailing-average slippage reaches 12 bps and the cost model assumes 5 bps
- **THEN** a risk alert SHALL fire with severity "warning" and message "Trailing slippage (12.0 bps) exceeds 2× assumed slippage (5 bps)"

#### Scenario: Alert appears in risk tab
- **WHEN** a slippage alert fires
- **THEN** it SHALL appear in the Risk tab's alert history table and in the War Room's alert log

### Requirement: WebSocket order blotter stream
The backend SHALL expose a `/ws/blotter` WebSocket endpoint that streams real-time order events (submissions, fills, rejections) for all active sessions.

```python
@dataclass
class BlotterEvent:
    event_type: str  # "submission" | "fill" | "rejection"
    timestamp: str
    account_id: str
    strategy: str
    symbol: str
    side: str  # "buy" | "sell"
    quantity: int
    expected_price: float | None
    fill_price: float | None
    fee: float | None
    rejection_reason: str | None
```

#### Scenario: Fill event streamed
- **WHEN** an order fills in the execution engine
- **THEN** the WS SHALL broadcast a `BlotterEvent` with `event_type: "fill"`, `fill_price`, and `fee` populated

#### Scenario: Rejection event streamed
- **WHEN** an order is rejected by the broker
- **THEN** the WS SHALL broadcast a `BlotterEvent` with `event_type: "rejection"` and `rejection_reason` populated

#### Scenario: Frontend receives and renders events
- **WHEN** the War Room blotter pane is active and a `BlotterEvent` arrives
- **THEN** the event SHALL be prepended to the blotter table in real-time without waiting for the next poll cycle
