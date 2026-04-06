## ADDED Requirements

### Requirement: Per-instrument cost configuration
The system SHALL provide an `InstrumentCostConfig` dataclass and a registry mapping instrument symbols to their default transaction costs.

```python
@dataclass(frozen=True)
class InstrumentCostConfig:
    slippage_pct: float       # percentage slippage per side (e.g., 0.1 = 0.1%)
    commission_per_contract: float  # NT$ round-trip commission
    symbol: str

INSTRUMENT_COSTS: dict[str, InstrumentCostConfig]
```

#### Scenario: TX default costs
- **WHEN** a backtest is run for symbol "TX" without explicit cost parameters
- **THEN** the system SHALL apply slippage of 0.1% per side and commission of NT$100 round-trip per contract

#### Scenario: MTX default costs
- **WHEN** a backtest is run for symbol "MTX" without explicit cost parameters
- **THEN** the system SHALL apply slippage of 0.1% per side and commission of NT$40 round-trip per contract

#### Scenario: Unknown instrument fallback
- **WHEN** a backtest is run for an unregistered symbol without explicit cost parameters
- **THEN** the system SHALL apply slippage of 0.1% per side and commission of NT$100 round-trip (TX defaults) and log a warning

### Requirement: Cost defaults injected in MCP facade
The MCP facade SHALL inject default costs from `InstrumentCostConfig` when the caller does not provide explicit `slippage_bps`, `commission_bps`, or `commission_fixed_per_contract` parameters. Explicit values SHALL override defaults.

#### Scenario: No cost params provided
- **WHEN** `run_backtest` is called with `strategy_params` that contain no cost keys
- **THEN** the facade SHALL inject `slippage_bps`, `commission_bps`, and `commission_fixed_per_contract` from the instrument's `InstrumentCostConfig`

#### Scenario: Explicit cost params override defaults
- **WHEN** `run_backtest` is called with `strategy_params={"slippage_bps": 5.0}`
- **THEN** the facade SHALL use `slippage_bps=5.0` and fill remaining cost params from defaults

#### Scenario: Explicit zero cost requires opt-in
- **WHEN** a caller wants zero transaction costs
- **THEN** they MUST explicitly pass `slippage_bps=0.0` and `commission_fixed_per_contract=0.0`; omitting these keys SHALL result in non-zero defaults being applied

### Requirement: Cost model applied to all simulation paths
The system SHALL apply the cost model consistently across all simulation types: single backtest, Monte Carlo, parameter sweep, and stress test.

#### Scenario: Monte Carlo with costs
- **WHEN** `run_monte_carlo` is called without explicit cost params
- **THEN** every simulated path SHALL apply the instrument's default slippage and commission

#### Scenario: Parameter sweep with costs
- **WHEN** `run_parameter_sweep` is called without explicit cost params
- **THEN** every parameter combination SHALL be backtested with the instrument's default costs

#### Scenario: Stress test with costs
- **WHEN** `run_stress_test` is called without explicit cost params
- **THEN** the stress scenario SHALL be run with the instrument's default costs applied to the fill model

### Requirement: Cost impact reporting
The system SHALL report transaction cost impact in backtest results, showing gross PnL (before costs), net PnL (after costs), total slippage cost, and total commission cost.

#### Scenario: Cost breakdown in metrics
- **WHEN** a backtest completes with non-zero costs
- **THEN** the result metrics SHALL include `gross_pnl`, `net_pnl`, `total_slippage_cost`, `total_commission_cost`, and `cost_drag_pct` (total costs as percentage of gross PnL)

#### Scenario: Cost drag warning
- **WHEN** `cost_drag_pct` exceeds 50% (costs consume more than half of gross profits)
- **THEN** the system SHALL include a warning flag `high_cost_drag: true` in the result
