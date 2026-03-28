## Purpose

Translate abstract Order objects into broker-specific API calls. Handle slippage tracking, retries, partial fills, and paper trading simulation. Routes orders to the correct market adapter.

## Requirements

### Requirement: Execution Engine interface
Execution Engine SHALL expose async `execute()` and `get_fill_stats()` methods. Now receives orders from OMS (sliced or passthrough).

```python
class ExecutionEngine(ABC):
    async def execute(self, orders: list[Order]) -> list[ExecutionResult]: ...
    def get_fill_stats(self) -> dict[str, float]: ...
```

#### Scenario: Execute orders from OMS
- **WHEN** `execute()` is awaited with a list of `Order` objects (from OMS child orders or passthrough)
- **THEN** it SHALL return a list of `ExecutionResult` objects, one per order, indicating fill status, fill price, and slippage

#### Scenario: Empty order list
- **WHEN** `execute()` is awaited with an empty list
- **THEN** it SHALL return an empty list without making any broker API calls

#### Scenario: Paper executor compatibility
- **WHEN** the paper executor's `execute()` is awaited
- **THEN** it SHALL return results immediately with no behavioral change from the synchronous version

### Requirement: Broker-specific translation
Execution Engine SHALL translate abstract `Order` objects into broker-specific API calls via the appropriate market adapter.

#### Scenario: Order routing
- **WHEN** an `Order` for symbol `"TX"` is executed
- **THEN** the engine SHALL route it through the TaifexAdapter's broker SDK (shioaji)

#### Scenario: Contract translation
- **WHEN** an `Order` has `contract_type="large"`
- **THEN** the adapter SHALL translate it to the actual contract code (e.g., `"TX"` for TAIFEX large)

### Requirement: Slippage tracking
Execution Engine SHALL track slippage between expected and actual fill prices.

#### Scenario: Record slippage
- **WHEN** an order is filled
- **THEN** the `ExecutionResult` SHALL record `expected_price`, `fill_price`, and `slippage = fill_price - expected_price`

#### Scenario: Slippage statistics
- **WHEN** `get_fill_stats()` is called
- **THEN** it SHALL return aggregate slippage statistics (mean, median, P95, max) across recent fills

### Requirement: Retry and error handling
Execution Engine SHALL handle transient broker errors with configurable retry logic.

#### Scenario: Transient network error
- **WHEN** a broker API call fails with a transient error (timeout, connection reset)
- **THEN** the engine SHALL retry up to a configurable number of times with exponential backoff

#### Scenario: Permanent rejection
- **WHEN** a broker rejects an order (insufficient margin, invalid symbol)
- **THEN** the engine SHALL NOT retry and SHALL return an `ExecutionResult` with failure status and rejection reason

#### Scenario: Partial fills
- **WHEN** an order is partially filled
- **THEN** the `ExecutionResult` SHALL report the partial fill quantity and the remaining unfilled quantity

### Requirement: Order validation
Execution Engine SHALL validate orders before submission to the broker.

#### Scenario: Margin check before submit
- **WHEN** an order would exceed available margin
- **THEN** the engine SHALL reject the order locally before sending to the broker

#### Scenario: Trading hours check
- **WHEN** an order is submitted outside of trading hours
- **THEN** the engine SHALL queue or reject the order based on configuration

### Requirement: Paper trading mode
Execution Engine SHALL support a paper trading mode that simulates fills against live or historical prices without placing real orders.

#### Scenario: Paper executor
- **WHEN** the engine is in paper mode and `execute()` is called
- **THEN** it SHALL simulate fills at current market price with configurable slippage (fixed points or random) and return synthetic `ExecutionResult` objects

#### Scenario: Paper fill logging
- **WHEN** a paper fill occurs
- **THEN** it SHALL be logged with the same detail as a live fill (expected price, fill price, slippage) for comparison analysis

### Requirement: Execution logging
Every order submission, fill, rejection, and retry SHALL be logged via structlog with full context.

#### Scenario: Structured event logging
- **WHEN** any execution event occurs (submit, fill, reject, retry)
- **THEN** a structured log entry SHALL be emitted containing order details, timestamp, result, and any error information

### Requirement: Live executor
Execution Engine SHALL provide a `LiveExecutor` implementation that places real orders via the shioaji broker API for TAIFEX futures. Shioaji uses callback-based fill notifications on a C++ thread; the executor SHALL bridge these to asyncio.

#### Scenario: Place futures order
- **WHEN** a market `Order` is submitted for a TAIFEX futures contract
- **THEN** the executor SHALL call `api.place_order()` with the correct contract, action, price_type, order_type, and octype, and await fill confirmation via callback

#### Scenario: Stop order via IOC limit
- **WHEN** a stop `Order` is submitted and the current price has crossed the stop level
- **THEN** the executor SHALL place an IOC limit order at the stop price (TAIFEX does not support native stop orders via API)

#### Scenario: Fill confirmation via callback
- **WHEN** an order is placed and the exchange sends a DealEvent callback
- **THEN** the executor SHALL resolve the pending order's asyncio Future with the fill price, quantity, and timestamp from the callback, bridging from shioaji's C++ thread via `loop.call_soon_threadsafe()`

#### Scenario: Order timeout
- **WHEN** no fill confirmation is received within a configurable timeout (default 30s)
- **THEN** the executor SHALL cancel the order via `api.cancel_order()` and return an ExecutionResult with status "cancelled"

#### Scenario: Simulation mode
- **WHEN** the executor is configured with `simulation=True`
- **THEN** it SHALL connect to shioaji's simulation environment (`sj.Shioaji(simulation=True)`) for end-to-end testing without real capital

### Requirement: Gradual rollout controls
Execution Engine SHALL support configurable position size limits to enable gradual scaling from paper to live trading.

#### Scenario: Max contracts per order
- **WHEN** an order exceeds the configured `max_contracts_per_order` limit
- **THEN** the executor SHALL reject the order locally with reason "exceeds_rollout_limit"

#### Scenario: Max total exposure
- **WHEN** total open position lots would exceed `max_total_contracts` after filling this order
- **THEN** the executor SHALL reject new entry and add-position orders

#### Scenario: Rollout config
- **WHEN** rollout limits are loaded from TOML config
- **THEN** they SHALL include `max_contracts_per_order`, `max_total_contracts`, and `enabled` (bool to bypass limits)

### Requirement: Live fill comparison
Execution Engine SHALL track live fills and compare against backtest expectations for ongoing strategy validation. Extended with impact model comparison.

#### Scenario: Fill deviation tracking
- **WHEN** a live fill occurs
- **THEN** the executor SHALL record the fill price and slippage alongside the corresponding backtest expected fill (if available) for comparison

#### Scenario: Deviation statistics (extended)
- **WHEN** `get_fill_stats()` is called
- **THEN** it SHALL include live-vs-backtest deviation metrics: mean fill deviation, P95 deviation, count of fills exceeding expected slippage by 2x, AND new fields: `predicted_impact_accuracy` (correlation between predicted and actual impact) and `oms_algorithm_performance` (fill quality per algorithm)

### Requirement: OMS integration
Execution Engine SHALL accept orders from the OMS and track parent-child order relationships.

#### Scenario: Child order tracking
- **WHEN** the OMS submits child orders from a sliced parent order
- **THEN** the Execution Engine SHALL track the parent-child relationship and aggregate fill statistics at the parent order level

#### Scenario: Parent order completion
- **WHEN** all child orders of a parent are filled
- **THEN** the Execution Engine SHALL compute the aggregate VWAP fill price and total slippage for the parent order

#### Scenario: Passthrough orders
- **WHEN** an order arrives without a parent relationship (passthrough from OMS)
- **THEN** the Execution Engine SHALL process it as a standalone order (existing behavior)

### Requirement: Impact model feedback loop
Execution Engine SHALL report actual fill impact back to the impact model for calibration.

#### Scenario: Actual impact reporting
- **WHEN** a live fill completes
- **THEN** the executor SHALL compute the actual market impact (fill_price - mid_price at order time) and publish it to the impact model

#### Scenario: Impact calibration data
- **WHEN** `get_fill_stats()` is called
- **THEN** it SHALL include `impact_model_error` (mean absolute error between predicted and actual impact over recent fills)

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
