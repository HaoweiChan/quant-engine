## ADDED Requirements

### Requirement: MDD computation across paths
The system SHALL compute maximum drawdown for each simulated equity path.

#### Scenario: MDD per path
- **WHEN** a set of simulated equity paths is provided
- **THEN** the system SHALL compute the maximum peak-to-trough drawdown (as a percentage) for each path

#### Scenario: MDD from flat equity
- **WHEN** an equity path is constant (no change)
- **THEN** MDD SHALL be 0.0

#### Scenario: MDD from monotonically increasing equity
- **WHEN** an equity path only increases
- **THEN** MDD SHALL be 0.0

### Requirement: Confidence-level MDD statistics
The system SHALL report MDD at configurable confidence levels.

#### Scenario: 95th percentile MDD
- **WHEN** `confidence_level=0.95` is specified (default)
- **THEN** the system SHALL return the MDD value at the 95th percentile of all paths' MDDs

#### Scenario: Median MDD
- **WHEN** MDD distribution is computed
- **THEN** the system SHALL also return the median (P50) MDD

#### Scenario: Full MDD distribution
- **WHEN** MDD analysis completes
- **THEN** the result SHALL include the list of all individual path MDDs for histogram visualization
