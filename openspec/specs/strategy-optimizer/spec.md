## Purpose

Programmatic optimization of strategy parameters via `StrategyOptimizer`: grid search, walk-forward validation, random search, parallel trials, and warnings for unreliable sample sizes.

## Requirements

### Requirement: Generic strategy optimizer
`StrategyOptimizer` SHALL accept any `engine_factory` callable whose keyword arguments correspond to the keys in `param_grid`, run real OHLCV backtests for every parameter combination, and return a ranked result with full per-trial metrics.

```python
@dataclass
class OptimizerResult:
    trials: pl.DataFrame          # one row per trial, param cols + metric cols, sorted by objective
    best_params: dict[str, Any]
    best_is_result: BacktestResult
    best_oos_result: BacktestResult | None  # None if is_fraction == 1.0

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
