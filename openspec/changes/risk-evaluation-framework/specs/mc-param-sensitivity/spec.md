## ADDED Requirements

### Requirement: Cliff-edge detection in perturbation analysis
The parameter sensitivity module SHALL detect cliff-edge behavior where Sharpe drops disproportionately between adjacent perturbation levels.

#### Scenario: Cliff detected
- **WHEN** Sharpe drops by more than 30% between two adjacent perturbation levels for a parameter
- **THEN** the result for that parameter SHALL include `cliff_detected: true` and identify the cliff edge values

#### Scenario: No cliff
- **WHEN** Sharpe changes smoothly across all perturbation levels
- **THEN** `cliff_detected` SHALL be `false`

### Requirement: Stability CV metric
The system SHALL compute the coefficient of variation of Sharpe (or Sortino) across all perturbation levels for each parameter.

#### Scenario: CV computation
- **WHEN** perturbation results are returned
- **THEN** each parameter's result SHALL include `stability_cv = std(metric_values) / mean(metric_values)` across all perturbation levels

#### Scenario: Zero or negative mean handling
- **WHEN** the mean metric value across perturbation levels is ≤ 0
- **THEN** `stability_cv` SHALL be set to `float('inf')` and the parameter SHALL be flagged as `unstable: true`

## MODIFIED Requirements

### Requirement: Single-parameter perturbation
The system SHALL perturb one strategy parameter at a time by configurable offsets and measure the impact on the Sortino ratio. The perturbation backtests SHALL apply the default instrument cost model.

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

#### Scenario: Costs applied to perturbation backtests
- **WHEN** perturbation backtests are run
- **THEN** each backtest SHALL use the instrument's default cost model from `InstrumentCostConfig`, not zero costs

### Requirement: Sensitivity result per parameter
The system SHALL return Sortino ratio for each perturbation of each parameter, along with cliff detection and stability metrics.

#### Scenario: Result structure
- **WHEN** parameter sensitivity completes
- **THEN** the result SHALL be a dict mapping `param_name` to a list of `{"offset": float, "value": float, "sortino": float}` entries, plus `cliff_detected: bool` and `stability_cv: float`

#### Scenario: Baseline included
- **WHEN** perturbation results are returned
- **THEN** the result for each parameter SHALL include an entry with `offset=0.0` representing the unperturbed baseline Sortino
