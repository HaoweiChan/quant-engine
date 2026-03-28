## Purpose

Programmatic optimization of strategy parameters via `StrategyOptimizer`: grid search, walk-forward validation, random search, parallel trials, and warnings for unreliable sample sizes.

## Requirements

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

### Requirement: Walk-forward rolling windows
`walk_forward()` SHALL divide bars into sequential IS+OOS window pairs, run `grid_search` on each IS window to find optimal params, evaluate those params on the OOS window, and report per-window results and an overall efficiency score.

#### Scenario: Window count is correct
- **WHEN** `walk_forward()` is called with `len(bars)` total bars, `train_bars` IS length, and `test_bars` OOS length
- **THEN** the number of windows SHALL be `floor((len(bars) - train_bars) / test_bars)`

#### Scenario: No bar overlap between IS and OOS within a window
- **WHEN** a window is created
- **THEN** the IS slice SHALL end immediately before the OOS slice begins — no bar appears in both

#### Scenario: Each window selects best params independently
- **WHEN** walk-forward runs with N windows
- **THEN** each window SHALL independently optimize on its IS bars — params from window k have no effect on window k+1

#### Scenario: Efficiency is flagged when below threshold
- **WHEN** `walk_forward()` completes and `efficiency < 0.3`
- **THEN** `WalkForwardResult` SHALL include a warning flag or the efficiency value itself, allowing the caller to detect likely overfitting

#### Scenario: Insufficient bars raises ValueError
- **WHEN** `walk_forward()` is called and `train_bars + test_bars > len(bars)`
- **THEN** it SHALL raise `ValueError`

### Requirement: Parallel execution
`StrategyOptimizer` SHALL support parallel trial execution when `n_jobs > 1`.

#### Scenario: n_jobs=1 runs serially
- **WHEN** `n_jobs == 1`
- **THEN** all trials SHALL execute in the calling process with no subprocess overhead

#### Scenario: n_jobs > 1 uses ProcessPoolExecutor
- **WHEN** `n_jobs > 1`
- **THEN** trials SHALL be distributed across worker processes using `concurrent.futures.ProcessPoolExecutor`

#### Scenario: Factory must be a module-level callable for parallelism
- **WHEN** `n_jobs > 1` and the `engine_factory` is a lambda or closure
- **THEN** `StrategyOptimizer` SHALL raise `ValueError` explaining the pickling constraint and instructing the caller to use a module-level function

#### Scenario: Serial and parallel results are identical
- **WHEN** the same grid search is run with `n_jobs=1` and `n_jobs=4`
- **THEN** `OptimizerResult.trials` SHALL contain identical rows (order may differ)

### Requirement: Low-trade-count warning
The optimizer SHALL warn when the IS window produces too few trades for statistically reliable optimization.

#### Scenario: Warning when IS trades below threshold
- **WHEN** the IS backtest for any trial produces fewer than 30 round-trip trades
- **THEN** `OptimizerResult` SHALL include a `warnings: list[str]` field with an entry noting the low trade count and the affected param combination

#### Scenario: Walk-forward window warns independently
- **WHEN** a walk-forward IS window produces fewer than 30 round-trip trades for the best-params run
- **THEN** `WindowResult` SHALL include a `low_trade_count: bool` flag set to `True`

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
