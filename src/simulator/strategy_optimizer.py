"""Generic strategy parameter optimizer.

Accepts any `engine_factory(**kwargs) -> PositionEngine` callable and a
`param_grid` dict, runs real OHLCV backtests for every combination, and
returns ranked results with full per-trial metrics.

Supports:
- grid_search   — exhaustive combination sweep with optional IS/OOS split
- walk_forward  — rolling IS+OOS windows with efficiency scoring
- random_search — random sampling from continuous param bounds

For parallel execution (n_jobs > 1), engine_factory MUST be a module-level
picklable function (not a lambda or closure).
"""
from __future__ import annotations

import importlib
import inspect
import itertools
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime
from typing import Any, Callable

import numpy as np
import polars as pl

from src.core.adapter import BaseAdapter
from src.core.position_engine import PositionEngine
from src.simulator.backtester import BacktestRunner
from src.simulator.fill_model import ClosePriceFillModel, FillModel
from src.simulator.types import (
    BacktestResult,
    OptimizerResult,
    WalkForwardResult,
    WindowResult,
)

_LOW_TRADE_THRESHOLD = 30


# ---------------------------------------------------------------------------
# Module-level worker (must be picklable for ProcessPoolExecutor)
# ---------------------------------------------------------------------------

def _run_single_trial(
    bars: list[dict[str, Any]],
    timestamps: list[datetime],
    factory_module: str,
    factory_name: str,
    params: dict[str, Any],
    adapter_module: str,
    adapter_class: str,
    adapter_kwargs: dict[str, Any],
    initial_equity: float,
    slippage: float,
) -> dict[str, Any]:
    """Picklable worker: reconstruct adapter + factory, run one backtest trial."""
    mod = importlib.import_module(factory_module)
    factory = getattr(mod, factory_name)
    engine = factory(**params)

    a_mod = importlib.import_module(adapter_module)
    a_cls = getattr(a_mod, adapter_class)
    adapter = a_cls(**adapter_kwargs)

    fill_model = ClosePriceFillModel(slippage_points=slippage)
    runner = BacktestRunner(
        config=lambda: engine,
        adapter=adapter,
        fill_model=fill_model,
        initial_equity=initial_equity,
    )
    result = runner.run(bars, timestamps=timestamps)
    row: dict[str, Any] = dict(params)
    row.update(result.metrics)
    row["_trade_count"] = len([f for f in result.trade_log if f.side == "buy"])
    return row


# ---------------------------------------------------------------------------
# StrategyOptimizer
# ---------------------------------------------------------------------------

class StrategyOptimizer:
    """Run grid/random/walk-forward optimization on any parameterized strategy."""

    def __init__(
        self,
        adapter: BaseAdapter,
        fill_model: FillModel | None = None,
        initial_equity: float = 2_000_000.0,
        n_jobs: int = 1,
    ) -> None:
        self._adapter = adapter
        self._fill_model = fill_model or ClosePriceFillModel(slippage_points=1.0)
        self._initial_equity = initial_equity
        self._n_jobs = n_jobs
        self._slippage = getattr(self._fill_model, "_slippage", 1.0)

    # -- Public API --

    def grid_search(
        self,
        engine_factory: Callable[..., PositionEngine],
        param_grid: dict[str, list[Any]],
        bars: list[dict[str, Any]],
        timestamps: list[datetime],
        objective: str = "sharpe",
        is_fraction: float = 0.8,
    ) -> OptimizerResult:
        """Exhaustive grid search across all param combinations.

        Args:
            engine_factory: Module-level callable `(**params) -> PositionEngine`.
            param_grid:     Dict of param_name → list of candidate values.
            bars:           OHLCV bar dicts for the full period.
            timestamps:     Matching timestamps for each bar.
            objective:      Metric name to optimize (must appear in BacktestResult.metrics).
            is_fraction:    Fraction of bars used as in-sample. Remainder is OOS.
        """
        if self._n_jobs > 1:
            _check_pickle_safety(engine_factory)

        combos = list(itertools.product(*param_grid.values()))
        keys = list(param_grid.keys())
        param_list = [dict(zip(keys, c)) for c in combos]

        is_end = int(len(bars) * is_fraction)
        is_bars = bars[:is_end]
        is_ts = timestamps[:is_end]
        oos_bars = bars[is_end:] if is_fraction < 1.0 else []
        oos_ts = timestamps[is_end:] if is_fraction < 1.0 else []

        rows = self._dispatch(engine_factory, param_list, is_bars, is_ts)

        # Validate objective; skip error rows from parallel failures
        if rows:
            _validate_objective(objective, rows)

        # Filter out error rows before building DataFrame
        valid_rows = [r for r in rows if "_error" not in r]
        if not valid_rows:
            raise ValueError("All optimizer trials failed — check engine factory and params")
        df = pl.DataFrame(valid_rows).sort(objective, descending=True)
        best_params = {k: df[k][0] for k in keys}

        warnings = _low_trade_count_warnings(rows, keys)

        best_is = self._run_backtest(engine_factory, best_params, is_bars, is_ts)
        best_oos = (
            self._run_backtest(engine_factory, best_params, oos_bars, oos_ts)
            if oos_bars else None
        )

        return OptimizerResult(
            trials=df,
            best_params=best_params,
            best_is_result=best_is,
            best_oos_result=best_oos,
            warnings=warnings,
        )

    def walk_forward(
        self,
        engine_factory: Callable[..., PositionEngine],
        param_grid: dict[str, list[Any]],
        bars: list[dict[str, Any]],
        timestamps: list[datetime],
        train_bars: int,
        test_bars: int,
        objective: str = "sharpe",
    ) -> WalkForwardResult:
        """Rolling walk-forward: optimize on IS, verify on OOS, compute efficiency.

        Args:
            train_bars: Number of bars in each IS (training) window.
            test_bars:  Number of bars in each OOS (test) window.
        """
        if train_bars + test_bars > len(bars):
            raise ValueError(
                f"train_bars ({train_bars}) + test_bars ({test_bars}) = "
                f"{train_bars + test_bars} exceeds total bars ({len(bars)})"
            )

        n_windows = (len(bars) - train_bars) // test_bars
        windows: list[WindowResult] = []

        for w in range(n_windows):
            is_start = w * test_bars
            is_end = is_start + train_bars
            oos_end = is_end + test_bars

            w_is_bars = bars[is_start:is_end]
            w_is_ts = timestamps[is_start:is_end]
            w_oos_bars = bars[is_end:oos_end]
            w_oos_ts = timestamps[is_end:oos_end]

            # Optimize on IS
            is_opt = self.grid_search(
                engine_factory, param_grid, w_is_bars, w_is_ts,
                objective=objective, is_fraction=1.0,
            )
            best = is_opt.best_params
            is_trades = len([f for f in is_opt.best_is_result.trade_log if f.side == "buy"])
            oos_result = self._run_backtest(engine_factory, best, w_oos_bars, w_oos_ts)

            windows.append(WindowResult(
                window_idx=w,
                is_bars=len(w_is_bars),
                oos_bars=len(w_oos_bars),
                best_params=best,
                is_result=is_opt.best_is_result,
                oos_result=oos_result,
                low_trade_count=is_trades < _LOW_TRADE_THRESHOLD,
            ))

        efficiency = _compute_efficiency(windows, objective)
        combined = _combine_oos_metrics(windows)

        return WalkForwardResult(
            windows=windows,
            efficiency=efficiency,
            combined_oos_metrics=combined,
        )

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
    ) -> OptimizerResult:
        """Random search over continuous param bounds.

        Args:
            param_bounds: Dict of param_name → (min_value, max_value).
            n_trials:     Number of random samples to evaluate.
            seed:         RNG seed for reproducibility.
        """
        rng = np.random.default_rng(seed)
        param_grid: dict[str, list[Any]] = {}
        for name, (lo, hi) in param_bounds.items():
            # Sample uniformly in [lo, hi]
            samples = rng.uniform(lo, hi, n_trials).tolist()
            param_grid[name] = samples

        # Build n_trials individual param dicts (not full cartesian product)
        keys = list(param_bounds.keys())
        param_list = [
            {k: param_grid[k][i] for k in keys}
            for i in range(n_trials)
        ]

        is_end = int(len(bars) * is_fraction)
        is_bars = bars[:is_end]
        is_ts = timestamps[:is_end]
        oos_bars = bars[is_end:] if is_fraction < 1.0 else []
        oos_ts = timestamps[is_end:] if is_fraction < 1.0 else []

        rows = self._dispatch(engine_factory, param_list, is_bars, is_ts)

        if rows:
            _validate_objective(objective, rows)

        valid_rows = [r for r in rows if "_error" not in r]
        if not valid_rows:
            raise ValueError("All optimizer trials failed — check engine factory and params")
        df = pl.DataFrame(valid_rows).sort(objective, descending=True)
        best_params = {k: df[k][0] for k in keys}
        warnings = _low_trade_count_warnings(rows, keys)

        best_is = self._run_backtest(engine_factory, best_params, is_bars, is_ts)
        best_oos = (
            self._run_backtest(engine_factory, best_params, oos_bars, oos_ts)
            if oos_bars else None
        )

        return OptimizerResult(
            trials=df,
            best_params=best_params,
            best_is_result=best_is,
            best_oos_result=best_oos,
            warnings=warnings,
        )

    # -- Private helpers --

    def _run_backtest(
        self,
        factory: Callable[..., PositionEngine],
        params: dict[str, Any],
        bars: list[dict[str, Any]],
        timestamps: list[datetime],
    ) -> BacktestResult:
        engine = factory(**params)
        runner = BacktestRunner(
            config=lambda: engine,
            adapter=self._adapter,
            fill_model=self._fill_model,
            initial_equity=self._initial_equity,
        )
        return runner.run(bars, timestamps=timestamps)

    def _dispatch(
        self,
        factory: Callable[..., PositionEngine],
        param_list: list[dict[str, Any]],
        bars: list[dict[str, Any]],
        timestamps: list[datetime],
    ) -> list[dict[str, Any]]:
        if self._n_jobs == 1 or len(param_list) <= 1:
            return [self._run_trial_serial(factory, p, bars, timestamps) for p in param_list]

        # Parallel path: serialize factory reference
        mod_name = inspect.getmodule(factory).__name__  # type: ignore[union-attr]
        fn_name = factory.__name__
        a_mod = inspect.getmodule(self._adapter).__name__  # type: ignore[union-attr]
        a_cls = type(self._adapter).__name__

        futures_map = {}
        with ProcessPoolExecutor(max_workers=self._n_jobs) as pool:
            for params in param_list:
                f = pool.submit(
                    _run_single_trial,
                    bars, timestamps,
                    mod_name, fn_name, params,
                    a_mod, a_cls, {},
                    self._initial_equity, self._slippage,
                )
                futures_map[f] = params

        rows: list[dict[str, Any]] = []
        for fut in as_completed(futures_map):
            try:
                rows.append(fut.result())
            except Exception as exc:
                params = futures_map[fut]
                rows.append({**params, "_error": str(exc)})
        return rows

    def _run_trial_serial(
        self,
        factory: Callable[..., PositionEngine],
        params: dict[str, Any],
        bars: list[dict[str, Any]],
        timestamps: list[datetime],
    ) -> dict[str, Any]:
        result = self._run_backtest(factory, params, bars, timestamps)
        row: dict[str, Any] = dict(params)
        row.update(result.metrics)
        row["_trade_count"] = len([f for f in result.trade_log if f.side == "buy"])
        return row


# ---------------------------------------------------------------------------
# Free helper functions
# ---------------------------------------------------------------------------

def _validate_objective(objective: str, rows: list[dict[str, Any]]) -> None:
    valid = {
        "sharpe", "sortino", "calmar", "max_drawdown_abs", "max_drawdown_pct",
        "win_rate", "profit_factor", "avg_win", "avg_loss", "trade_count",
        "avg_holding_period",
    }
    # Skip error rows (from failed parallel workers) when checking
    sample = next((r for r in rows if "_error" not in r), None)
    if sample is None:
        errors = [r.get("_error", "unknown") for r in rows[:3]]
        raise ValueError(f"All optimizer trials failed. Errors: {errors}")
    if objective not in sample:
        available = sorted(k for k in sample if not k.startswith("_"))
        raise ValueError(
            f"Objective '{objective}' not found in trial results. "
            f"Available metrics: {available}"
        )


def _check_pickle_safety(factory: Callable[..., Any]) -> None:
    """Raise ValueError if factory is a lambda or local closure (unpicklable)."""
    name = getattr(factory, "__name__", "")
    qualname = getattr(factory, "__qualname__", "")
    if name == "<lambda>" or "<locals>" in qualname:
        raise ValueError(
            f"engine_factory '{qualname}' is a lambda or closure and cannot be "
            "pickled for parallel execution (n_jobs > 1). "
            "Use a module-level function instead."
        )


def _low_trade_count_warnings(
    rows: list[dict[str, Any]], param_keys: list[str]
) -> list[str]:
    warnings: list[str] = []
    for row in rows:
        count = row.get("_trade_count", _LOW_TRADE_THRESHOLD)
        if count < _LOW_TRADE_THRESHOLD:
            label = ", ".join(f"{k}={row[k]}" for k in param_keys if k in row)
            warnings.append(
                f"Low IS trade count ({count} < {_LOW_TRADE_THRESHOLD}) for params: {label}"
            )
    return warnings


def _compute_efficiency(windows: list[WindowResult], objective: str) -> float:
    is_scores = [w.is_result.metrics.get(objective, 0.0) for w in windows]
    oos_scores = [w.oos_result.metrics.get(objective, 0.0) for w in windows]
    mean_is = sum(is_scores) / len(is_scores) if is_scores else 0.0
    mean_oos = sum(oos_scores) / len(oos_scores) if oos_scores else 0.0
    return mean_oos / mean_is if mean_is != 0.0 else 0.0


def _combine_oos_metrics(windows: list[WindowResult]) -> dict[str, float]:
    if not windows:
        return {}
    combined: dict[str, list[float]] = defaultdict(list)
    for w in windows:
        for k, v in w.oos_result.metrics.items():
            combined[k].append(v)
    return {k: sum(vs) / len(vs) for k, vs in combined.items()}
