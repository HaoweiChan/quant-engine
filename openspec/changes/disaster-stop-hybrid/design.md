## Context

The current stop-loss is engine-side synthetic: `PositionEngine._check_stops()` compares `snapshot.price` against `position.stop_level` and emits a market exit order when crossed. This works perfectly during normal operation but leaves positions fully exposed if:

- The main engine coroutine crashes or deadlocks
- The Shioaji WebSocket drops and no new ticks arrive
- A gap-open moves price through the stop before the engine processes the first tick

Shioaji/TAIFEX does **not** support native resting Stop-Market orders, so we cannot delegate the safety stop to the exchange. The solution is a **Disaster Stop Monitor** — a separate `asyncio.Task` running in the same event loop that independently watches price ticks per position and fires emergency exits when the disaster level is crossed.

```
                       ┌──────────────────────────────────────────┐
                       │           Trading Process                │
                       │                                          │
  Market tick ─────────┤──► PositionEngine (algo stop, in-memory) │
                       │         │ entry order (+ position_id)    │
                       │         ▼                                │
                       │    ExecutionEngine                       │
                       │     - on fill: register disaster level   │
                       │       in DisasterStopMonitor             │
                       │     - on algo exit: deregister + cancel  │
                       │                                          │
  Market tick ─────────┤──► DisasterStopMonitor (separate task)  │
                       │     - holds: {pos_id → disaster_level}  │
                       │     - if price crosses disaster level:  │
                       │       fire market exit directly          │
                       │       → ExecutionEngine deregisters      │
                       └──────────────────────────────────────────┘
```

The monitor runs as a separate `asyncio.Task` so a deadlock in the engine coroutine cannot block it. Both coroutines share the same event loop and process — this is **intra-process isolation**, not inter-process.

## Goals / Non-Goals

**Goals:**
- Protect against engine task crash or deadlock during live trading
- Protect against gap-open events where price skips through the algo stop
- One disaster stop per `Position` (including pyramid adds), registered immediately on fill
- Paper engine simulates disaster fills on gap-through for backtest fidelity
- Reconciler handles offline disaster fills as normal stop-loss exits
- Zero changes to `StopPolicy` ABCs or `PositionEngine` stop-calculation logic

**Non-Goals:**
- Protection against full host/instance failure (requires exchange-native stops — not available)
- Protection against event-loop thread death (both tasks die together)
- Dynamic disaster stop trailing (disaster stop is static; only the algo stop trails)
- Sending `Cancel/Replace` to exchange (no native stop orders on TAIFEX)

## Decisions

### Decision 1: Asyncio task, not a separate process

**Chosen**: `asyncio.Task` in the same event loop.

**Alternatives considered**:
- Separate OS process: true isolation, but adds IPC complexity (shared memory or queue for position state), significantly higher engineering cost, and the tick feed would need to be duplicated or proxied.
- Separate thread: Shares memory with the main thread but asyncio is not thread-safe; would require locks everywhere ticks are read.

**Rationale**: An asyncio task is scheduled independently from the engine coroutine. A crash in one task does not propagate to the other task unless the event loop itself dies. The added complexity of IPC is not justified given the constraint that exchange-native stops are unavailable regardless.

### Decision 2: Static disaster level, registered once on fill

**Chosen**: Disaster level = `entry_price ± disaster_atr_mult * daily_atr` at time of fill, never updated.

**Alternatives considered**:
- Trailing disaster stop: Update disaster level as algo stop trails. Adds complexity (monitor must receive updates) and risks rate of update issues; defeats the "set and forget" simplicity.
- Fixed percentage: e.g., entry ± 3%. Simpler, but not ATR-normalized — overly tight in high-volatility regimes, overly loose in low-volatility.

**Rationale**: The disaster stop's purpose is catastrophic loss prevention, not exit optimization. It should be far enough from entry that normal volatility never reaches it, but close enough to prevent ruin. A static ATR multiple at entry achieves this with minimal complexity.

### Decision 3: One disaster stop per Position (pyramid-aware)

**Chosen**: Each `Position` object gets its own disaster stop registered when the corresponding entry fill arrives.

**Alternatives considered**:
- One aggregate stop per trade: Single stop covering total exposure. On partial close, the stop must be resized — this is complex and error-prone.
- Only protect initial entry: Pyramid adds are unprotected. Unacceptable given pyramid sizing is the core position-building mechanism.

**Rationale**: Since each `Position` has an independent `entry_price` and `stop_level`, registering per-position is the natural fit. On full close all pyramid positions deregister together.

### Decision 4: `Order` carries `parent_position_id` and `order_class`

**Chosen**: Extend `Order` with two optional fields.

```python
@dataclass
class Order:
    # ... existing fields unchanged ...
    parent_position_id: str | None = None
    order_class: Literal["standard", "disaster_stop", "algo_exit"] = "standard"
```

**Rationale**: The `ExecutionEngine` needs to know which disaster stop to cancel when an algo exit arrives, and which position to register a stop for after an entry fill. Encoding this in `Order` keeps the execution path stateless (no external lookup needed beyond `active_disaster_stops`).

### Decision 5: PaperExecutionEngine simulates gap-through disaster fills

**Chosen**: Paper engine checks whether the opening price of a new bar crosses the disaster level (gap scenario); if so, fills the disaster stop instead of the algo stop.

**Rationale**: Without this, backtests understate disaster stop behaviour in gap markets. The simulation should match live semantics: disaster stop fires before algo stop if the gap is large enough.

### Decision 6: Reconciler treats offline disaster fill as normal stop-loss

**Chosen**: When reconciliation detects a filled order matching a known disaster stop order ID, it closes the internal `Position` with `reason="disaster_stop"` and records exit at the disaster fill price.

**Rationale**: Keeps reconciliation semantics simple. No special circuit-breaker transition is needed — the position is simply closed. Operators are alerted via the existing alerting dispatcher with a `DISASTER_STOP_FILLED` event code.

## Risks / Trade-offs

| Risk | Mitigation |
|------|-----------|
| Event loop dies → both engine and monitor die together | Document clearly; true protection requires exchange-native stops or separate process (future work) |
| Disaster stop fires spuriously on a spike (algo stop is tighter) | Set `disaster_atr_mult` significantly wider than `stop_atr_mult` (e.g., 3× algo stop); add a config validation that asserts `disaster_atr_mult > stop_atr_mult` |
| Race: algo exit and disaster stop both fire simultaneously | `DisasterStopMonitor` checks a per-position `closed` flag before sending; `ExecutionEngine` deregisters before sending algo exit — idempotent close orders are harmless but we add a guard |
| `Order.order_class` breaks existing callers that construct `Order(...)` positionally | All existing `Order` constructors use keyword args; mypy strict will catch regressions at CI time |
| Paper disaster fill changes P&L vs current baseline | Expected: disaster fills are slightly worse than algo exits (wider stop). Backtests should note this as conservative |

## Migration Plan

1. Add `parent_position_id` and `order_class` to `Order` with defaults — backward compatible at runtime, mypy validates at CI
2. Implement `DisasterStopMonitor` as a standalone module with full unit tests before wiring it up
3. Update `LiveExecutionEngine` to register/deregister stops — gated behind a `disaster_stop_enabled: bool` config flag (default `False`) so existing live deployments are unaffected until tested
4. Update `PaperExecutionEngine` and add backtest comparison tests
5. Update reconciler and alerting
6. Flip `disaster_stop_enabled` to `True` in production config after end-to-end paper trading validation

## Open Questions

- Should `disaster_atr_mult` be a global `EngineConfig` field or a per-strategy `PyramidConfig` field? (Currently leaning toward `EngineConfig` since disaster stops are infrastructure, not strategy logic)
- What alerting channel should `DISASTER_STOP_FILLED` fire to? Telegram? (Assume same as existing `risk_monitor` alerts for now)
- Should the `DisasterStopMonitor` have its own heartbeat metric for observability?
