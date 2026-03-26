## Purpose

The core trading logic module. Receives MarketSnapshot + MarketSignal, manages pyramid entries, 3-layer stop-loss, Kelly position sizing, and operating mode transitions. Produces Order lists for the Execution Engine.

## Requirements

### Requirement: Core entry point
Position Engine SHALL expose an `on_snapshot()` method as the sole entry point, called on every new bar/snapshot. Engine accepts policy objects via constructor. Extended with pre-trade risk gating.

```python
class PositionEngine:
    mode: Literal["model_assisted", "rule_only", "halted"]

    def __init__(
        self,
        entry_policy: EntryPolicy,
        add_policy: AddPolicy,
        stop_policy: StopPolicy,
        config: EngineConfig,
        pre_trade_check: PreTradeRiskCheck | None = None,
    ) -> None: ...

    def on_snapshot(
        self, snapshot: MarketSnapshot, signal: MarketSignal | None = None,
        account: AccountState | None = None,
    ) -> list[Order]: ...

    def set_mode(self, mode: str) -> None: ...
    def get_state(self) -> EngineState: ...
```

#### Scenario: Returns orders on each snapshot
- **WHEN** `on_snapshot()` is called with a valid `MarketSnapshot`
- **THEN** it SHALL return a `list[Order]` (possibly empty) representing all actions for this bar

#### Scenario: Signal is optional
- **WHEN** `on_snapshot()` is called without a signal (or `signal=None`)
- **THEN** the engine SHALL pass `None` to policies, which decide how to handle it

#### Scenario: Pre-trade risk gate on entry
- **WHEN** `pre_trade_check` is provided AND an entry order is generated
- **THEN** the engine SHALL evaluate the order against pre-trade risk limits BEFORE including it in the output

#### Scenario: Pre-trade risk rejects entry
- **WHEN** `pre_trade_check.evaluate()` returns `approved=False`
- **THEN** the entry order SHALL be suppressed and a structured log emitted with the rejection reason

#### Scenario: Pre-trade risk gate on add
- **WHEN** `pre_trade_check` is provided AND an add-position order is generated
- **THEN** the engine SHALL evaluate the order against pre-trade risk limits BEFORE including it in the output

#### Scenario: Pre-trade check not provided (backward compatible)
- **WHEN** `pre_trade_check` is `None`
- **THEN** all orders SHALL pass through without risk evaluation (existing behavior)

#### Scenario: Stop and circuit breaker orders bypass pre-trade check
- **WHEN** stop-loss, trailing-stop, margin-safety, or circuit-breaker orders are generated
- **THEN** they SHALL NOT be subject to pre-trade risk checks (risk-reducing orders must always execute)

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

### Requirement: Pyramid add-position logic
Position Engine SHALL delegate add-position decisions to the injected `AddPolicy`. The engine executes the decision but does not determine add conditions.

#### Scenario: Add on policy decision
- **WHEN** the engine has open positions AND `add_policy.should_add()` returns an `AddDecision`
- **THEN** the engine SHALL create a new `Position` and generate an add `Order`

#### Scenario: Breakeven adjustment on add
- **WHEN** `AddDecision.move_existing_to_breakeven` is `True`
- **THEN** the engine SHALL move all existing position stops to at least their entry prices (for longs) or at most their entry prices (for shorts)

#### Scenario: Breakeven not requested
- **WHEN** `AddDecision.move_existing_to_breakeven` is `False`
- **THEN** the engine SHALL NOT adjust existing stop levels

#### Scenario: Policy rejects add
- **WHEN** `add_policy.should_add()` returns `None`
- **THEN** the engine SHALL generate no add orders

### Requirement: Three-layer stop-loss
Position Engine SHALL delegate stop computation to the injected `StopPolicy`. The engine enforces the ratchet constraint (stops only move favorably).

#### Scenario: Initial stop from policy
- **WHEN** a new position is created
- **THEN** the initial stop SHALL be the value from the `EntryDecision.initial_stop` field (computed by the entry policy or stop policy)

#### Scenario: Stop update delegation
- **WHEN** trailing stop update runs each bar
- **THEN** the engine SHALL call `stop_policy.update_stop()` for each position and use the returned value

#### Scenario: Ratchet constraint for long
- **WHEN** `stop_policy.update_stop()` returns a value below the current stop for a long position
- **THEN** the stop level SHALL remain unchanged (only moves up)

#### Scenario: Ratchet constraint for short
- **WHEN** `stop_policy.update_stop()` returns a value above the current stop for a short position
- **THEN** the stop level SHALL remain unchanged (only moves down)

#### Scenario: Stop trigger for long
- **WHEN** `snapshot.price <= position.stop_level` for a long position
- **THEN** the engine SHALL generate a close `Order` with side `"sell"`

#### Scenario: Stop trigger for short
- **WHEN** `snapshot.price >= position.stop_level` for a short position
- **THEN** the engine SHALL generate a close `Order` with side `"buy"`

### Requirement: Stop-loss priority
Stop-loss checks SHALL be the highest-priority operation in the `on_snapshot()` execution order. They run before any other logic.

#### Scenario: Execution order (updated)
- **WHEN** `on_snapshot()` is called
- **THEN** the processing order SHALL be: (1) stop-loss check, (2) trailing stop update, (3) margin safety, (4) **pre-trade risk evaluation**, (5) entry signal, (6) add-position, (7) circuit breaker

### Requirement: Margin safety
Position Engine SHALL monitor `margin_ratio` and reduce positions if it exceeds the configured limit. Direction-aware order generation.

#### Scenario: Reduce on margin breach
- **WHEN** `margin_ratio > config.margin_limit`
- **THEN** the engine SHALL generate reduce `Order`(s) with the appropriate side based on position direction

### Requirement: Circuit breaker
Position Engine SHALL close all positions and halt when total drawdown reaches the configured `max_loss`. The threshold is loaded from `EngineConfig`.

#### Scenario: Max loss triggers halt
- **WHEN** total cumulative drawdown >= `config.max_loss`
- **THEN** the engine SHALL generate close-all `Order`(s) with reason `"circuit_breaker"` AND set its mode to `"halted"`

#### Scenario: Direction-aware close orders
- **WHEN** circuit breaker fires
- **THEN** each close order's `side` SHALL be the opposite of the position's direction (`"sell"` for longs, `"buy"` for shorts)

### Requirement: Operating modes
Position Engine SHALL support three operating modes: `model_assisted`, `rule_only`, and `halted`. Mode information is passed to policies via `EngineState`.

#### Scenario: model_assisted mode
- **WHEN** mode is `"model_assisted"`
- **THEN** the engine SHALL pass the full signal to policies for decision-making

#### Scenario: rule_only mode
- **WHEN** mode is `"rule_only"`
- **THEN** the engine SHALL pass `None` as signal to policies (policies decide how to handle absence of signal)

#### Scenario: halted mode
- **WHEN** mode is `"halted"`
- **THEN** the engine SHALL skip entry and add policy calls, but existing stop-loss logic SHALL remain active

#### Scenario: External mode override
- **WHEN** `set_mode()` is called
- **THEN** the engine SHALL immediately switch to the specified mode

### Requirement: Factory function
The system SHALL provide a `create_pyramid_engine()` factory function for backward compatibility.

```python
def create_pyramid_engine(config: PyramidConfig) -> PositionEngine: ...
```

#### Scenario: Factory produces working engine
- **WHEN** `create_pyramid_engine(config)` is called with a valid `PyramidConfig`
- **THEN** it SHALL return a `PositionEngine` configured with `PyramidEntryPolicy`, `PyramidAddPolicy`, and `ChandelierStopPolicy`

#### Scenario: Factory extracts EngineConfig
- **WHEN** `create_pyramid_engine(config)` is called
- **THEN** the `EngineConfig` SHALL have `max_loss`, `margin_limit`, and `trail_lookback` copied from the `PyramidConfig`

#### Scenario: Behavioral equivalence
- **WHEN** a `PositionEngine` created via `create_pyramid_engine(config)` processes identical inputs as the old `PositionEngine(config)`
- **THEN** it SHALL produce identical outputs (same orders, same positions, same stop levels)

### Requirement: Kelly position sizing
Position Engine SHALL use fractional Kelly criterion to determine position size, bounded by margin constraints.

#### Scenario: Quarter-Kelly default
- **WHEN** calculating position size for entry
- **THEN** the size SHALL be determined by `kelly_fraction` (default 0.25) of the full Kelly optimal, capped by margin availability

### Requirement: Multi-contract lot scheduling
Position Engine SHALL support mixed large/small/micro contract allocation per pyramid level via `lot_schedule`.

#### Scenario: Lot schedule per level
- **WHEN** entering at pyramid level N
- **THEN** the engine SHALL allocate lots according to `lot_schedule[N]`, where each entry is `[large_lots, small_lots]` (e.g., `[3, 4]` means 3 large + 4 small contracts)

### Requirement: Order metadata for OMS
Orders generated by Position Engine SHALL include metadata needed by the OMS for execution scheduling.

#### Scenario: Urgency classification
- **WHEN** a stop-loss or circuit-breaker order is generated
- **THEN** `order.metadata["urgency"]` SHALL be `"immediate"` (OMS passthrough)

#### Scenario: Entry/add urgency
- **WHEN** an entry or add-position order is generated
- **THEN** `order.metadata["urgency"]` SHALL be `"normal"` (OMS may slice)

#### Scenario: ADV hint
- **WHEN** any order is generated and account state is available
- **THEN** `order.metadata["estimated_adv"]` SHALL be populated with the average daily volume for the instrument (from snapshot or adapter)

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
