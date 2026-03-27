## ADDED Requirements

### Requirement: Monte Carlo mode dispatcher
The simulator SHALL expose a single entry point that dispatches to the appropriate MC simulation mode based on a `mode` parameter.

```python
def run_monte_carlo_enhanced(
    strategy: str,
    symbol: str,
    start: str,
    end: str,
    params: dict | None = None,
    initial_capital: float = 2_000_000.0,
    bar_agg: int = 1,
    mode: str = "bootstrap",
    n_paths: int = 500,
    sim_days: int = 252,
    ruin_thresholds: list[float] | None = None,
    fat_tails: bool = False,
    df: int = 5,
    perturbation_offsets: list[float] | None = None,
    block_size: int = 1,
) -> MonteCarloReport: ...
```

#### Scenario: Mode routing
- **WHEN** `run_monte_carlo_enhanced` is called with `mode="bootstrap"`, `"trade_resampling"`, `"gbm"`, or `"sensitivity"`
- **THEN** the function SHALL delegate to the corresponding engine and return a unified `MonteCarloReport`

#### Scenario: Invalid mode
- **WHEN** an unsupported `mode` value is provided
- **THEN** the function SHALL raise `ValueError` listing valid modes

### Requirement: MonteCarloReport result dataclass
The simulator SHALL return a structured `MonteCarloReport` from all enhanced MC runs.

```python
@dataclass
class MonteCarloReport:
    mode: str
    initial_capital: float
    sim_days: int
    n_paths: int
    paths: list[list[float]]
    final_pnls: list[float]
    percentiles: dict[str, float]
    mdd_values: list[float]
    mdd_p95: float
    mdd_median: float
    ruin_thresholds: dict[str, float]
    param_sensitivity: dict[str, list[dict]] | None = None
    sharpe_values: list[float] | None = None
    sortino_values: list[float] | None = None
```

#### Scenario: All modes populate core fields
- **WHEN** any MC mode completes
- **THEN** `paths`, `final_pnls`, `percentiles`, `mdd_values`, `mdd_p95`, `mdd_median`, and `ruin_thresholds` SHALL be populated

#### Scenario: Sensitivity mode populates param_sensitivity
- **WHEN** `mode="sensitivity"` completes
- **THEN** `param_sensitivity` SHALL be populated with per-parameter perturbation results

#### Scenario: Path downsampling
- **WHEN** `n_paths > 200`
- **THEN** `paths` SHALL contain at most 200 equity curves (evenly sampled) for frontend rendering; full statistics SHALL use all paths

### Requirement: MCP facade for enhanced MC
The simulator SHALL expose a facade function for the MCP tool layer and the REST API.

```python
def run_monte_carlo_enhanced_for_mcp(
    strategy: str,
    symbol: str,
    start: str,
    end: str,
    params: dict | None = None,
    initial_capital: float = 2_000_000.0,
    bar_agg: int = 1,
    mode: str = "bootstrap",
    n_paths: int = 500,
    sim_days: int = 252,
    **kwargs,
) -> dict: ...
```

#### Scenario: Dict-in dict-out
- **WHEN** the facade function is called
- **THEN** it SHALL delegate to `run_monte_carlo_enhanced`, serialize the `MonteCarloReport` to a plain dict, and return it

#### Scenario: API endpoint wiring
- **WHEN** `POST /api/mc/run` is called with a JSON body containing `mode` and strategy parameters
- **THEN** the API SHALL call the facade function and return the serialized `MonteCarloReport`

## MODIFIED Requirements

### Requirement: Monte Carlo runner
Simulator SHALL run N price paths through PositionEngine and collect PnL distribution statistics. Accepts engine factory. The runner SHALL also compute MDD distribution and ruin probability for every MC mode.

#### Scenario: PnL distribution
- **WHEN** a Monte Carlo run completes with N paths
- **THEN** the result SHALL include P5, P25, P50, P75, P95 of terminal PnL across all paths

#### Scenario: Risk metrics
- **WHEN** a Monte Carlo run completes
- **THEN** the result SHALL include win rate, max drawdown distribution, Sharpe distribution, Calmar ratio, ruin probability (% of paths hitting max_loss), **MDD at 95th percentile**, **MDD median**, and **ruin probability at configurable drawdown thresholds**

#### Scenario: Engine factory per path
- **WHEN** a Monte Carlo run starts
- **THEN** `BacktestRunner` SHALL use the engine factory to create a fresh engine, ensuring each path starts from a clean state

#### Scenario: Parallelization
- **WHEN** N > 1000
- **THEN** the runner SHALL support Ray-based parallelization for performance

### Requirement: MonteCarloResult fields
- **WHEN** a Monte Carlo run completes
- **THEN** `MonteCarloResult` SHALL contain: terminal_pnl_distribution, percentiles (P5/P25/P50/P75/P95), win_rate, max_drawdown_distribution, sharpe_distribution, ruin_probability, per-path equity curves, **mdd_values (list)**, **mdd_p95**, **mdd_median**, **ruin_thresholds (dict)**, **sortino_values (list, optional)**, and **param_sensitivity (dict, optional)**

#### Scenario: Backward compatible
- **WHEN** existing code accesses `MonteCarloResult` fields
- **THEN** all previously existing fields SHALL remain available with the same types
