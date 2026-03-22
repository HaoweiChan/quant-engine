## 1. Parameterize ATR Mean Reversion Strategy

- [x] 1.1 Add `rsi_oversold: float = 25.0` and `rsi_overbought: float = 75.0` to `ATRMeanReversionEntryPolicy.__init__()` and replace hardcoded `25.0`/`75.0` constants in `should_enter()`
- [x] 1.2 Add `rsi_oversold` and `rsi_overbought` as kwargs to `create_atr_mean_reversion_engine()` and pass them through to `ATRMeanReversionEntryPolicy`
- [x] 1.3 Fix import violation: remove `from src.core.position_engine import PositionEngine` from `src/strategies/atr_mean_reversion.py` and use the return type annotation only, or move the factory to a permitted location per the strategies spec
- [x] 1.4 Verify the default behavior is unchanged: run the existing 1-month TX backtest and confirm identical trade log and metrics

## 2. New Result Types in src/simulator/types.py

- [x] 2.1 Add `OptimizerResult` dataclass: `trials: pl.DataFrame`, `best_params: dict[str, Any]`, `best_is_result: BacktestResult`, `best_oos_result: BacktestResult | None`, `warnings: list[str]`
- [x] 2.2 Add `WindowResult` dataclass: `window_idx: int`, `is_bars: int`, `oos_bars: int`, `best_params: dict[str, Any]`, `is_result: BacktestResult`, `oos_result: BacktestResult`, `low_trade_count: bool`
- [x] 2.3 Add `WalkForwardResult` dataclass: `windows: list[WindowResult]`, `efficiency: float`, `combined_oos_metrics: dict[str, float]`

## 3. Core StrategyOptimizer Implementation

- [x] 3.1 Create `src/simulator/strategy_optimizer.py` with `StrategyOptimizer` class skeleton: `__init__(adapter, fill_model, initial_equity, n_jobs)`
- [x] 3.2 Implement `_run_single_trial(bars, timestamps, engine_factory, params, adapter_config, fill_model, initial_equity) -> dict` as a module-level (picklable) worker function
- [x] 3.3 Implement `grid_search()`: generate all `itertools.product` combinations, dispatch trials (serial or parallel), collect results into `pl.DataFrame`, compute IS/OOS split, return `OptimizerResult`
- [x] 3.4 Implement `_validate_objective()`: check the objective name against the metrics keys from a sample trial; raise `ValueError` with valid options if not found
- [x] 3.5 Implement `_check_pickle_safety()`: detect lambda/closure factories when `n_jobs > 1` and raise `ValueError` with a descriptive message
- [x] 3.6 Implement `_low_trade_count_warnings()`: scan IS `BacktestResult` trade logs and append warnings for combinations with fewer than 30 round trips
- [x] 3.7 Implement `walk_forward()`: slice bars into rolling windows, call `grid_search` on each IS slice, run single OOS backtest with best IS params, compute `efficiency`, return `WalkForwardResult`
- [x] 3.8 Implement `random_search()`: sample `n_trials` random combinations from `param_bounds` using `numpy.random.default_rng(seed)`, delegate each to `_run_single_trial`, return `OptimizerResult`

## 4. Parallel Execution

- [x] 4.1 Add `ProcessPoolExecutor` path to `grid_search()` when `n_jobs > 1`: submit all trials, collect futures, handle exceptions per-trial without aborting the run
- [x] 4.2 Ensure `_run_single_trial` is importable from `src.simulator.strategy_optimizer` at module level (no nested definition)
- [x] 4.3 Write a smoke test: run `grid_search` with `n_jobs=2` on a tiny 3-combination grid and assert the result matches `n_jobs=1`

## 5. Integration Verification

- [x] 5.1 Run `grid_search` on TX 1-min data for 6 months (IS) + 1 month (OOS) with ATR Mean Reversion: sweep `bb_len` [15, 20, 25], `rsi_oversold` [25, 30], `atr_sl_multi` [2.0, 2.5, 3.0] — confirm output DataFrame has 18 rows with expected columns
- [x] 5.2 Call `print_backtest_report()` on `best_is_result` and `best_oos_result` and confirm readable output
- [x] 5.3 Run `walk_forward` on 1 year of TX 1-min data with `train_bars=15000` (~1 month), `test_bars=5000` (~2 weeks) — confirm window count is correct and `efficiency` is a sensible float
- [x] 5.4 Confirm `walk_forward` raises `ValueError` when `train_bars + test_bars > len(bars)`
- [x] 5.5 Confirm `grid_search` raises `ValueError` when `objective="nonexistent_metric"` is passed

## 6. Tests

- [x] 6.1 Add `tests/test_strategy_optimizer.py` with unit tests for: correct combination count, IS/OOS bar counts, walk-forward window count formula, ValueError on bad objective, ValueError on pickle-unsafe factory with n_jobs>1, low-trade-count warning trigger
- [x] 6.2 Use synthetic OHLCV bars (constant price with small noise) so tests are fast and deterministic — no DB access in unit tests
- [x] 6.3 Verify `OptimizerResult.trials` is sorted descending by the objective metric
- [x] 6.4 Verify `WalkForwardResult.efficiency` equals `mean(oos_sharpes) / mean(is_sharpes)` to 4 decimal places
