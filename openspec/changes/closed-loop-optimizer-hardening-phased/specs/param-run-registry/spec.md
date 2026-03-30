## MODIFIED Requirements

### Requirement: Save optimization run with full trial data
`ParamRegistry.save_run()` SHALL persist complete optimization output including governance metadata required for phase-aware promotion decisions.

#### Scenario: Gate metadata persisted
- **WHEN** `save_run()` is called for a production-intent optimization run
- **THEN** the run metadata SHALL include phase, mode, and gate pass/fail details

#### Scenario: Best candidate created but not auto-active
- **WHEN** `save_run()` completes
- **THEN** a best candidate SHALL still be created
- **AND** the candidate SHALL remain `is_active=0` until explicit activation passes gate checks

#### Scenario: Research run marked non-promotable by default
- **WHEN** `save_run()` is called with `mode="research"`
- **THEN** persisted metadata SHALL mark the run as non-promotable unless manually overridden

### Requirement: Activate a parameter candidate
`ParamRegistry.activate()` SHALL enforce promotion-gate constraints for production-intent activation.

#### Scenario: Activation blocked by failed gates
- **WHEN** `activate(candidate_id)` is called and the candidate's parent run has failed required gates
- **THEN** activation SHALL be rejected with `ValueError` describing failed gates

#### Scenario: Activation succeeds when gates pass
- **WHEN** `activate(candidate_id)` is called and all required gates pass
- **THEN** the candidate SHALL become active and all same-strategy candidates SHALL be deactivated

#### Scenario: Audit trail includes gate context
- **WHEN** activation succeeds
- **THEN** activation metadata SHALL retain references to the governing phase/mode and gate outcomes used for approval
