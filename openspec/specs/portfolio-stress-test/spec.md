# portfolio-stress-test

## Purpose
TBD — synced from change `multi-strategy-portfolio`.

## Requirements

### Requirement: Portfolio stress test endpoint
The system SHALL expose `POST /api/portfolio/stress-test` that runs Monte Carlo simulation on merged portfolio daily returns.

```python
class PortfolioStressRequest(BaseModel):
    strategies: list[StrategyEntry]  # 2-3 items, same as backtest
    symbol: str = "TX"
    start: str = "2025-08-01"
    end: str = "2026-03-14"
    initial_capital: float = 2_000_000.0
    slippage_bps: float = 0.0
    commission_bps: float = 0.0
    n_paths: int = Field(500, ge=10, le=5000)
    n_days: int = Field(252, ge=20, le=1000)
    method: Literal["stationary", "circular", "garch"] = "stationary"
    ruin_threshold: float = Field(0.5, ge=0.01, le=0.99)
    seed: int | None = None
```

#### Scenario: Valid portfolio stress test
- **WHEN** request contains 2-3 valid strategies
- **THEN** endpoint SHALL run individual backtests, merge daily returns, feed merged returns into `BlockBootstrapMC`, and return Monte Carlo results

#### Scenario: Response format matches single-strategy MC
- **WHEN** the stress test completes
- **THEN** response SHALL contain `var_95`, `var_99`, `cvar_95`, `cvar_99`, `median_final`, `prob_ruin`, `method`, `n_paths`, `n_days`, and `bands` (percentile fan chart data) — identical shape to the existing `/api/monte-carlo` response

#### Scenario: Merged returns used for simulation
- **WHEN** the stress test runs
- **THEN** the Monte Carlo simulation SHALL use the weighted merged daily returns, NOT individual strategy returns independently

#### Scenario: Insufficient merged data for GARCH
- **WHEN** `method="garch"` and merged returns have fewer than 50 data points
- **THEN** endpoint SHALL return HTTP 422 with appropriate message

#### Scenario: Zero-variance merged returns
- **WHEN** all merged daily returns are 0.0
- **THEN** endpoint SHALL return HTTP 422 with "merged returns are all zero"

#### Scenario: Strategy count validation
- **WHEN** fewer than 2 or more than 3 strategies are provided
- **THEN** endpoint SHALL return HTTP 400 with count validation message

### Requirement: Reuse existing BlockBootstrapMC
The portfolio stress test SHALL reuse the existing `BlockBootstrapMC` class without modification. The merged daily returns array SHALL be passed as the `returns` parameter.

#### Scenario: MC engine receives merged returns
- **WHEN** `BlockBootstrapMC` is instantiated for portfolio stress
- **THEN** its `returns` parameter SHALL be the output of `PortfolioMerger.merge().merged_daily_returns`

#### Scenario: All MC methods supported
- **WHEN** `method` is "stationary", "circular", or "garch"
- **THEN** the portfolio stress test SHALL support all three methods identically to single-strategy MC
