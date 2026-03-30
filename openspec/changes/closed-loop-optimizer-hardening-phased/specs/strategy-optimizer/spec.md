## MODIFIED Requirements

### Requirement: Generic strategy optimizer
`StrategyOptimizer` SHALL accept any `engine_factory` callable whose keyword arguments correspond to the keys in `param_grid`, run real OHLCV backtests for every parameter combination, and return a ranked result with full per-trial metrics. Ranking SHALL support objective-direction semantics (`maximize` or `minimize`) and optional composite risk-first fitness policies.

```python
@dataclass
class OptimizerResult:
    trials: pl.DataFrame
    best_params: dict[str, Any]
    best_is_result: BacktestResult
    best_oos_result: BacktestResult | None
    objective_name: str
    objective_direction: Literal["maximize", "minimize"]
    disqualified_trials: int = 0
    warnings: list[str] = field(default_factory=list)
```

#### Scenario: Objective direction is respected
- **WHEN** objective is `max_drawdown_pct`
- **THEN** the optimizer SHALL treat lower values as better and rank accordingly

#### Scenario: Composite fitness objective
- **WHEN** objective policy is `calmar_profit_factor_duration_penalty`
- **THEN** each trial SHALL compute fitness from risk-adjusted return terms and configured penalties
- **AND** the optimizer SHALL rank trials by the resulting composite score

#### Scenario: OOS remains excluded from ranking
- **WHEN** `is_fraction < 1.0`
- **THEN** OOS bars SHALL NOT participate in trial ranking
- **AND** `best_oos_result` SHALL be computed once using the selected IS winner

### Requirement: Low-trade-count warning
The optimizer SHALL enforce statistical minimums for production-intent evaluation. Low trade count MUST be treated as a disqualifier by policy, not warning-only behavior.

#### Scenario: Trial disqualified on low sample size
- **WHEN** a trial's IS trade count is below configured minimum threshold
- **THEN** the trial SHALL be flagged disqualified and excluded from winner selection for production-intent mode

#### Scenario: Research mode keeps warnings
- **WHEN** optimization runs in research mode and a trial has low trade count
- **THEN** the trial MAY remain in ranked output
- **AND** the run SHALL include an explicit warning describing sample-size risk

#### Scenario: No eligible trial raises policy error
- **WHEN** all trials are disqualified by minimum sample/expectancy gates in production-intent mode
- **THEN** optimizer completion SHALL return an error indicating no promotable candidate exists
