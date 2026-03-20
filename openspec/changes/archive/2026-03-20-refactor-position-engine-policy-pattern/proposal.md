## Why

`PositionEngine` currently mixes two distinct responsibilities: managing position state (open/close/update) and making strategy decisions (when to enter, when to add, how to compute stops). Entry logic is hardcoded long-only, add logic assumes ATR-threshold pyramiding, and stop logic is welded to Chandelier Exit. Testing a different strategy — short, mean-reversion, fixed-point stops — requires rewriting the engine itself. Separating the "state machine" from the "strategy" enables composable, testable strategies on top of a single stable engine.

## What Changes

- **BREAKING**: `Position` gains a `direction` field (`"long"` | `"short"`). All position consumers must handle direction.
- **BREAKING**: `PositionEngine.__init__` signature changes from `(config: PyramidConfig)` to `(entry_policy, add_policy, stop_policy, config: EngineConfig)`.
- New ABC protocols: `EntryPolicy`, `AddPolicy`, `StopPolicy` define the strategy interface.
- New decision types: `EntryDecision`, `AddDecision` carry structured intent from policies to engine.
- New `EngineConfig` dataclass with only engine-level params (max_loss, margin_limit, trail_lookback).
- Existing pyramid logic extracted into `PyramidEntryPolicy`, `PyramidAddPolicy`, `ChandelierStopPolicy`.
- Convenience factory `create_pyramid_engine(config: PyramidConfig) -> PositionEngine` for backward compatibility in consumers.
- `BacktestRunner`, `scanner`, `monte_carlo`, `stress` updated to use the factory or accept a pre-built engine.
- Engine internals become direction-aware: stop triggers, PnL calculations, order sides all respect `Position.direction`.

## Capabilities

### New Capabilities
- `trading-policies`: ABC protocols (`EntryPolicy`, `AddPolicy`, `StopPolicy`) and decision types (`EntryDecision`, `AddDecision`) defining the strategy interface. Includes concrete implementations: `PyramidEntryPolicy`, `PyramidAddPolicy`, `ChandelierStopPolicy`.

### Modified Capabilities
- `core-types`: `Position` gains `direction: Literal["long", "short"]`. New `EngineConfig` dataclass. New decision types `EntryDecision` and `AddDecision`.
- `position-engine`: Engine becomes a pure state machine. Constructor accepts policy objects. Stop/PnL logic becomes direction-aware. Adds factory function for backward compat.
- `simulator`: `BacktestRunner` accepts `PositionEngine` instance or factory instead of raw `PyramidConfig`.

## Impact

- **Core**: `src/core/types.py`, `src/core/position_engine.py` (major rewrite)
- **New file**: `src/core/policies.py` (policy ABCs + pyramid implementations)
- **Simulator**: `src/simulator/backtester.py`, `scanner.py`, `monte_carlo.py`, `stress.py` (constructor changes)
- **Pipeline**: `src/pipeline/config.py` (factory wiring), `src/pipeline/runner.py` (already takes engine — minimal change)
- **Tests**: `tests/test_position_engine.py`, `tests/conftest.py`, plus new `tests/test_policies.py`
- **Specs**: `openspec/specs/core-types/spec.md`, `openspec/specs/position-engine/spec.md`, `openspec/specs/simulator/spec.md`
