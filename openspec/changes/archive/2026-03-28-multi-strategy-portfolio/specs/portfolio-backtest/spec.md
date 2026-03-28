## ADDED Requirements

### Requirement: Portfolio backtest merger
The system SHALL provide a `PortfolioMerger` class in `src/core/portfolio_merger.py` that combines daily returns from up to 3 individual backtest results into a single portfolio equity curve.

```python
@dataclass
class PortfolioMergerInput:
    daily_returns: list[float]
    strategy_slug: str
    weight: float  # 0.0-1.0, all weights must sum to 1.0

@dataclass
class PortfolioMergeResult:
    merged_daily_returns: list[float]
    merged_equity_curve: list[float]
    individual_equity_curves: dict[str, list[float]]
    correlation_matrix: list[list[float]]
    metrics: dict[str, float]  # sharpe, sortino, max_dd, calmar, total_return

class PortfolioMerger:
    def __init__(self, initial_capital: float = 2_000_000.0) -> None: ...
    def merge(self, inputs: list[PortfolioMergerInput]) -> PortfolioMergeResult: ...
```

#### Scenario: Two strategies with equal weights
- **WHEN** `merge()` is called with two inputs, each having `weight=0.5`
- **THEN** `merged_daily_returns[t]` SHALL equal `0.5 * r_a[t] + 0.5 * r_b[t]` for all `t`
- **AND** `merged_equity_curve` SHALL compound from `initial_capital` using merged returns

#### Scenario: Three strategies with custom weights
- **WHEN** `merge()` is called with three inputs with weights `[0.5, 0.3, 0.2]`
- **THEN** merged return at each day SHALL be the weighted sum of individual daily returns

#### Scenario: Weights auto-normalized
- **WHEN** weights do not sum to 1.0
- **THEN** the merger SHALL normalize them to sum to 1.0 before computing

#### Scenario: Unequal return series lengths
- **WHEN** strategies have different numbers of daily returns (e.g., one traded fewer days)
- **THEN** the merger SHALL align by date index, using 0.0 return for days a strategy has no data

#### Scenario: Single strategy input
- **WHEN** only one strategy is provided
- **THEN** the result SHALL be identical to that strategy's individual backtest

#### Scenario: Empty returns rejected
- **WHEN** any input has an empty `daily_returns` list
- **THEN** `merge()` SHALL raise `ValueError`

### Requirement: Correlation matrix computation
The merger SHALL compute the Pearson correlation matrix between all strategy daily return series.

#### Scenario: Two-strategy correlation
- **WHEN** two strategies are provided
- **THEN** `correlation_matrix` SHALL be a 2×2 matrix with 1.0 on the diagonal

#### Scenario: Uncorrelated strategies
- **WHEN** two strategies have uncorrelated returns
- **THEN** off-diagonal correlation values SHALL be near 0.0

#### Scenario: Perfectly correlated strategies
- **WHEN** two strategies have identical daily returns
- **THEN** off-diagonal correlation values SHALL be 1.0

### Requirement: Portfolio metrics computation
The merger SHALL compute standard portfolio-level performance metrics on the merged equity curve.

```python
metrics = {
    "total_return": float,     # (final - initial) / initial
    "sharpe": float,           # annualized, risk-free=0
    "sortino": float,          # annualized, downside deviation
    "max_drawdown_pct": float, # worst peak-to-trough
    "calmar": float,           # annual return / max drawdown
    "annual_return": float,    # CAGR
    "annual_vol": float,       # annualized volatility
    "n_days": int,             # number of trading days
}
```

#### Scenario: Metrics computed on merged curve
- **WHEN** `merge()` completes
- **THEN** `result.metrics` SHALL contain all keys listed above with correct values

#### Scenario: Zero-variance merged returns
- **WHEN** all merged daily returns are 0.0
- **THEN** Sharpe and Sortino SHALL be 0.0, not NaN or Inf

### Requirement: Portfolio backtest API endpoint
The system SHALL expose `POST /api/portfolio/backtest` that runs individual backtests and merges results.

```python
class StrategyEntry(BaseModel):
    slug: str
    params: dict | None = None
    weight: float = 1.0

class PortfolioBacktestRequest(BaseModel):
    strategies: list[StrategyEntry]  # 2-3 items
    symbol: str = "TX"
    start: str = "2025-08-01"
    end: str = "2026-03-14"
    initial_capital: float = 2_000_000.0
    slippage_bps: float = 0.0
    commission_bps: float = 0.0
```

#### Scenario: Valid 2-strategy request
- **WHEN** request contains 2 valid strategy entries
- **THEN** endpoint SHALL run both backtests, merge results, and return combined metrics + individual summaries + correlation matrix

#### Scenario: Valid 3-strategy request
- **WHEN** request contains 3 valid strategy entries
- **THEN** endpoint SHALL run all 3, merge, and return combined results

#### Scenario: Single strategy rejected
- **WHEN** request contains only 1 strategy entry
- **THEN** endpoint SHALL return HTTP 400 with "Portfolio requires at least 2 strategies"

#### Scenario: More than 3 strategies rejected
- **WHEN** request contains more than 3 strategy entries
- **THEN** endpoint SHALL return HTTP 400 with "Maximum 3 strategies allowed"

#### Scenario: Invalid strategy slug
- **WHEN** a strategy slug does not exist in the registry
- **THEN** endpoint SHALL return HTTP 404 with the invalid slug identified

#### Scenario: Backtest failure for one strategy
- **WHEN** one strategy's backtest raises an error
- **THEN** endpoint SHALL return HTTP 500 with the failing strategy identified
