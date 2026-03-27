## ADDED Requirements

### Requirement: Probability of ruin calculation
The system SHALL compute the fraction of simulated paths that breach configurable drawdown thresholds.

#### Scenario: Default ruin thresholds
- **WHEN** no custom thresholds are specified
- **THEN** the system SHALL compute ruin probability at -30%, -50%, and -100% drawdown levels

#### Scenario: Custom ruin thresholds
- **WHEN** `ruin_thresholds=[-0.20, -0.40, -0.60]` is specified
- **THEN** the system SHALL compute ruin probability for each threshold

#### Scenario: Zero ruin probability
- **WHEN** no simulated path breaches any threshold
- **THEN** ruin probability SHALL be 0.0 for all thresholds

#### Scenario: Full ruin
- **WHEN** all paths breach a given threshold
- **THEN** ruin probability for that threshold SHALL be 1.0

### Requirement: Ruin result structure
The system SHALL return ruin probabilities as a mapping from threshold labels to fractions.

#### Scenario: Result format
- **WHEN** ruin analysis completes with thresholds [-0.30, -0.50, -1.00]
- **THEN** the result SHALL be a dict like `{"-30%": 0.12, "-50%": 0.05, "-100%": 0.01}` with values in [0.0, 1.0]
