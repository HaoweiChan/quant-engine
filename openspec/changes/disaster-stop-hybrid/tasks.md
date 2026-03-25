## 1. Core Types

- [x] 1.1 Add `position_id: str` field (auto UUID4) to `Position` dataclass in `src/core/types.py`
- [x] 1.2 Add `parent_position_id: str | None = None` and `order_class: Literal["standard", "disaster_stop", "algo_exit"] = "standard"` to `Order` dataclass
- [x] 1.3 Add `disaster_atr_mult: float = 4.5` and `disaster_stop_enabled: bool = False` to `EngineConfig` dataclass
- [x] 1.4 Add validation: `disaster_atr_mult > 0` in `EngineConfig.__post_init__`
- [x] 1.5 Add `"disaster_stop"` to `Order.reason` type annotation / docstring
- [ ] 1.6 Run mypy strict — fix any type errors caused by new fields

## 2. Position Engine

- [x] 2.1 Update `PositionEngine` to set `parent_position_id=position.position_id` on all entry `Order` objects
- [x] 2.2 Update all algo exit order construction to set `order_class="algo_exit"` and `parent_position_id=position.position_id`
- [x] 2.3 Update circuit breaker close-all to set `order_class="algo_exit"` and `parent_position_id` per position
- [x] 2.4 Implement `close_position_by_disaster_stop(position_id, fill_price, fill_timestamp)` method on `PositionEngine`
- [ ] 2.5 Validate `EngineConfig.disaster_atr_mult > PyramidConfig.stop_atr_mult` in `create_pyramid_engine()` factory when `disaster_stop_enabled=True`

## 3. DisasterStopMonitor

- [ ] 3.1 Create `src/execution/disaster_stop_monitor.py` with `DisasterStopEntry` dataclass and `DisasterStopMonitor` class
- [ ] 3.2 Implement `register()`, `deregister()`, `active_count()` methods
- [ ] 3.3 Implement `compute_disaster_level()` standalone function
- [ ] 3.4 Implement `on_tick()`: breach detection with symbol filtering, `closed` flag guard, and `execute_fn` call
- [ ] 3.5 Wire alerting dispatcher call in `on_tick()` on breach (`DISASTER_STOP_FIRED`), non-blocking with error logging
- [ ] 3.6 Create `PaperDisasterStopMonitor` wrapper: gap-through check on bar open and intrabar `on_tick(low_price)` check

## 4. LiveExecutionEngine

- [ ] 4.1 Add `DisasterStopMonitor` instance to `LiveExecutionEngine.__init__()` (injected or constructed internally based on `disaster_stop_enabled`)
- [ ] 4.2 In `execute()`: after an entry fill, call `monitor.register()` with fill price and `daily_atr` from snapshot
- [ ] 4.3 In `execute()`: before sending an `order_class="algo_exit"` order, call `monitor.deregister(parent_position_id)`
- [ ] 4.4 In `execute()`: handle `order_class="disaster_stop"` fills — call `engine.close_position_by_disaster_stop()` and emit `DISASTER_STOP_FILLED` alert
- [ ] 4.5 Add `"active_disaster_stops"` to `get_fill_stats()` return dict

## 5. PaperExecutionEngine

- [ ] 5.1 Inject `PaperDisasterStopMonitor` into `PaperExecutionEngine`
- [ ] 5.2 On each simulated bar: run gap-through check before algo stop logic
- [ ] 5.3 Log paper disaster fills with same structured fields as live, plus `"paper": True` metadata

## 6. Reconciler

- [ ] 6.1 Update `Reconciler` to detect fills on `order_class="disaster_stop"` orders that arrived while engine was offline
- [ ] 6.2 On detection: call `engine.close_position_by_disaster_stop()` and emit `DISASTER_STOP_FILLED` alert
- [ ] 6.3 Ensure reconciled disaster fills are recorded in the trade log with `reason="disaster_stop"`

## 7. Tests

- [ ] 7.1 Unit: `test_disaster_stop_monitor.py` — register/deregister, tick breach (long/short), idempotent fire guard, symbol filtering
- [ ] 7.2 Unit: `test_compute_disaster_level.py` — long/short level computation, parametrized ATR multiples
- [ ] 7.3 Unit: `test_position_engine_disaster.py` — entry orders carry `parent_position_id`, algo exits carry `order_class="algo_exit"`, `close_position_by_disaster_stop` removes correct position
- [ ] 7.4 Unit: `test_core_types_order.py` — new fields default correctly, existing order construction unaffected
- [ ] 7.5 Unit: `test_engine_config_validation.py` — `disaster_atr_mult <= stop_atr_mult` raises `ValueError`
- [ ] 7.6 Integration: `test_live_execution_disaster.py` — entry fill → register → algo exit → deregister flow (mock monitor)
- [ ] 7.7 Integration: `test_paper_disaster_gap.py` — bar gap-through triggers paper disaster fill before algo stop
- [ ] 7.8 Integration: `test_reconciler_disaster.py` — offline disaster fill detected and position closed

## 8. Configuration & Feature Flag

- [ ] 8.1 Set `disaster_stop_enabled = false` in all existing strategy TOML configs (default off)
- [ ] 8.2 Add `disaster_atr_mult = 4.5` to TOML config schema documentation
- [ ] 8.3 Add config validation test: `disaster_stop_enabled=True` with valid and invalid `disaster_atr_mult` values
