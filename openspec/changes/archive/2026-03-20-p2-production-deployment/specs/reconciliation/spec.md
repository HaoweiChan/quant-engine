## ADDED Requirements

### Requirement: Position reconciliation
The system SHALL periodically compare PositionEngine's internal positions against the broker's reported positions via `api.list_positions()`.

#### Scenario: Reconciliation cadence
- **WHEN** the reconciler is running
- **THEN** it SHALL check positions every 60 seconds (configurable) as an asyncio task

#### Scenario: Position match
- **WHEN** engine positions match broker positions (same symbol, direction, quantity within tolerance)
- **THEN** the reconciler SHALL log a debug-level "reconciled OK" message

#### Scenario: Quantity mismatch
- **WHEN** engine shows N contracts but broker shows M contracts for the same symbol
- **THEN** the reconciler SHALL log a warning with both quantities and dispatch a Telegram alert

#### Scenario: Ghost position (engine-only)
- **WHEN** the engine has a position that the broker does not report
- **THEN** the reconciler SHALL log an error and dispatch an urgent Telegram alert

#### Scenario: Orphan position (broker-only)
- **WHEN** the broker reports a position that the engine does not track
- **THEN** the reconciler SHALL log an error and dispatch an urgent Telegram alert

### Requirement: Account state reconciliation
The system SHALL compare the engine's derived account state against the broker's margin and equity data via `api.margin()`.

#### Scenario: Equity deviation
- **WHEN** the engine's computed equity differs from broker-reported equity by more than a configurable threshold (default 1%)
- **THEN** the reconciler SHALL log a warning with both values

#### Scenario: Margin ratio cross-check
- **WHEN** broker-reported `risk_indicator` indicates margin stress (below a configurable threshold)
- **THEN** the reconciler SHALL trigger a risk alert via the notification dispatcher, independent of Risk Monitor's own checks

### Requirement: Mismatch response policy
The system SHALL take configurable actions on reconciliation mismatches.

#### Scenario: Alert-only mode (default)
- **WHEN** a mismatch is detected and policy is "alert"
- **THEN** the reconciler SHALL log and alert but take no corrective action

#### Scenario: Halt-on-mismatch mode
- **WHEN** a critical mismatch is detected (ghost or orphan position) and policy is "halt"
- **THEN** the reconciler SHALL set PositionEngine mode to "halted" and alert
