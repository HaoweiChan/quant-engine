## 1. Types & Decision Objects (`src/core/types.py`)

- [x] 1.1 Add `direction: Literal["long", "short"] = "long"` field to `Position` dataclass. Add `__post_init__` validation for direction value. Verify: existing tests still pass since default is `"long"`.
- [x] 1.2 Add `EngineConfig` dataclass with `max_loss: float`, `margin_limit: float = 0.50`, `trail_lookback: int = 22`. Add `__post_init__` validation (max_loss > 0, 0 < margin_limit <= 1). Verify: `from src.core.types import EngineConfig` works.
- [x] 1.3 Add `EntryDecision` dataclass with `lots`, `contract_type`, `initial_stop`, `direction`, `metadata`. Add `__post_init__` validation (lots > 0, direction in {"long", "short"}). Verify: construction and validation tests pass.
- [x] 1.4 Add `AddDecision` dataclass with `lots`, `contract_type`, `move_existing_to_breakeven: bool = False`, `metadata`. Add `__post_init__` validation (lots > 0). Verify: construction and validation tests pass.

## 2. Policy ABCs & Pyramid Implementations (`src/core/policies.py`)

- [x] 2.1 Create `src/core/policies.py`. Define `EntryPolicy` ABC with `should_enter(snapshot, signal, engine_state) -> EntryDecision | None`. Define `AddPolicy` ABC with `should_add(snapshot, signal, engine_state) -> AddDecision | None`. Define `StopPolicy` ABC with `initial_stop(entry_price, direction, snapshot) -> float` and `update_stop(position, snapshot, high_history) -> float`. Verify: ABCs importable, cannot be instantiated directly.
- [x] 2.2 Implement `PyramidEntryPolicy(config: PyramidConfig)`. Extract logic from `PositionEngine._check_entry`. Include risk scaling (max_loss check), mode checks, signal validation. Verify: unit tests with same inputs as `test_position_engine.py::TestEntryLogic` produce identical decisions.
- [x] 2.3 Implement `PyramidAddPolicy(config: PyramidConfig)`. Extract logic from `PositionEngine._check_add_position`. Include margin headroom check. Set `move_existing_to_breakeven=True`. Verify: unit tests with same inputs as `TestPyramidAdds` produce identical decisions.
- [x] 2.4 Implement `ChandelierStopPolicy(config: PyramidConfig)`. Extract `initial_stop` from stop distance calculation. Extract `update_stop` with breakeven (layer 2) and chandelier (layer 3) logic. Support both long and short direction. Verify: unit tests with same inputs as `TestBreakevenStop` and `TestStopsOnlyMoveUpward` produce identical stop levels.
- [x] 2.5 Implement `NoAddPolicy` returning `None` unconditionally. Verify: `should_add()` returns `None` for any input.

## 3. Refactor PositionEngine (`src/core/position_engine.py`)

- [x] 3.1 Change `__init__` signature from `(config: PyramidConfig)` to `(entry_policy: EntryPolicy, add_policy: AddPolicy, stop_policy: StopPolicy, config: EngineConfig)`. Store policies as instance attributes. Remove `_pyramid_level` in favor of `len(self._positions)` for `add_count`. Verify: engine can be instantiated with policy objects.
- [x] 3.2 Replace `_check_entry` with delegation to `entry_policy.should_enter()`. Add `_execute_entry(decision, snapshot)` that creates Position (with direction) and Order (with direction-aware side). Verify: entry orders have correct side for long decisions.
- [x] 3.3 Replace `_check_add_position` with delegation to `add_policy.should_add()`. Add `_execute_add(decision, snapshot)` that creates Position, generates Order, and conditionally moves existing stops to breakeven based on `decision.move_existing_to_breakeven`. Verify: add orders generated correctly, breakeven applied when flag is True.
- [x] 3.4 Replace `_update_trailing_stops` with delegation to `stop_policy.update_stop()`. Engine enforces ratchet constraint: `max(new, current)` for long, `min(new, current)` for short. Verify: stops only move favorably for both directions.
- [x] 3.5 Make `_check_stops` direction-aware: `price <= stop` for long, `price >= stop` for short. Order side is opposite of position direction. Verify: long stops trigger on price drop, short stops trigger on price rise.
- [x] 3.6 Make `_check_margin_safety` direction-aware: reduce order side matches opposite of position direction. Make `_estimate_drawdown` direction-aware: PnL = `(price - entry) * lots * point_value` for long, `(entry - price) * lots * point_value` for short. Verify: drawdown calculated correctly for both directions.
- [x] 3.7 Make `_check_circuit_breaker` direction-aware: close order sides opposite of position directions. Verify: circuit breaker generates correct close sides.
- [x] 3.8 Add `create_pyramid_engine(config: PyramidConfig) -> PositionEngine` factory function. Extract `EngineConfig` from `PyramidConfig`, create pyramid policies, return assembled engine. Verify: `create_pyramid_engine(config)` produces engine with identical behavior to old `PositionEngine(config)`.

## 4. Update Consumers

- [x] 4.1 Update `BacktestRunner.__init__` to accept `engine_factory: Callable[[], PositionEngine]` instead of `config: PyramidConfig`. Add overload/fallback that accepts `PyramidConfig` and wraps with `create_pyramid_engine`. Update `run()` to call `engine_factory()` for fresh engine. Verify: existing backtest tests pass unchanged.
- [x] 4.2 Update `scanner.grid_search` to construct `PyramidConfig` per combo and pass `create_pyramid_engine` as factory. Verify: `test_scanner.py` passes.
- [x] 4.3 Update `monte_carlo.run_monte_carlo` to use updated `BacktestRunner`. Verify: `test_monte_carlo.py` passes.
- [x] 4.4 Update `stress.run_stress_test` and `run_liquidity_crisis` to use updated `BacktestRunner`. Verify: `test_stress.py` passes.
- [x] 4.5 Update `pipeline/config.py` `load_engine_config` to construct engine via `create_pyramid_engine`. Renamed pipeline's `EngineConfig` to `PipelineConfig` to avoid name clash. Verify: `test_pipeline.py` passes.

## 5. Tests

- [x] 5.1 Update `tests/conftest.py`: add `make_engine_state()` helper. Verify: helper produces valid `EngineState`.
- [x] 5.2 Create `tests/test_policies.py`: unit tests for `PyramidEntryPolicy`, `PyramidAddPolicy`, `ChandelierStopPolicy` in isolation. Test each scenario from the trading-policies spec. Include both long and short cases for `ChandelierStopPolicy`.
- [x] 5.3 Update `tests/test_position_engine.py`: replace `PositionEngine(config)` with `create_pyramid_engine(config)` in fixtures. All existing tests SHALL pass with zero logic changes (only fixture wiring). Verify: full test suite green.
- [x] 5.4 Add direction-aware tests in `test_position_engine.py`: short position stop triggers on price rise, short PnL calculation, short circuit breaker close sides. Verify: new tests pass.
- [x] 5.5 Run `pytest` full suite. Run `ruff check`. Fix lint issues. Verify: 284 tests pass, zero ruff errors.
