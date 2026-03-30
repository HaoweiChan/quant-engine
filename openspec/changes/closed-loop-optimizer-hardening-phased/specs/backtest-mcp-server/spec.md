## MODIFIED Requirements

### Requirement: run_parameter_sweep tool
The server SHALL expose a `run_parameter_sweep` tool that searches over parameter space and returns ranked results with explicit mode selection: `research` (fast synthetic) or `production_intent` (real-data walk-forward default).

#### Scenario: Production-intent sweep defaults to real-data walk-forward
- **WHEN** `run_parameter_sweep` is called with `mode="production_intent"`
- **THEN** it SHALL require market dataset context (`symbol`, date range, or equivalent configured source)
- **AND** SHALL run walk-forward evaluation before returning promotable candidates

#### Scenario: Research sweep allows synthetic quick iteration
- **WHEN** `run_parameter_sweep` is called with `mode="research"` and synthetic scenario inputs
- **THEN** it MAY execute a faster synthetic sweep
- **AND** response SHALL be explicitly marked as research-only (not promotion-eligible)

#### Scenario: Promotion eligibility is returned
- **WHEN** `run_parameter_sweep` completes
- **THEN** the response SHALL include gate outcomes and a promotable/non-promotable status per best candidate

### Requirement: run_parameter_sweep auto-persistence
The `run_parameter_sweep` tool SHALL persist run outputs together with gate metadata and SHALL NOT auto-activate candidates.

#### Scenario: Persist gate metadata
- **WHEN** `run_parameter_sweep` completes
- **THEN** persisted run metadata SHALL include mode, phase, and gate pass/fail details

#### Scenario: No implicit activation
- **WHEN** `run_parameter_sweep` completes with a best candidate
- **THEN** candidate state SHALL remain non-active until explicit activation is requested

#### Scenario: Activation blocked on failed gates
- **WHEN** `activate_candidate` is requested for a candidate whose required gates failed
- **THEN** the tool SHALL return a rejection with failed gate reasons
