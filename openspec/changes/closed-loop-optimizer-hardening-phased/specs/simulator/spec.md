## MODIFIED Requirements

### Requirement: Sequential optimization support
Simulator SHALL support the 2-stage sequential optimization protocol with realistic Stage-2 scoring and strict best-parameter propagation.

#### Scenario: Stage 2 uses realistic scoring path
- **WHEN** Stage 2 optimization is invoked
- **THEN** it SHALL use frozen (precomputed) signals from Stage 1
- **AND** score each parameter combination via backtest-equivalent execution metrics rather than proxy formulas

#### Scenario: Robustness uses selected Stage-2 params
- **WHEN** robustness evaluation runs after Stage 2
- **THEN** it SHALL evaluate the Stage-2 selected parameter set
- **AND** SHALL NOT fall back to hardcoded parameter defaults

#### Scenario: Final OOS uses selected Stage-2 params
- **WHEN** all parameters are frozen after Stage 1 + Stage 2
- **THEN** Simulator SHALL run exactly one final OOS evaluation with the selected Stage-2 params and report final metrics

### Requirement: Parameter scanner
Simulator SHALL sweep parameter combinations and identify robust regions in parameter space with explicit production-intent acceptance gates.

#### Scenario: Production-intent scan enforces acceptance gates
- **WHEN** scanner runs in production-intent mode
- **THEN** it SHALL apply configured gates (minimum trades, expectancy floor, OOS threshold) before marking any candidate promotable

#### Scenario: Scanner reports disqualified trial counts
- **WHEN** scanning completes
- **THEN** output SHALL include both ranked eligible trials and count of disqualified trials

#### Scenario: Research mode remains exploratory
- **WHEN** scanner runs in research mode
- **THEN** it SHALL preserve full ranked outputs while emitting explicit gate-risk warnings
