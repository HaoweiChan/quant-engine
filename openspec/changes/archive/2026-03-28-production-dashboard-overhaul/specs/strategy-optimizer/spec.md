## ADDED Requirements

### Requirement: Unified Param Sweep frontend tab
The Strategy "Param Sweep" sub-tab SHALL combine Grid Search and Optimizer into a single interface. A method selector dropdown SHALL allow choosing: "Grid Search", "Random Search", or "Walk-Forward". The sweep SHALL use parameters from `useStrategyStore`, allowing the user to mark 1-2 parameters as sweep variables while all others remain locked at their global context values.

#### Scenario: Grid search with locked params
- **WHEN** the user selects "Grid Search" method, marks `fast_period` and `slow_period` as sweep variables, and a strategy has 5 total params
- **THEN** the request to `/api/optimizer/run` SHALL sweep `fast_period` and `slow_period` while `atr_multiplier`, `lots`, and `bar_agg` remain fixed at their `useStrategyStore.params` values

#### Scenario: Random search configuration
- **WHEN** the user selects "Random Search" method
- **THEN** the UI SHALL show `n_trials` input (default 50) and use the sweep variable ranges for random sampling

#### Scenario: Walk-forward configuration
- **WHEN** the user selects "Walk-Forward" method
- **THEN** the UI SHALL show `train_bars` and `test_bars` inputs in addition to the sweep parameters

#### Scenario: Results display as heatmap for 2 sweep variables
- **WHEN** a grid search completes with 2 sweep variables
- **THEN** the results SHALL display as a 2D heatmap with the selected metric (Sharpe, PnL, Win Rate) as the color dimension

#### Scenario: Results display as ranked table for 1 sweep variable
- **WHEN** a grid/random search completes with 1 sweep variable
- **THEN** the results SHALL display as a sorted table of trials with the sweep variable and all metrics

### Requirement: Cost model in optimizer requests
All optimizer/sweep API requests SHALL include `slippage_bps` and `commission_bps` from the global parameter context. The backend optimizer SHALL apply these costs to each trial's backtest.

#### Scenario: Costs applied to each trial
- **WHEN** a grid search runs 36 trials with `slippage_bps=5, commission_bps=2`
- **THEN** every trial's backtest SHALL apply 5 bps slippage and 2 bps commission per trade, and the resulting Sharpe/PnL metrics SHALL reflect these costs

#### Scenario: Cost model logged in param runs
- **WHEN** an optimizer run completes
- **THEN** the `param_runs` record SHALL include the cost model used: `{ slippage_bps, commission_bps }`

## MODIFIED Requirements

### Requirement: Generic strategy optimizer
`StrategyOptimizer` SHALL accept any `engine_factory` callable whose keyword arguments correspond to the keys in `param_grid`, run real OHLCV backtests for every parameter combination, and return a ranked result with full per-trial metrics. The optimizer SHALL accept optional `slippage_bps: float = 0` and `commission_bps: float = 0` parameters that are applied to every trial's backtest via the fill model.

```python
@dataclass
class OptimizerResult:
    trials: pl.DataFrame          # one row per trial, param cols + metric cols, sorted by objective
    best_params: dict[str, Any]
    best_is_result: BacktestResult
    best_oos_result: BacktestResult | None  # None if is_fraction == 1.0
    cost_model: dict[str, float]  # { "slippage_bps": ..., "commission_bps": ... }

@dataclass
class WindowResult:
    window_idx: int
    is_bars: int
    oos_bars: int
    best_params: dict[str, Any]
    is_result: BacktestResult
    oos_result: BacktestResult

@dataclass
class WalkForwardResult:
    windows: list[WindowResult]
    efficiency: float              # mean OOS Sharpe / mean IS Sharpe
    combined_oos_metrics: dict[str, float]

class StrategyOptimizer:
    def __init__(
        self,
        adapter: BaseAdapter,
        fill_model: FillModel | None = None,
        initial_equity: float = 2_000_000.0,
        n_jobs: int = 1,
        slippage_bps: float = 0,
        commission_bps: float = 0,
    ) -> None: ...

    def grid_search(
        self,
        engine_factory: Callable[..., PositionEngine],
        param_grid: dict[str, list[Any]],
        bars: list[dict[str, Any]],
        timestamps: list[datetime],
        objective: str = "sharpe",
        is_fraction: float = 0.8,
    ) -> OptimizerResult: ...

    def walk_forward(
        self,
        engine_factory: Callable[..., PositionEngine],
        param_grid: dict[str, list[Any]],
        bars: list[dict[str, Any]],
        timestamps: list[datetime],
        train_bars: int,
        test_bars: int,
        objective: str = "sharpe",
    ) -> WalkForwardResult: ...

    def random_search(
        self,
        engine_factory: Callable[..., PositionEngine],
        param_bounds: dict[str, tuple[float, float]],
        bars: list[dict[str, Any]],
        timestamps: list[datetime],
        n_trials: int = 50,
        objective: str = "sharpe",
        is_fraction: float = 0.8,
        seed: int | None = None,
    ) -> OptimizerResult: ...
```

#### Scenario: Grid search returns one row per combination
- **WHEN** `grid_search()` is called with a param grid containing N total combinations
- **THEN** `OptimizerResult.trials` SHALL contain exactly N rows, sorted by the objective metric descending

#### Scenario: Best params are the IS winner
- **WHEN** `grid_search()` completes
- **THEN** `best_params` SHALL match the parameter values of the row with the highest objective metric in the IS period

#### Scenario: OOS is held out from all optimization decisions
- **WHEN** `is_fraction < 1.0`
- **THEN** the OOS bars SHALL NOT be seen by any backtest during the parameter search — only the IS slice is used for ranking

#### Scenario: OOS result uses best IS params
- **WHEN** `is_fraction < 1.0` and `grid_search()` completes
- **THEN** `best_oos_result` SHALL be a single backtest run on the OOS bars using `best_params`

#### Scenario: No OOS result when is_fraction is 1.0
- **WHEN** `is_fraction == 1.0`
- **THEN** `best_oos_result` SHALL be `None`

#### Scenario: Unsupported objective metric raises ValueError
- **WHEN** `objective` is not a key present in the metrics dict returned by `BacktestRunner`
- **THEN** `grid_search()` SHALL raise `ValueError` with a descriptive message listing valid objective names

#### Scenario: Cost model stored in result
- **WHEN** `grid_search()` completes
- **THEN** `OptimizerResult.cost_model` SHALL contain `{ "slippage_bps": <value>, "commission_bps": <value> }` reflecting the costs applied during optimization
