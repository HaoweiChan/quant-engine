## MODIFIED Requirements

### Requirement: Core entry point
Position Engine SHALL expose an `on_snapshot()` method as the sole entry point, called on every new bar/snapshot. Entry policy evaluation SHALL receive account context and entry order emission SHALL pass through a pre-trade margin gate.

```python
class PositionEngine:
    mode: Literal["model_assisted", "rule_only", "halted"]

    def on_snapshot(
        self,
        snapshot: MarketSnapshot,
        signal: MarketSignal | None = None,
        account: AccountState | None = None,
    ) -> list[Order]: ...
```

#### Scenario: Returns orders on each snapshot
- **WHEN** `on_snapshot()` is called with a valid `MarketSnapshot`
- **THEN** it SHALL return a `list[Order]` (possibly empty) representing all actions for this bar

#### Scenario: Signal is optional
- **WHEN** `on_snapshot()` is called without a signal (or `signal=None`)
- **THEN** the engine SHALL pass `None` to policies, which decide how to handle it

#### Scenario: Account context passed to entry policy
- **WHEN** entry policy evaluation is performed
- **THEN** the engine SHALL call `entry_policy.should_enter(snapshot, signal, engine_state, account)`

#### Scenario: Pre-trade margin gate allows entry
- **WHEN** `entry_policy.should_enter()` returns an `EntryDecision` AND `account.margin_available` is greater than required initial margin
- **THEN** the engine SHALL emit entry orders normally

#### Scenario: Pre-trade margin gate blocks entry
- **WHEN** `entry_policy.should_enter()` returns an `EntryDecision` AND required margin exceeds `account.margin_available`
- **THEN** the engine SHALL suppress entry order emission and record a structured rejection event

#### Scenario: Pre-trade margin gate without account
- **WHEN** `account` is `None` for live entry evaluation
- **THEN** the engine SHALL suppress entry order emission and record a missing-account rejection event

### Requirement: Stop-loss priority
Stop-loss checks SHALL remain highest priority, but entry logic SHALL include pre-trade margin validation before any entry order is emitted.

#### Scenario: Execution order with margin gate
- **WHEN** `on_snapshot()` is called
- **THEN** processing order SHALL be: (1) stop-loss check, (2) trailing stop update, (3) margin safety, (4) pre-trade risk evaluation, (5) entry decision, (6) pre-trade margin gate, (7) add-position, (8) circuit breaker

#### Scenario: Risk-reducing orders bypass margin gate
- **WHEN** stop-loss, trailing-stop, margin-safety, or circuit-breaker close orders are generated
- **THEN** they SHALL NOT be blocked by pre-trade entry margin validation
