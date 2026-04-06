## ADDED Requirements

### Requirement: Unified risk report aggregation
The system SHALL provide a `RiskReport` data structure that aggregates results from all five evaluation layers and applies pass/fail logic for strategy promotion.

```python
@dataclass
class RiskReport:
    strategy_name: str
    generated_at: datetime
    instrument: str

    # L1: Cost model
    cost_config: InstrumentCostConfig
    cost_drag_pct: float
    cost_gate_passed: bool

    # L2: Parameter sensitivity
    sensitivity_result: list[SensitivityResult]
    param_stability_passed: bool

    # L3: Regime MC
    regime_metrics: list[RegimeMetrics] | None
    regime_gate_passed: bool

    # L4: Adversarial injection
    adversarial_result: AdversarialResult | None
    adversarial_gate_passed: bool

    # L5: Walk-forward
    walk_forward_result: WalkForwardResult | None
    walk_forward_gate_passed: bool

    # Aggregate
    all_gates_passed: bool
    failure_reasons: list[str]
    recommendation: str            # "promote" | "investigate" | "reject"
```

#### Scenario: All gates pass
- **WHEN** all five layer gates pass
- **THEN** `all_gates_passed` SHALL be `true` and `recommendation` SHALL be `"promote"`

#### Scenario: Non-critical gate failure
- **WHEN** regime MC or adversarial injection gate fails but all others pass
- **THEN** `all_gates_passed` SHALL be `false` and `recommendation` SHALL be `"investigate"`

#### Scenario: Critical gate failure
- **WHEN** walk-forward validation fails (severe overfit) OR cost drag exceeds 80%
- **THEN** `recommendation` SHALL be `"reject"`

### Requirement: Gate criteria definitions
The system SHALL apply the following pass/fail criteria for each layer.

#### Scenario: Cost gate criteria
- **WHEN** evaluating the cost gate
- **THEN** it SHALL pass if the strategy's net Sharpe (after costs) remains ≥ 0.5 and `cost_drag_pct < 80%`

#### Scenario: Parameter stability gate criteria
- **WHEN** evaluating the parameter stability gate
- **THEN** it SHALL pass if no parameter has `cliff_detected: true` AND more than half of parameters have `stability_cv < 0.20`

#### Scenario: Regime gate criteria
- **WHEN** evaluating the regime gate
- **THEN** it SHALL pass if the strategy's Sharpe in the worst regime is ≥ 0.4 (sideways threshold from quality gates)

#### Scenario: Adversarial gate criteria
- **WHEN** evaluating the adversarial gate
- **THEN** it SHALL pass if `injected_metrics.max_drawdown_pct < 25%` and `worst_case_terminal_equity > 0.5 * initial_equity`

#### Scenario: Walk-forward gate criteria
- **WHEN** evaluating the walk-forward gate
- **THEN** it SHALL delegate to `WalkForwardResult.passed` (which applies all quality gate thresholds)

### Requirement: Report generation via MCP tool
The system SHALL expose a `run_risk_report` MCP tool that generates a `RiskReport` from cached or freshly-computed layer results.

#### Scenario: Generate from cached results
- **WHEN** `run_risk_report` is called and all five layers have cached results in the current session
- **THEN** the report SHALL be assembled from cached results without re-running simulations

#### Scenario: Generate with missing layers
- **WHEN** `run_risk_report` is called and some layers have not been run
- **THEN** the missing layers SHALL be reported as `None` with the corresponding gate marked as `not_evaluated`, and `all_gates_passed` SHALL be `false`

#### Scenario: Force re-evaluation
- **WHEN** `run_risk_report` is called with `force_rerun=true`
- **THEN** all five layers SHALL be re-executed before assembling the report

### Requirement: Report available via FastAPI
The system SHALL expose a FastAPI endpoint for retrieving risk reports.

#### Scenario: GET risk report
- **WHEN** a GET request is made to `/api/risk-report/{strategy_name}`
- **THEN** the system SHALL return the most recent `RiskReport` as JSON

#### Scenario: No report available
- **WHEN** a GET request is made for a strategy with no cached risk report
- **THEN** the system SHALL return HTTP 404 with a message suggesting to run the risk evaluation first
