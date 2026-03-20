## Context

`PositionEngine` is the central decision-making module in the signal flow: `Prediction Engine → Position Engine → Execution Engine`. It currently takes a `PyramidConfig` and embeds pyramid-specific logic (long-only entry, ATR-triggered adds, Chandelier Exit trailing stops) directly in its methods. This makes it impossible to test alternative strategies without modifying the engine.

The engine has 8 direct consumers: `BacktestRunner`, `PipelineRunner`, `scanner.grid_search`, `monte_carlo.run_monte_carlo`, `stress.run_stress_test`, plus 3 test files. `PipelineRunner` already receives a `PositionEngine` instance via DI; the others construct engines internally from `PyramidConfig`.

Current file layout:
```
src/core/
  types.py          # PyramidConfig, Position, Order, EngineState, etc.
  position_engine.py # 340 lines, strategy + state machine mixed
```

## Goals / Non-Goals

**Goals:**
- Separate strategy decisions from position state management
- Enable composable strategy combinations (entry × add × stop)
- Support both long and short positions in the engine
- Maintain backward compatibility via factory function
- Keep the refactor self-contained to `src/core/` + consumer wiring

**Non-Goals:**
- Implementing new strategies (mean-reversion, short-only, etc.) — this change only enables them
- Changing the external `on_snapshot()` → `list[Order]` contract
- Modifying Prediction Engine, Execution Engine, or Risk Monitor
- Multi-asset / portfolio-level position management
- Kelly sizing rework (stays in config, can become a policy later)

## Decisions

### Decision 1: Composition over inheritance for strategy pattern

**Choice:** Three ABC protocols (`EntryPolicy`, `AddPolicy`, `StopPolicy`) injected into `PositionEngine` via constructor.

**Why not inheritance (Template Method)?** With inheritance, a `MeanReversionEngine` would need to override 3+ methods. Combining `PyramidEntry` with `FixedStopPolicy` would require creating a new subclass. With composition, you get N×M×K combinations from N+M+K classes.

**Why not a single `Strategy` ABC?** Entry, add, and stop decisions have different signatures and lifecycles. A monolithic `Strategy` class would violate SRP and prevent mixing policies from different strategy families.

### Decision 2: Policy ABCs live in `src/core/policies.py`

**Choice:** New file `src/core/policies.py` contains ABC definitions, decision types, and the concrete pyramid/chandelier implementations.

**Why not split ABCs and implementations?** At this stage there's only one implementation family (pyramid). Splitting into `policies/base.py` + `policies/pyramid.py` is premature. When a second strategy family arrives, we split then.

### Decision 3: Direction on Position, not on Engine

**Choice:** `Position` gains `direction: Literal["long", "short"]`. The engine reads direction from each position to determine stop trigger logic and order sides.

**Why not engine-level direction?** A future portfolio engine might hold both long and short positions simultaneously. Per-position direction is more general and matches how the `bar_simulator` already handles direction (see `entry_checker.py`, `stop_checker.py`).

### Decision 4: Decision types carry intent, engine executes

**Choice:**
```
EntryDecision → lots, contract_type, initial_stop, direction
AddDecision   → lots, contract_type, move_existing_to_breakeven
```

The engine converts decisions into `Position` records and `Order` lists. Policies never mutate engine state directly.

**Why `move_existing_to_breakeven` on AddDecision?** Moving stops to breakeven on pyramid add is a strategy choice (pyramid does it, mean-reversion wouldn't). Rather than hardcoding it in the engine, the policy expresses intent and the engine enforces the constraint (stops only move favorably).

### Decision 5: EngineConfig for engine-level params, PyramidConfig stays for pyramid policies

**Choice:**
```
EngineConfig   → max_loss, margin_limit, trail_lookback (engine cares)
PyramidConfig  → lot_schedule, add_trigger_atr, stop_atr_mult, etc. (pyramid policy cares)
```

`PyramidConfig` keeps all its fields but is no longer passed to the engine. The engine only sees `EngineConfig`. `PyramidConfig` is consumed by the pyramid policy implementations.

### Decision 6: Factory function for backward compatibility

**Choice:** `create_pyramid_engine(config: PyramidConfig) -> PositionEngine` constructs the engine with pyramid policies, extracting `EngineConfig` from `PyramidConfig` fields.

This lets `BacktestRunner`, `scanner`, `monte_carlo`, `stress` migrate incrementally. They swap `PositionEngine(config)` → `create_pyramid_engine(config)` and everything works. Later, they can accept arbitrary engines.

### Decision 7: Direction-aware stop logic in engine

**Choice:** The engine's `_check_stops` becomes:
```
long:  trigger when price <= stop_level
short: trigger when price >= stop_level
```

The "stops only move favorably" constraint becomes:
```
long:  new_stop = max(new_stop, current_stop)   # can only move up
short: new_stop = min(new_stop, current_stop)   # can only move down
```

This is the engine's core invariant and stays in the engine, not in policies.

## Architecture

```
┌─────────────────────────────────────────────────┐
│                 PositionEngine                   │
│  (pure state machine)                           │
│                                                 │
│  State: positions[], high_history, mode          │
│  Invariants:                                    │
│    - stops only move favorably                  │
│    - circuit breaker halts engine               │
│    - margin safety reduces positions            │
│                                                 │
│  Delegates to:                                  │
│    ┌──────────────┐ ┌───────────┐ ┌───────────┐│
│    │ EntryPolicy  │ │ AddPolicy │ │ StopPolicy││
│    │ .should_enter│ │ .should_add│ │.update_stop││
│    └──────┬───────┘ └─────┬─────┘ └─────┬─────┘│
│           │               │             │       │
│    Returns:         Returns:       Returns:     │
│    EntryDecision    AddDecision    float (stop)  │
│    or None          or None                     │
└─────────────────────────────────────────────────┘

Concrete implementations (src/core/policies.py):
  PyramidEntryPolicy   ← extracted from _check_entry
  PyramidAddPolicy     ← extracted from _check_add_position
  ChandelierStopPolicy ← extracted from _update_trailing_stops

Factory:
  create_pyramid_engine(PyramidConfig) → PositionEngine
```

## Risks / Trade-offs

**[Risk] Breaking change to `Position` type** → All code that constructs `Position` must now pass `direction`. Mitigation: default `direction="long"` during transition, but mark as required in type definition. Search-and-replace is mechanical (6 construction sites in production code + tests).

**[Risk] Test churn** → `test_position_engine.py` (364 lines) constructs engines directly. Mitigation: factory function means changing `PositionEngine(config)` → `create_pyramid_engine(config)` in fixtures. Individual test logic unchanged — same inputs, same expected outputs.

**[Risk] Over-abstraction for current needs** → We only have one strategy family right now. Trade-off accepted: the abstraction cost is ~100 lines of ABCs + decision types, which is modest. The payoff comes when we add short strategies or mean-reversion, which is planned.

**[Risk] Performance regression from indirection** → Policy method calls add one level of indirection per bar per position. Mitigation: Python function call overhead is ~100ns; at 1000 bars × 4 positions = 4000 calls, that's 0.4ms total. Negligible vs. actual computation.

**[Trade-off] `EngineConfig` duplicates some `PyramidConfig` fields** → `max_loss` and `margin_limit` exist in both. The factory function copies them. Accepted for clean separation; the alternative (engine reaching into policy config) defeats the purpose.

## Open Questions

1. Should `BacktestRunner` take a `PositionEngine` instance directly (full flexibility) or a factory callable `() -> PositionEngine` (allows fresh engine per run)? Leaning toward factory callable since backtest needs a fresh engine per `run()` call.
2. Should `EngineState.pyramid_level` be renamed to something generic like `add_count`? It's currently pyramid-specific naming but the field itself (count of add operations) is strategy-agnostic.
