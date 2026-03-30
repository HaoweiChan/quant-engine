## MODIFIED Requirements

### Requirement: Live executor
Execution Engine SHALL provide a `LiveExecutor` implementation that places real orders via the shioaji broker API for TAIFEX futures and routes orders through an adaptive-by-volatility state machine. Shioaji uses callback-based fill notifications on a C++ thread; the executor SHALL bridge these to asyncio while enforcing bounded cancel-replace behavior.

#### Scenario: Adaptive initial order placement
- **WHEN** a TAIFEX entry order is submitted
- **THEN** the executor SHALL choose initial order aggressiveness based on the configured volatility regime policy (`calm`, `normal`, `high`) and submit the corresponding order type

#### Scenario: Place futures order
- **WHEN** a market or limit `Order` is submitted for a TAIFEX futures contract
- **THEN** the executor SHALL call `api.place_order()` with the correct contract, action, price_type, order_type, and octype, and track the order lifecycle until terminal state

#### Scenario: Fill confirmation via callback
- **WHEN** an order is placed and the exchange sends a DealEvent callback
- **THEN** the executor SHALL resolve the pending order's asyncio Future with fill price, quantity, and timestamp using `loop.call_soon_threadsafe()`

#### Scenario: Cancel-replace chase with bounded retries
- **WHEN** a working order remains unfilled past its regime-specific wait budget and alpha remains valid
- **THEN** the executor SHALL cancel and replace at a more aggressive price, up to configured `max_retries`, and SHALL stop chasing once retries are exhausted

#### Scenario: Partial fills during chase
- **WHEN** an order is partially filled before a cancel-replace step
- **THEN** the replacement order SHALL use only the remaining unfilled quantity and preserve parent-child linkage for reporting

#### Scenario: Order timeout
- **WHEN** no fill confirmation is received within the configurable timeout
- **THEN** the executor SHALL attempt cancellation and return an `ExecutionResult` with status `cancelled` if cancel succeeds, or `unknown` with a recovery flag if broker cancel acknowledgement is missing

#### Scenario: Volatility spike fallback
- **WHEN** live volatility transitions to `high` during an active chase
- **THEN** the executor SHALL switch to the high-volatility aggressiveness policy for remaining replacement attempts

#### Scenario: Simulation mode
- **WHEN** the executor is configured with `simulation=True`
- **THEN** it SHALL connect to shioaji's simulation environment (`sj.Shioaji(simulation=True)`) for end-to-end testing without real capital

### Requirement: Slippage tracking
Execution Engine SHALL track slippage between expected and actual fill prices and evaluate fill quality against a benchmark of 2 bps for intraday monitoring.

#### Scenario: Record slippage
- **WHEN** an order is filled
- **THEN** the `ExecutionResult` SHALL record `expected_price`, `fill_price`, and realized slippage in both absolute and basis-point terms

#### Scenario: Slippage statistics
- **WHEN** `get_fill_stats()` is called
- **THEN** it SHALL return aggregate slippage statistics (mean, median, P95, max) and benchmark comparison fields including `pct_over_2bps`

#### Scenario: Fill quality breach alert
- **WHEN** rolling slippage breach ratio exceeds configured tolerance for the strategy window
- **THEN** the executor SHALL emit a warning alert and mark execution quality status as degraded
