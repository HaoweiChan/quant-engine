## MODIFIED Requirements

### Requirement: Entry signal logic
Position Engine SHALL delegate entry decisions to the injected `EntryPolicy`. The engine executes the decision but does not determine entry conditions. Entry orders SHALL carry `parent_position_id` linking the order to the newly created `Position` so the execution engine can register the disaster stop.

#### Scenario: Enter on policy decision
- **WHEN** the engine is flat (no open positions) AND `entry_policy.should_enter()` returns an `EntryDecision`
- **THEN** the engine SHALL create a `Position` with the decision's `lots`, `direction`, `initial_stop`, and `contract_type`, and generate a corresponding `Order` with `parent_position_id=position.position_id` and `order_class="standard"`

#### Scenario: Policy rejects entry
- **WHEN** `entry_policy.should_enter()` returns `None`
- **THEN** the engine SHALL generate no entry orders

#### Scenario: Order side from direction
- **WHEN** the `EntryDecision` has `direction="long"`
- **THEN** the entry order's `side` SHALL be `"buy"`
- **WHEN** the `EntryDecision` has `direction="short"`
- **THEN** the entry order's `side` SHALL be `"sell"`

#### Scenario: Entry order carries position_id
- **WHEN** the engine creates a new `Position` with auto-generated `position_id`
- **THEN** the entry `Order.parent_position_id` SHALL equal that `Position.position_id`

## ADDED Requirements

### Requirement: Algo exit orders carry position_id and order_class
Position Engine SHALL tag all algorithmic exit orders with `parent_position_id` and `order_class="algo_exit"` so the `ExecutionEngine` knows which disaster stop to deregister before sending the broker order.

#### Scenario: Trailing stop exit carries position link
- **WHEN** the engine generates a close order because `snapshot.price <= position.stop_level` (trailing stop hit)
- **THEN** the `Order` SHALL have `parent_position_id=position.position_id`, `order_class="algo_exit"`, and `reason="trailing_stop"`

#### Scenario: Circuit breaker close-all carries position links
- **WHEN** the circuit breaker fires and generates close orders for all positions
- **THEN** each `Order` SHALL have `parent_position_id` set to the corresponding `Position.position_id` and `order_class="algo_exit"`

#### Scenario: Margin reduce orders are standard class
- **WHEN** the engine generates a reduce order due to margin breach
- **THEN** the `Order` SHALL have `order_class="standard"` (margin reduces are not algo exits linked to a specific stop)

### Requirement: External disaster stop close handling
Position Engine SHALL expose a method for the `ExecutionEngine` to notify it that a position was closed by a disaster stop fill, so internal state stays consistent.

```python
def close_position_by_disaster_stop(
    self, position_id: str, fill_price: float, fill_timestamp: datetime,
) -> None: ...
```

#### Scenario: Disaster stop close removes position
- **WHEN** `close_position_by_disaster_stop(position_id, fill_price, fill_timestamp)` is called
- **THEN** the engine SHALL remove the matching `Position` from its internal list, record the exit as a stop-loss, and update `pyramid_level` accordingly

#### Scenario: Unknown position_id is a no-op
- **WHEN** `close_position_by_disaster_stop(position_id, ...)` is called with a `position_id` that is not in the current positions list
- **THEN** the engine SHALL log a warning and take no further action (the position may have already been closed by the algo stop)

#### Scenario: Engine mode unchanged after disaster close
- **WHEN** a position is closed via `close_position_by_disaster_stop`
- **THEN** the engine mode SHALL remain unchanged unless all positions are now closed AND the total cumulative drawdown from this exit triggers the circuit breaker threshold
