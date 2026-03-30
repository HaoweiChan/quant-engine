## MODIFIED Requirements

### Requirement: Position reconciliation
The system SHALL run reconciliation as a mandatory startup gate before enabling live strategy order generation, in addition to periodic runtime checks.

#### Scenario: Startup reconciliation gate
- **WHEN** the runtime starts or reconnects after connectivity loss
- **THEN** reconciliation SHALL run before strategy evaluation begins, comparing broker positions, open orders, and recent fills against local state

#### Scenario: Startup freeze until reconciliation complete
- **WHEN** startup reconciliation is in progress
- **THEN** the strategy process SHALL remain in frozen mode and MUST NOT emit new order intents

#### Scenario: Open order cleanup at startup
- **WHEN** startup reconciliation finds broker-side open orders not mapped to active strategy intents
- **THEN** the runtime SHALL cancel those open orders before allowing resume

#### Scenario: Orphan position at startup
- **WHEN** broker reports a position that the engine does not track
- **THEN** the reconciler SHALL mark startup as unsafe, emit urgent alerting, and require manual intervention before resume

### Requirement: Mismatch response policy
The system SHALL use controlled resume policy for critical mismatches and startup uncertainty.

#### Scenario: Controlled resume required
- **WHEN** reconciliation completes with no unresolved critical mismatch
- **THEN** trading SHALL remain paused until operator confirms resume action

#### Scenario: Critical mismatch blocks resume
- **WHEN** ghost or orphan positions remain unresolved
- **THEN** the system SHALL keep mode `halted` and SHALL NOT allow live order submission

#### Scenario: Resume audit trail
- **WHEN** operator issues resume confirmation
- **THEN** the system SHALL record who confirmed, when, and which reconciliation snapshot was accepted
