## ADDED Requirements

### Requirement: Grid sweep with cliff-edge detection
The system SHALL provide a parameter sensitivity analysis that runs a ±20% grid sweep around active strategy parameters and detects performance cliffs — regions where a small parameter change causes a disproportionate Sharpe degradation.

```python
@dataclass
class SensitivityResult:
    param_name: str
    grid_values: list[float]
    sharpe_values: list[float]
    baseline_sharpe: float
    max_sharpe_drop_pct: float    # worst degradation within the grid
    cliff_detected: bool          # True if any adjacent step drops Sharpe > 30%
    stability_cv: float           # CV of Sharpe across grid points
```

#### Scenario: Default grid sweep range
- **WHEN** parameter sensitivity is run without custom range
- **THEN** each numeric parameter SHALL be swept ±20% from its current value in 5 steps per side (11 total grid points including baseline)

#### Scenario: Cliff-edge detection
- **WHEN** the Sharpe ratio drops by more than 30% between any two adjacent grid points
- **THEN** `cliff_detected` SHALL be set to `true` for that parameter

#### Scenario: Integer parameter handling
- **WHEN** a parameter is integer-typed in `PARAM_SCHEMA`
- **THEN** grid values SHALL be rounded to nearest integer, deduplicated, and clamped to `[min, max]` bounds

#### Scenario: Boundary parameter warning
- **WHEN** the highest Sharpe in the grid occurs at the boundary of the sweep range (first or last grid point)
- **THEN** the result SHALL include a warning flag `optimal_at_boundary: true`, indicating the true optimum may lie outside the tested range

### Requirement: Stability scoring
The system SHALL compute a stability score for each parameter based on the coefficient of variation (CV) of Sharpe ratios across the grid.

#### Scenario: Low stability parameter
- **WHEN** a parameter's Sharpe CV across the grid exceeds 0.30 (30%)
- **THEN** the parameter SHALL be flagged as `unstable: true`

#### Scenario: High stability parameter
- **WHEN** a parameter's Sharpe CV across the grid is below 0.15 (15%)
- **THEN** the parameter SHALL be marked as `stable: true`

### Requirement: Aggregate overfitting assessment
The system SHALL provide an aggregate overfitting assessment across all parameters.

#### Scenario: Overfitting flag
- **WHEN** more than half of the swept parameters have `cliff_detected: true` or `unstable: true`
- **THEN** the aggregate result SHALL set `likely_overfit: true`

#### Scenario: Robust parameter set
- **WHEN** no parameters have `cliff_detected` and all have `stability_cv < 0.20`
- **THEN** the aggregate result SHALL set `likely_overfit: false` and `robust: true`

### Requirement: Costs applied to sensitivity sweep
The parameter sensitivity sweep SHALL apply the default instrument cost model to every grid point backtest, consistent with the `transaction-cost-model` capability.

#### Scenario: Sensitivity with costs
- **WHEN** a parameter sensitivity sweep is run
- **THEN** every backtest in the grid SHALL use the instrument's default slippage and commission, not zero costs
