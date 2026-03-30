## ADDED Requirements

### Requirement: Long-only compatibility feature flag
The system SHALL provide a feature flag to preserve legacy long-only entry behavior during migration.

#### Scenario: Compatibility mode enabled
- **WHEN** `long_only_compat_mode` is `True`
- **THEN** entry policies SHALL suppress short entries even when `signal.direction < 0`

#### Scenario: Compatibility mode disabled
- **WHEN** `long_only_compat_mode` is `False`
- **THEN** entry policies SHALL evaluate both long and short entry opportunities symmetrically

### Requirement: Runtime-visible flag state
The feature-flag state SHALL be included in policy metadata and startup logs for operator visibility.

#### Scenario: Startup logs include flag state
- **WHEN** the engine initializes with policy config
- **THEN** logs SHALL include the resolved value of `long_only_compat_mode`

#### Scenario: Entry decision metadata includes compatibility context
- **WHEN** an entry decision is produced
- **THEN** decision metadata SHALL include whether compatibility mode influenced side selection
