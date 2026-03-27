## ADDED Requirements

### Requirement: Single-parameter perturbation
The system SHALL perturb one strategy parameter at a time by configurable offsets and measure the impact on the Sortino ratio.

#### Scenario: Default perturbation levels
- **WHEN** parameter sensitivity is run without custom offsets
- **THEN** each numeric parameter from `PARAM_SCHEMA` SHALL be perturbed by ±5%, ±10%, and ±20% of its current value

#### Scenario: Custom perturbation offsets
- **WHEN** `offsets=[0.02, 0.05, 0.10]` is specified
- **THEN** each parameter SHALL be tested at ±2%, ±5%, and ±10%

#### Scenario: Integer parameter rounding
- **WHEN** a parameter is defined as integer type in `PARAM_SCHEMA`
- **THEN** perturbed values SHALL be rounded to the nearest integer and clamped to `[min, max]` bounds

#### Scenario: Parameter bounds enforcement
- **WHEN** a perturbation pushes a value beyond its min/max in `PARAM_SCHEMA`
- **THEN** the value SHALL be clamped to the bound

### Requirement: Sensitivity result per parameter
The system SHALL return Sortino ratio for each perturbation of each parameter.

#### Scenario: Result structure
- **WHEN** parameter sensitivity completes
- **THEN** the result SHALL be a dict mapping `param_name` to a list of `{"offset": float, "value": float, "sortino": float}` entries

#### Scenario: Baseline included
- **WHEN** perturbation results are returned
- **THEN** the result for each parameter SHALL include an entry with `offset=0.0` representing the unperturbed baseline Sortino

### Requirement: Perturbation backtests use aggregated timeframe
The system SHALL run perturbation backtests on the aggregated timeframe (e.g., 5-min bars) to reduce computation time.

#### Scenario: Timeframe passthrough
- **WHEN** the user has selected `bar_agg=5` in the sidebar
- **THEN** each perturbation backtest SHALL use 5-minute aggregated bars

#### Scenario: Computation limit
- **WHEN** a strategy has N numeric parameters and M offset levels
- **THEN** the total number of perturbation backtests SHALL be `N * 2M + 1` (±M offsets plus baseline, per parameter)
