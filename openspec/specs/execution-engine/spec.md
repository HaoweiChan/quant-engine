## Purpose

Translate abstract Order objects into broker-specific API calls. Handle slippage tracking, retries, partial fills, and paper trading simulation. Routes orders to the correct market adapter.

## Requirements

### Requirement: Execution Engine interface
Execution Engine SHALL expose async `execute()` and `get_fill_stats()` methods.

```python
class ExecutionEngine(ABC):
    async def execute(self, orders: list[Order]) -> list[ExecutionResult]: ...
    def get_fill_stats(self) -> dict: ...
```

#### Scenario: Execute orders
- **WHEN** `execute()` is awaited with a list of `Order` objects
- **THEN** it SHALL return a list of `ExecutionResult` objects, one per order, indicating fill status, fill price, and slippage

#### Scenario: Empty order list
- **WHEN** `execute()` is awaited with an empty list
- **THEN** it SHALL return an empty list without making any broker API calls

#### Scenario: Paper executor compatibility
- **WHEN** the paper executor's `execute()` is awaited
- **THEN** it SHALL return results immediately (trivial async wrapper) with no behavioral change from the synchronous version

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
Execution Engine SHALL track live fills and compare against backtest expectations for ongoing strategy validation.

#### Scenario: Fill deviation tracking
- **WHEN** a live fill occurs
- **THEN** the executor SHALL record the fill price and slippage alongside the corresponding backtest expected fill (if available) for comparison

#### Scenario: Deviation statistics
- **WHEN** `get_fill_stats()` is called
- **THEN** it SHALL include live-vs-backtest deviation metrics: mean fill deviation, P95 deviation, and count of fills that exceeded expected slippage by more than 2x
