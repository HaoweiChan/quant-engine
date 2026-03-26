## Purpose

Unified event-driven engine that processes identical code paths for backtesting and live trading. Queue-based event system with typed event hierarchy, handler registration, and intra-bar tick drill-down.

## Requirements

### Requirement: Event types
Typed event hierarchy for all trading events.

```python
class EventType(Enum):
    MARKET = "market"
    SIGNAL = "signal"
    ORDER = "order"
    FILL = "fill"
    RISK = "risk"
    AUDIT = "audit"

@dataclass
class Event:
    event_type: EventType
    timestamp: datetime
    data: Any
```

#### Scenario: Event type discrimination
- **WHEN** an event is placed on the queue
- **THEN** it SHALL be dispatchable by `event_type` to the correct handler

#### Scenario: Priority ordering
- **WHEN** multiple events have the same timestamp
- **THEN** processing order SHALL be: RISK > FILL > MARKET > SIGNAL > ORDER > AUDIT

### Requirement: Event engine core
Queue-based processing loop dispatching events to registered handlers.

```python
class EventEngine:
    def __init__(self, config: EventEngineConfig | None = None) -> None: ...
    def register_handler(self, event_type: EventType, handler: Callable[[Event], list[Event] | None]) -> None: ...
    def push(self, event: Event) -> None: ...
    def run(self) -> None: ...
    def run_backtest(self, bars: list[dict], adapter: BaseAdapter, ...) -> BacktestResult: ...
```

#### Scenario: Handler registration
- **WHEN** a handler is registered for `EventType.MARKET`
- **THEN** it SHALL be called for every `MarketEvent`

#### Scenario: Event chaining
- **WHEN** a handler returns new events
- **THEN** those events SHALL be pushed to the queue

#### Scenario: Queue drains per bar
- **WHEN** a `MarketEvent` triggers a cascade
- **THEN** all cascaded events SHALL process before the next `MarketEvent`

#### Scenario: Empty queue termination
- **WHEN** queue is empty and no more data
- **THEN** `run()` SHALL return cleanly

### Requirement: Backtest mode
Feed historical bars as `MarketEvent` objects through the same handler chain.

#### Scenario: Bar-to-event conversion
- **WHEN** `run_backtest()` is called with bars
- **THEN** each bar SHALL become a `MarketEvent`

#### Scenario: Same code path as live
- **WHEN** backtest processes a `MarketEvent`
- **THEN** it SHALL invoke the exact same handlers as live

#### Scenario: BacktestRunner backward compatibility
- **WHEN** `BacktestRunner.run(bars, signals, timestamps)` is called
- **THEN** it SHALL delegate to `EventEngine.run_backtest()` and return `BacktestResult` unchanged

### Requirement: Intra-bar tick drill-down
Drill into tick-level resolution for volatile bars.

#### Scenario: Volatile bar detection
- **WHEN** `(bar.high - bar.low) > tick_drill_atr_mult × daily_atr`
- **THEN** engine SHALL generate synthetic ticks within the bar using `price_sequence.py`

#### Scenario: Stop-before-target resolution
- **WHEN** both stop-loss and take-profit are within bar range
- **THEN** tick drill-down SHALL determine which was hit first

#### Scenario: Normal bars bypass
- **WHEN** `(bar.high - bar.low) <= tick_drill_atr_mult × daily_atr`
- **THEN** bar SHALL be processed as single `MarketEvent`

#### Scenario: Drill-down disabled
- **WHEN** `tick_drill_enabled` is `False`
- **THEN** all bars processed as single events

### Requirement: Event engine configuration

```python
@dataclass
class EventEngineConfig:
    tick_drill_atr_mult: float = 2.0
    tick_drill_enabled: bool = True
    latency_delay_ms: float = 10.0
    max_events_per_bar: int = 1000
    audit_enabled: bool = True
```

#### Scenario: Config from TOML
- **WHEN** engine initialized
- **THEN** config SHALL load from TOML or accept dataclass
