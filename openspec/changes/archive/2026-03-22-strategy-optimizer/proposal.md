## Why

The existing `scanner.py` grid search is hardwired to `PyramidConfig` parameters (`stop_atr_mult`, `trail_atr_mult`, `kelly_fraction`) and cannot be used to optimize rule-based strategies like the new ATR Mean Reversion strategy. There is also no walk-forward validation or IS/OOS split, making it impossible to distinguish genuine robustness from in-sample overfitting.

## What Changes

- **New**: `src/simulator/strategy_optimizer.py` — a generic `StrategyOptimizer` that accepts any `engine_factory(**params)` callable and a `param_grid` dict, runs real OHLCV backtests over all combinations, reports full metrics, and supports IS/OOS splitting and walk-forward validation.
- **New**: `OptimizerResult` and `WalkForwardResult` dataclasses in `src/simulator/types.py`.
- **Modify**: `src/strategies/atr_mean_reversion.py` — add `rsi_oversold` and `rsi_overbought` as explicit factory parameters (currently hardcoded at 25/75), making them optimizable.
- **Deferred (Phase 2)**: Dashboard integration — wiring the Optimization tab to the new optimizer with real data.

## Capabilities

### New Capabilities
- `strategy-optimizer`: Generic strategy parameter optimizer — grid search, random search, IS/OOS split, and walk-forward validation against real OHLCV data. Produces ranked results DataFrame, best-params backtest, and WF efficiency metric. CLI-only in Phase 1.

### Modified Capabilities
- `simulator`: `scan_parameters` requirement extended to support arbitrary engine factories (not just `PyramidConfig`), IS/OOS splitting, and walk-forward evaluation with efficiency scoring.
- `strategies`: `ATRMeanReversionEntryPolicy` gains `rsi_oversold` and `rsi_overbought` constructor parameters; `create_atr_mean_reversion_engine()` exposes them as keyword arguments.

## Impact

- **New file**: `src/simulator/strategy_optimizer.py`
- **Modified files**: `src/simulator/types.py` (new result types), `src/strategies/atr_mean_reversion.py` (new params)
- **No dashboard changes in Phase 1** — optimizer is invoked programmatically or via a script
- **No new dependencies** — uses existing `polars`, `itertools`, `concurrent.futures`, `BacktestRunner`, and `TaifexAdapter`
