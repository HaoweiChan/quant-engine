## MODIFIED Requirements

### Requirement: Core entry point
Position Engine SHALL expose an `on_snapshot()` method as the sole entry point, called on every new bar/snapshot. **Engine now accepts policy objects via constructor instead of PyramidConfig.**

```python
class PositionEngine:
    mode: Literal["model_assisted", "rule_only", "halted"]

    def __init__(
        self,
        entry_policy: EntryPolicy,
        add_policy: AddPolicy,
        stop_policy: StopPolicy,
        config: EngineConfig,
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

### Requirement: Entry signal logic
Position Engine SHALL delegate entry decisions to the injected `EntryPolicy`. The engine executes the decision but does not determine entry conditions.

#### Scenario: Enter on policy decision
- **WHEN** the engine is flat (no open positions) AND `entry_policy.should_enter()` returns an `EntryDecision`
- **THEN** the engine SHALL create a `Position` with the decision's `lots`, `direction`, `initial_stop`, and `contract_type`, and generate a corresponding `Order`

#### Scenario: Policy rejects entry
- **WHEN** `entry_policy.should_enter()` returns `None`
- **THEN** the engine SHALL generate no entry orders

#### Scenario: Order side from direction
- **WHEN** the `EntryDecision` has `direction="long"`
- **THEN** the entry order's `side` SHALL be `"buy"`
- **WHEN** the `EntryDecision` has `direction="short"`
- **THEN** the entry order's `side` SHALL be `"sell"`

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

#### Scenario: Execution order
- **WHEN** `on_snapshot()` is called
- **THEN** the processing order SHALL be: (1) stop-loss check, (2) trailing stop update, (3) margin safety, (4) entry signal, (5) add-position, (6) circuit breaker

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

## ADDED Requirements

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
