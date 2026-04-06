## ADDED Requirements

### Requirement: run_walk_forward MCP tool
The server SHALL expose a `run_walk_forward` tool that runs expanding-window walk-forward validation on historical or synthetic data.

```python
# Input schema
{
    "strategy": str,              # strategy factory identifier
    "n_folds": int,               # default 3
    "oos_fraction": float,        # default 0.2
    "session": str,               # "all" | "day" | "night", default "all"
    "max_sweep_combinations": int, # default 50
    "strategy_params": dict,      # optional base params
}
```

#### Scenario: Walk-forward tool call
- **WHEN** `run_walk_forward` is called with a strategy identifier
- **THEN** it SHALL run the walk-forward validation engine and return per-fold IS/OOS metrics, aggregate OOS Sharpe, overfit flag, and pass/fail status

#### Scenario: Walk-forward result persisted
- **WHEN** walk-forward completes successfully
- **THEN** the result SHALL be cached in the session history for use by `run_risk_report`

#### Scenario: Walk-forward with session filter
- **WHEN** `run_walk_forward` is called with `session="day"`
- **THEN** the engine SHALL filter bars to only include TAIFEX day session (08:45–13:45) before splitting into folds

### Requirement: run_risk_report MCP tool
The server SHALL expose a `run_risk_report` tool that generates a unified risk sign-off report.

```python
# Input schema
{
    "strategy": str,              # strategy factory identifier
    "force_rerun": bool,          # default false — if true, re-run all layers
    "instrument": str,            # default "TX"
}
```

#### Scenario: Risk report from cached results
- **WHEN** `run_risk_report` is called and all layers have cached results
- **THEN** it SHALL assemble and return a `RiskReport` without re-running simulations

#### Scenario: Risk report with missing layers
- **WHEN** `run_risk_report` is called with some layers not yet run
- **THEN** missing layers SHALL be reported as `not_evaluated` and `all_gates_passed` SHALL be `false`

#### Scenario: Risk report with force rerun
- **WHEN** `run_risk_report` is called with `force_rerun=true`
- **THEN** it SHALL execute all five evaluation layers before assembling the report

### Requirement: Default cost injection in existing tools
All existing MCP tools (`run_backtest`, `run_monte_carlo`, `run_parameter_sweep`, `run_stress_test`) SHALL inject default instrument costs when no explicit cost parameters are provided.

#### Scenario: run_backtest default costs
- **WHEN** `run_backtest` is called without `slippage_bps`, `commission_bps`, or `commission_fixed_per_contract` in `strategy_params`
- **THEN** the facade SHALL inject defaults from `InstrumentCostConfig` for the target instrument

#### Scenario: run_monte_carlo default costs
- **WHEN** `run_monte_carlo` is called without explicit cost params
- **THEN** the facade SHALL inject default costs and pass them to the backtest runner underlying the MC simulation

#### Scenario: run_parameter_sweep default costs
- **WHEN** `run_parameter_sweep` is called without explicit cost params
- **THEN** every parameter combination SHALL be evaluated with default instrument costs

#### Scenario: run_stress_test default costs
- **WHEN** `run_stress_test` is called without explicit cost params
- **THEN** the stress scenario SHALL use a fill model configured with default instrument costs

#### Scenario: Explicit zero overrides defaults
- **WHEN** any tool is called with `slippage_bps=0.0` explicitly in `strategy_params`
- **THEN** the facade SHALL respect the explicit zero and NOT inject defaults for that parameter
