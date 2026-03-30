## ADDED Requirements

### Requirement: Isolated intraday runtime topology
The system SHALL run the live intraday critical path as separate OS processes on a single host: Market Data Process, Strategy Process, and Execution Process. API and dashboard workloads MUST NOT share the same event loop as execution-critical order submission.

#### Scenario: Critical path isolation from API load
- **WHEN** the dashboard or FastAPI layer receives bursty user traffic
- **THEN** order submission latency in the Execution Process SHALL remain isolated from that traffic and continue processing queued execution commands

#### Scenario: Process failure containment
- **WHEN** the Strategy Process exits unexpectedly
- **THEN** the Market Data Process and Execution Process SHALL remain running, and the runtime supervisor SHALL mark strategy output as unavailable until recovery

### Requirement: Typed IPC contracts for quotes and order intents
Inter-process messages SHALL use explicit versioned dataclass contracts and monotonic sequence identifiers.

```python
@dataclass(frozen=True)
class QuoteEvent:
    stream_id: str
    seq: int
    symbol: str
    ts_ns: int
    bid: float
    ask: float
    last: float

@dataclass(frozen=True)
class SignalIntent:
    stream_id: str
    seq: int
    symbol: str
    side: str
    quantity: int
    ts_ns: int
    reason: str

@dataclass(frozen=True)
class ExecutionCommand:
    intent_id: str
    symbol: str
    side: str
    quantity: int
    ts_ns: int
    policy: str
```

#### Scenario: Sequence monotonicity enforcement
- **WHEN** a process receives a message with `seq` lower than the last committed sequence for the same `stream_id`
- **THEN** the message SHALL be treated as stale and ignored with a warning log

#### Scenario: Duplicate-safe replay handling
- **WHEN** a message with the same `(stream_id, seq)` arrives more than once
- **THEN** processing SHALL be idempotent and MUST NOT produce duplicate order submissions

### Requirement: Latency budget instrumentation
The runtime SHALL emit stage timestamps for quote-ingest, signal-emit, order-dispatch, and broker-ack to support live SLO tracking.

#### Scenario: Tick-to-order SLO measurement
- **WHEN** an order is dispatched from a live quote-driven signal
- **THEN** the system SHALL compute and record tick-to-order latency and include it in rolling P99 metrics

#### Scenario: SLO breach alerting
- **WHEN** rolling P99 tick-to-order latency exceeds 200 ms for the configured observation window
- **THEN** the system SHALL emit an alert and automatically downgrade to shadow-only mode unless operator override is enabled

### Requirement: Backpressure and overload safeguards
The runtime SHALL protect execution continuity when IPC queues accumulate faster than they can be consumed.

#### Scenario: Quote queue saturation
- **WHEN** quote backlog exceeds configured capacity
- **THEN** the strategy process SHALL drop superseded quote events per symbol while preserving the latest quote snapshot and SHALL emit a saturation alert

#### Scenario: Execution queue saturation
- **WHEN** execution command backlog exceeds configured capacity
- **THEN** the system SHALL halt new signal emission and raise a critical risk event until backlog returns below threshold
