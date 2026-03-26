## Purpose

Independent disaster stop monitor that runs as a separate asyncio task, watching per-position disaster stop levels and firing emergency market exits when price crosses a disaster level. Operates independently of the main PositionEngine loop to ensure stops execute even if the engine stalls.

## Requirements

### Requirement: DisasterStopMonitor class
The system SHALL define a `DisasterStopMonitor` in `src/execution/disaster_stop_monitor.py` as a separate asyncio task that independently watches per-position disaster stop levels and fires emergency market exits when price crosses a disaster level, independently of the main `PositionEngine` loop.

```python
@dataclass
class DisasterStopEntry:
    position_id: str
    direction: Literal["long", "short"]
    disaster_level: float
    lots: float
    contract_type: str
    symbol: str
    closed: bool = False

class DisasterStopMonitor:
    def __init__(self, execute_fn: Callable[[list[Order]], Awaitable[None]]) -> None: ...

    def register(self, entry: DisasterStopEntry) -> None: ...
    def deregister(self, position_id: str) -> None: ...
    async def on_tick(self, price: float, symbol: str) -> None: ...
    def active_count(self) -> int: ...
```

#### Scenario: Register disaster stop on entry fill
- **WHEN** `register(entry)` is called with a `DisasterStopEntry`
- **THEN** the monitor SHALL add it to its internal registry keyed by `position_id`

#### Scenario: Deregister removes entry
- **WHEN** `deregister(position_id)` is called
- **THEN** the monitor SHALL remove the entry and it SHALL no longer fire on subsequent ticks

#### Scenario: Deregister unknown position_id is no-op
- **WHEN** `deregister(position_id)` is called for a position not in the registry
- **THEN** the monitor SHALL NOT raise any exception

### Requirement: Disaster level breach detection
The monitor SHALL fire an emergency market exit when `on_tick()` is called with a price that crosses the disaster level for any registered position.

#### Scenario: Long disaster stop triggered
- **WHEN** `on_tick(price, symbol)` is called with `price <= entry.disaster_level` for a long position
- **THEN** the monitor SHALL call `execute_fn` with a market sell `Order` with `order_class="disaster_stop"`, `parent_position_id=entry.position_id`, and `reason="disaster_stop"`

#### Scenario: Short disaster stop triggered
- **WHEN** `on_tick(price, symbol)` is called with `price >= entry.disaster_level` for a short position
- **THEN** the monitor SHALL call `execute_fn` with a market buy `Order` with `order_class="disaster_stop"`, `parent_position_id=entry.position_id`, and `reason="disaster_stop"`

#### Scenario: Price within disaster range does not fire
- **WHEN** `on_tick(price, symbol)` is called with price between entry price and disaster level
- **THEN** the monitor SHALL NOT call `execute_fn`

#### Scenario: Idempotent fire guard
- **WHEN** the disaster stop fires and `entry.closed` is set to `True`
- **THEN** subsequent `on_tick()` calls SHALL NOT fire again for the same position

#### Scenario: Symbol filtering
- **WHEN** `on_tick(price, symbol)` is called with a `symbol` that does not match any registered entry's `symbol`
- **THEN** the monitor SHALL NOT fire any exits

### Requirement: Disaster level computation
The disaster stop level SHALL be computed at entry fill time and SHALL be wider than the algo stop to avoid normal market noise triggering it.

```python
def compute_disaster_level(
    entry_price: float,
    direction: Literal["long", "short"],
    daily_atr: float,
    disaster_atr_mult: float,
) -> float: ...
```

#### Scenario: Long disaster level is below entry
- **WHEN** `compute_disaster_level(entry_price, "long", daily_atr, disaster_atr_mult)` is called
- **THEN** it SHALL return `entry_price - disaster_atr_mult * daily_atr`

#### Scenario: Short disaster level is above entry
- **WHEN** `compute_disaster_level(entry_price, "short", daily_atr, disaster_atr_mult)` is called
- **THEN** it SHALL return `entry_price + disaster_atr_mult * daily_atr`

#### Scenario: disaster_atr_mult must exceed stop_atr_mult
- **WHEN** `EngineConfig` is validated with `disaster_atr_mult <= stop_atr_mult`
- **THEN** validation SHALL raise `ValueError` with message `"disaster_atr_mult must exceed stop_atr_mult"`

### Requirement: Monitor runs as independent asyncio task
The `DisasterStopMonitor` SHALL be started as a separate `asyncio.Task` so that a stall or exception in the main `PositionEngine` coroutine does not block disaster stop execution.

#### Scenario: Monitor task survives engine coroutine exception
- **WHEN** the main engine coroutine raises an unhandled exception and is cancelled
- **THEN** the monitor's asyncio task SHALL remain running and continue calling `on_tick()` as ticks arrive

#### Scenario: Monitor is isolated from engine state mutation
- **WHEN** `on_tick()` is executing
- **THEN** it SHALL NOT access or mutate any `PositionEngine` internal state — it only reads its own registry and calls `execute_fn`

### Requirement: Disaster stop alerting
The monitor SHALL emit a structured alert via the existing alerting dispatcher whenever a disaster stop fires.

#### Scenario: Alert on disaster fire
- **WHEN** a disaster stop fires for `position_id`
- **THEN** the monitor SHALL emit a structured alert with event code `"DISASTER_STOP_FIRED"`, `position_id`, `symbol`, `price`, and `disaster_level`

#### Scenario: Alert is non-blocking
- **WHEN** the alerting dispatcher call fails or times out
- **THEN** the monitor SHALL log the alert failure but SHALL still complete the `execute_fn` call without blocking

### Requirement: Paper trading disaster simulation
A `PaperDisasterStopMonitor` SHALL wrap `DisasterStopMonitor` for paper trading, simulating gap-through fills by checking the opening bar price against registered disaster levels.

#### Scenario: Gap-through fill in paper mode
- **WHEN** a new bar opens with `open_price <= disaster_level` for a long position
- **THEN** the paper monitor SHALL call `execute_fn` with a disaster stop exit at `open_price` (simulating a gap fill) before the engine processes the bar

#### Scenario: Non-gap bar does not simulate disaster fill
- **WHEN** a new bar opens within the disaster range and only the low crosses the level
- **THEN** the paper monitor SHALL check `on_tick(low_price, symbol)` to determine if the level was crossed intrabar, consistent with bar simulator behavior
