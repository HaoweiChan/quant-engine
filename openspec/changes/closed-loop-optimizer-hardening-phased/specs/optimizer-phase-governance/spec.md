## ADDED Requirements

### Requirement: Phase-aware optimizer governance
The optimization system SHALL expose a phase-aware governance model that separates rapid experimentation from production-intent promotion. Every optimization run SHALL record its phase, mode, and gate results before any candidate can be activated.

```python
class OptimizationPhase(TypedDict):
    phase: Literal["phase0_safety_rails", "phase1_fidelity", "phase2_structural_seed"]
    mode: Literal["research", "production_intent"]
    gates: dict[str, bool]
    gate_details: dict[str, float | str]
```

#### Scenario: Research mode bypasses promotion
- **WHEN** an optimization run is created with `mode="research"`
- **THEN** candidates MAY be ranked and persisted
- **AND** no candidate SHALL be auto-activated

#### Scenario: Production-intent run requires gate evaluation
- **WHEN** an optimization run is created with `mode="production_intent"`
- **THEN** the run SHALL evaluate required gates and persist a pass/fail result for each gate

#### Scenario: Phase metadata is queryable
- **WHEN** run history is requested
- **THEN** each run SHALL include `phase`, `mode`, and gate outcomes in the returned metadata

### Requirement: Promotion gate contract
Candidate activation SHALL require explicit gate compliance based on phase policy.

#### Scenario: Gate failure blocks activation
- **WHEN** at least one required gate is `False` for a production-intent run
- **THEN** candidate activation SHALL be rejected with an error listing failed gates

#### Scenario: Gate pass allows activation
- **WHEN** all required gates are `True` for a production-intent run
- **THEN** activation SHALL be allowed via explicit operator or API action

#### Scenario: Auto-activation disabled by default
- **WHEN** an optimization run completes
- **THEN** the system SHALL leave candidates in non-active state unless an explicit activation request is made
