## ADDED Requirements

### Requirement: Disaster stop registration on entry fill
`LiveExecutionEngine` SHALL register a disaster stop in the `DisasterStopMonitor` immediately after an entry order is confirmed filled, when `disaster_stop_enabled` is `True`.

#### Scenario: Register after entry fill
- **WHEN** an `Order` with `reason="entry"` and `order_class="standard"` is filled
- **THEN** the engine SHALL call `monitor.register()` with a `DisasterStopEntry` containing the `position_id` from `order.parent_position_id`, direction, lots, symbol, and disaster level computed from `compute_disaster_level(fill_price, direction, daily_atr, config.disaster_atr_mult)`

#### Scenario: Register uses fill price not order price
- **WHEN** an entry order fills at a price different from the expected price (slippage)
- **THEN** the disaster level SHALL be computed from the actual `fill_price`, not the original order price

#### Scenario: No registration when disaster_stop_enabled is False
- **WHEN** `EngineConfig.disaster_stop_enabled` is `False`
- **THEN** the engine SHALL NOT call `monitor.register()` after any fill

#### Scenario: Registration failure does not block execution
- **WHEN** `monitor.register()` raises an exception
- **THEN** the engine SHALL log the error and continue — the entry fill result SHALL still be returned to the caller

### Requirement: Disaster stop deregistration on algo exit
`LiveExecutionEngine` SHALL deregister the disaster stop before or concurrently with sending an algorithmic exit order, to prevent double-exit race conditions.

#### Scenario: Deregister before algo exit send
- **WHEN** an `Order` with `order_class="algo_exit"` is received for execution
- **THEN** the engine SHALL call `monitor.deregister(order.parent_position_id)` BEFORE sending the market exit to the broker

#### Scenario: Deregister on circuit breaker close
- **WHEN** a close-all order with `reason="circuit_breaker"` is received
- **THEN** the engine SHALL call `monitor.deregister()` for each position ID in the batch before sending any broker orders

#### Scenario: Deregistration is idempotent
- **WHEN** `monitor.deregister(position_id)` is called for a position that was already deregistered
- **THEN** NO exception SHALL be raised and the algo exit SHALL proceed normally

### Requirement: Disaster stop fill reconciliation
`LiveExecutionEngine` SHALL detect when a disaster stop order has been filled (fired by the monitor) and ensure the corresponding internal position is closed in the engine state.

#### Scenario: Disaster fill closes internal position
- **WHEN** an `Order` with `order_class="disaster_stop"` is filled
- **THEN** the engine SHALL notify the `PositionEngine` to close the position identified by `parent_position_id` with `reason="disaster_stop"` at the fill price

#### Scenario: Disaster fill recorded as stop-loss exit
- **WHEN** a disaster stop fills
- **THEN** the resulting `ExecutionResult` SHALL have `reason="disaster_stop"` and the fill SHALL be recorded in the same trade log as a normal stop-loss exit

#### Scenario: Disaster fill emits alert
- **WHEN** a disaster stop fill is processed
- **THEN** the engine SHALL emit a `DISASTER_STOP_FILLED` alert via the alerting dispatcher containing `position_id`, `symbol`, `fill_price`, and `fill_timestamp`

### Requirement: PaperExecutionEngine disaster simulation
`PaperExecutionEngine` SHALL simulate disaster stop fills for positions that gap through their disaster level on bar open, before processing the bar's algo stop logic.

#### Scenario: Gap-through disaster fill in paper mode
- **WHEN** a new bar's `open_price` crosses a registered disaster level for any open position
- **THEN** the paper engine SHALL fill the disaster stop at `open_price` and close the position before running the algo stop check for that bar

#### Scenario: No disaster fill when open within disaster range
- **WHEN** a new bar's `open_price` is between the algo stop level and the disaster level
- **THEN** the paper engine SHALL NOT fill the disaster stop (the algo stop will handle it normally)

#### Scenario: Paper disaster fills are logged identically to live
- **WHEN** a paper disaster stop fills
- **THEN** it SHALL be logged with the same structured fields as a live disaster fill, with an additional `"paper": True` metadata flag

### Requirement: Disaster stop active count metric
`LiveExecutionEngine` SHALL expose the count of currently active disaster stops for observability.

#### Scenario: Active count exposed
- **WHEN** `get_fill_stats()` is called
- **THEN** the returned dict SHALL include `"active_disaster_stops": int` reflecting the current count from `monitor.active_count()`
