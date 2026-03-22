## Context

The simulator already has `BacktestRunner` (feeds real OHLCV bars through the production `PositionEngine`) and `scanner.py` (grid search hardwired to `PyramidConfig`). The `ATRMeanReversionEntryPolicy` has RSI thresholds hardcoded as constants. The dashboard Optimization tab renders a Grid Search heatmap backed by Monte Carlo synthetic data — not real backtests.

Phase 1 of this change focuses entirely on the CLI-accessible optimizer. Dashboard wiring is deferred to Phase 2.

## Goals / Non-Goals

**Goals:**
- Generic `StrategyOptimizer` callable with any `engine_factory(**kwargs) -> PositionEngine` and any `param_grid: dict[str, list]`
- Grid search mode: exhaustive combination sweep with configurable objective metric
- IS/OOS split: hold back a trailing fraction of bars (default 20%) for out-of-sample verification of the best IS parameters
- Walk-forward mode: rolling IS+OOS windows to measure WF efficiency (OOS Sharpe / IS Sharpe)
- Parallel execution via `ProcessPoolExecutor` using a top-level picklable worker function
- `OptimizerResult` and `WalkForwardResult` typed result dataclasses surfacing all metrics per trial
- ATR Mean Reversion `rsi_oversold` / `rsi_overbought` exposed as factory kwargs
- Full integration with `print_backtest_report()` for readable CLI output

**Non-Goals (Phase 1):**
- Dashboard UI changes
- Bayesian / Optuna-based search
- Multi-objective Pareto optimization
- Saving/loading optimizer results to disk automatically

## Decisions

### Decision 1 — Generic factory protocol, not a base class

**Chosen:** The optimizer accepts `engine_factory: Callable[..., PositionEngine]` — a plain callable with keyword arguments matching the param grid keys.

**Alternative:** Require strategies to subclass an `OptimizableStrategy` ABC with a `param_schema` property.

**Rationale:** The factory protocol is zero-overhead — `create_atr_mean_reversion_engine` already has keyword parameters. No inheritance ceremony needed. The optimizer just calls `engine_factory(**combo)` for each parameter combination.

```
param_grid = {
    "bb_len":        [15, 20, 25],
    "rsi_oversold":  [25, 30],
    "atr_sl_multi":  [2.0, 2.5, 3.0],
    "atr_tp_multi":  [1.5, 2.0, 2.5],
}

# Optimizer does:
for combo in itertools.product(*param_grid.values()):
    params = dict(zip(param_grid.keys(), combo))
    engine = engine_factory(**params)   # ← typed, no magic
    result = BacktestRunner(engine, adapter, ...).run(bars)
```

### Decision 2 — IS/OOS split by bar count (trailing fraction), not calendar

**Chosen:** `is_fraction=0.8` keeps the first 80% of bars as IS, the last 20% as OOS.

**Alternative:** Calendar-based split (e.g., "last N months as OOS").

**Rationale:** Bar-count split is adapter-agnostic and works correctly for sessions with gaps (weekends, holidays). The caller can always pre-filter bars by calendar before passing them in.

### Decision 3 — Walk-forward with fixed-size rolling windows

**Chosen:** Rolling `train_bars` IS window + `test_bars` OOS window, stepping forward by `test_bars` each iteration.

```
Bars: |──────────────────────────────────────────────────|
      [── IS(train) ──][OOS]
                  [── IS(train) ──][OOS]
                              [── IS(train) ──][OOS]
```

**Rationale:** Anchored (expanding) walk-forward overfits to the distant past. Rolling windows reflect the strategy's practical retraining cadence and are simpler to interpret.

**WF efficiency** = mean(OOS Sharpe per window) / mean(IS Sharpe per window). Values > 0.6 indicate robustness; < 0.3 indicates overfitting.

### Decision 4 — Parallelism via ProcessPoolExecutor with module-level worker

**Chosen:** `concurrent.futures.ProcessPoolExecutor`. Worker is a top-level module function (picklable) that receives a serializable `_TrialSpec` dataclass (bars, timestamps, factory module path + name, params, adapter config path, equity).

**Alternative A:** `multiprocessing.Pool` with `dill` for lambda pickling.  
**Alternative B:** Serial execution only.

**Rationale:** `ProcessPoolExecutor` is stdlib, no extra deps. Lambdas and closures can't be pickled by default, so we serialize the factory as a `(module, function_name)` reference plus a kwargs dict. The worker reconstructs it via `importlib`. This keeps the API ergonomic (pass any module-level factory function) while enabling true multiprocessing.

**Default:** `n_jobs=1` (serial) for safety. Caller opts in to parallelism.

### Decision 5 — Result type: polars DataFrame + structured dataclasses

**Chosen:** `OptimizerResult` contains:
- `trials: pl.DataFrame` — one row per trial, all param columns + all metric columns, sorted by objective descending
- `best_params: dict[str, Any]`
- `best_is_result: BacktestResult`
- `best_oos_result: BacktestResult | None`

`WalkForwardResult` contains:
- `windows: list[WindowResult]` — IS and OOS `BacktestResult` per window, plus which params were chosen
- `efficiency: float`
- `combined_oos_metrics: dict[str, float]` — aggregate across all OOS windows

**Rationale:** polars DataFrame is already used by `scanner.py` and the dashboard. Structured dataclasses allow `print_backtest_report()` to be called directly on the IS/OOS results.

### Decision 6 — ATR Mean Reversion: add rsi_oversold / rsi_overbought to factory kwargs

**Chosen:** Add `rsi_oversold: float = 25.0` and `rsi_overbought: float = 75.0` to `ATRMeanReversionEntryPolicy.__init__()` and `create_atr_mean_reversion_engine()`.

**Rationale:** Strict RSI thresholds (25/75) are the most likely parameter to tune — they directly control trade frequency vs. selectivity. Without these as parameters, the optimizer can only tune risk management, not entry quality.

## Risks / Trade-offs

**[Risk] Optimizer finds parameters that work purely by chance (in-sample overfitting)**
→ Mitigation: IS/OOS split is mandatory when `is_fraction < 1.0`. Walk-forward efficiency < 0.3 is flagged as a warning in the result. Always report OOS result alongside IS.

**[Risk] Small trade count per window in 1-min walk-forward**
→ Mitigation: The ATR MR strategy fires ~9 trades/month. With 3-month IS windows we get ~27 trades — borderline for statistical significance. Optimizer output warns when IS trade count < 30. Walk-forward on shorter timeframes may not be reliable; document this constraint.

**[Risk] `ProcessPoolExecutor` pickling fails for complex factories**
→ Mitigation: Default `n_jobs=1`. Parallelism is opt-in and documented as requiring module-level factory functions. Clear error message if pickle fails.

**[Risk] strategies spec says files should only import from `src.core.policies` and `src.core.types`, but `atr_mean_reversion.py` currently imports from `src.core.position_engine`**
→ Mitigation: Fix the import violation in the same PR — move `PositionEngine` construction to a thin wrapper, or relax the spec constraint for factory functions.

## Migration Plan

1. Implement `StrategyOptimizer` in `src/simulator/strategy_optimizer.py`
2. Add result types to `src/simulator/types.py`
3. Add `rsi_oversold`/`rsi_overbought` to `atr_mean_reversion.py`
4. Run optimizer on TX 1-min data (1 year IS + 1 month OOS) to verify end-to-end
5. No migrations, no breaking changes — all additions are new public API

## Open Questions

- **Minimum IS trade count threshold**: 30 is a rule of thumb. Configurable or hard-coded warning?
- **Random search bounds**: Should `random_search()` accept `(min, max, type)` tuples or log-uniform sampling for multipliers? Deferred to implementation.
- **Should `WalkForwardResult.combined_oos_metrics` be a concatenation of all OOS fills or just average per-window metrics?** Concatenation is more accurate but requires careful equity curve stitching.
