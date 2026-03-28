## Why

The current engine uses **engine-side synthetic stops**: the `PositionEngine` tracks stop levels in memory and emits a market-exit order when price crosses them. If the process crashes, the Sinopac API disconnects, or the host machine loses network during a volatile event, all open positions become unprotected and risk catastrophic ruin. A hybrid "Disaster Stop" model decouples the tight algorithmic stop (fast, zero-latency, in-memory) from a wide safety-net stop (process-crash-resistant, independently monitored) to preserve capital without sacrificing execution edge.

## What Changes

- **New**: `DisasterStopMonitor` — an asyncio task that independently watches price ticks and fires emergency market exits if the disaster stop level is crossed, regardless of the main engine's state
- **New**: Per-position disaster stop registration/deregistration lifecycle in `LiveExecutionEngine` and `PaperExecutionEngine`
- **Modified**: `Order` dataclass gains `parent_position_id: str | None` and `order_class: Literal["standard", "disaster_stop", "algo_exit"]` fields **BREAKING** (all callers must handle new fields)
- **Modified**: `LiveExecutionEngine.execute()` registers a disaster stop after entry fill and cancels it before/after algo exit
- **Modified**: `PaperExecutionEngine` simulates disaster stop fills on gap-through events for backtest fidelity
- **Modified**: Reconciler detects orphaned positions whose disaster stop filled while engine was offline, closes them as stop-loss exits

## Capabilities

### New Capabilities
- `disaster-stop-monitor`: Asyncio watchdog task that holds per-position disaster stop levels, subscribes to real-time price ticks, and fires market-exit orders when price crosses a disaster level independently of the main `PositionEngine`

### Modified Capabilities
- `core-types`: `Order` dataclass gains `parent_position_id` and `order_class` fields
- `execution-engine`: `LiveExecutionEngine` manages disaster stop lifecycle (register on fill, cancel on algo exit); `PaperExecutionEngine` simulates disaster fills on gap events
- `position-engine`: Emits entry orders with `parent_position_id` set to the new position's ID so the execution engine can link disaster stops back

## Impact

- `src/core/types.py` — `Order` dataclass change (breaking for all order constructors)
- `src/execution/live.py` — disaster stop registration/cancellation logic
- `src/execution/paper.py` — disaster stop simulation
- `src/reconciliation/reconciler.py` — orphan detection when disaster stop filled offline
- New file: `src/execution/disaster_stop_monitor.py`
- No change to `PositionEngine` stop calculation logic or `StopPolicy` ABCs
- **Constraint**: Because Shioaji does not support native resting stop orders, the disaster stop runs in a separate asyncio task within the same process — it protects against main-engine task failures and API handler crashes, but **not** against full host/instance failure
