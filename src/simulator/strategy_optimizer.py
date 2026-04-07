"""Generic strategy parameter optimizer.

Accepts any `engine_factory(**kwargs) -> PositionEngine` callable and a
`param_grid` dict, runs real OHLCV backtests for every combination, and
returns ranked results with full per-trial metrics.

Supports:
- grid_search   — exhaustive combination sweep with optional IS/OOS split
- walk_forward  — rolling IS+OOS windows with efficiency scoring
- random_search — random sampling from continuous param bounds

For parallel execution (n_jobs > 1), engine_factory MUST be either a
module-level function or a picklable callable class (not a lambda or closure).
"""
from __future__ import annotations

import inspect
import importlib
import itertools

import numpy as np
import polars as pl

from datetime import datetime
from typing import Any, Callable
from collections import defaultdict
from src.core.adapter import BaseAdapter
from src.core.position_engine import PositionEngine
from src.simulator.backtester import BacktestRunner
import multiprocessing
from concurrent.futures import ProcessPoolExecutor, as_completed
from src.simulator.fill_model import FillModel, MarketImpactFillModel
from src.simulator.types import (
    BacktestResult,
    OptimizerResult,
    WalkForwardResult,
    WindowResult,
)

_LOW_TRADE_THRESHOLD = 30
_OBJECTIVE_DIRECTIONS: dict[str, str] = {
    "max_drawdown_abs": "minimize",
    "max_drawdown_pct": "minimize",
}


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
    force_flat_indices: set[int] | None = None,
) -> dict[str, Any]:
    """Picklable worker: reconstruct adapter + factory, run one backtest trial."""
    mod = importlib.import_module(factory_module)
    factory = getattr(mod, factory_name)
    engine = factory(**params)

    a_mod = importlib.import_module(adapter_module)
    a_cls = getattr(a_mod, adapter_class)
    adapter = a_cls(**adapter_kwargs)

    fill_model = MarketImpactFillModel()
    runner = BacktestRunner(
        config=lambda: engine,
        adapter=adapter,
        fill_model=fill_model,
        initial_equity=initial_equity,
    )
    result = runner.run(bars, timestamps=timestamps, force_flat_indices=force_flat_indices)
    row: dict[str, Any] = dict(params)
    row.update(result.metrics)
    row["_trade_count"] = int(result.metrics.get("trade_count", 0.0))
    return row


def _run_single_trial_callable(
    bars: list[dict[str, Any]],
    timestamps: list[datetime],
    factory_pickle: bytes,
    params: dict[str, Any],
    adapter_module: str,
    adapter_class: str,
    adapter_kwargs: dict[str, Any],
    initial_equity: float,
    slippage: float,
    force_flat_indices: set[int] | None = None,
) -> dict[str, Any]:
    """Picklable worker for callable factory objects (e.g. _PicklableEngineFactory)."""
    import pickle as _pickle
    factory = _pickle.loads(factory_pickle)
    engine = factory(**params)

    a_mod = importlib.import_module(adapter_module)
    a_cls = getattr(a_mod, adapter_class)
    adapter = a_cls(**adapter_kwargs)

    fill_model = MarketImpactFillModel()
    runner = BacktestRunner(
        config=lambda: engine,
        adapter=adapter,
        fill_model=fill_model,
        initial_equity=initial_equity,
    )
    result = runner.run(bars, timestamps=timestamps, force_flat_indices=force_flat_indices)
    row: dict[str, Any] = dict(params)
    row.update(result.metrics)
    row["_trade_count"] = int(result.metrics.get("trade_count", 0.0))
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
        mode: str = "research",
        min_trade_count: int = _LOW_TRADE_THRESHOLD,
        min_expectancy: float = 0.0,
        min_oos_objective: float = 0.0,
        worker_pool: "ProcessPoolExecutor | None" = None,
    ) -> None:
        if mode not in {"research", "production_intent"}:
            raise ValueError("mode must be 'research' or 'production_intent'")
        self._adapter = adapter
        self._fill_model = fill_model or MarketImpactFillModel()
        self._initial_equity = initial_equity
        self._n_jobs = n_jobs
        self._slippage = getattr(self._fill_model, "_slippage", 1.0)
        self._mode = mode
        self._min_trade_count = min_trade_count
        self._min_expectancy = min_expectancy
        self._min_oos_objective = min_oos_objective
        # Pre-initialized pool from caller (avoids per-call spawn overhead and
        # the asyncio/signal-handling issues that arise when spawning from a
        # thread inside an asyncio application).
        self._worker_pool: "ProcessPoolExecutor | None" = worker_pool

    # -- Public API --

    def grid_search(
        self,
        engine_factory: Callable[..., PositionEngine],
        param_grid: dict[str, list[Any]],
        bars: list[dict[str, Any]],
        timestamps: list[datetime],
        objective: str = "sortino",
        is_fraction: float = 0.8,
        force_flat_indices: set[int] | None = None,
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

        # Remap force_flat_indices to IS/OOS slices
        is_ffi = (
            {idx for idx in force_flat_indices if idx < is_end} if force_flat_indices else None
        )
        oos_ffi = (
            {idx - is_end for idx in force_flat_indices if idx >= is_end} if force_flat_indices and oos_bars else None
        )

        rows = self._dispatch(engine_factory, param_list, is_bars, is_ts, force_flat_indices=is_ffi)

        # Validate objective; skip error rows from parallel failures
        if rows:
            _validate_objective(objective, rows)

        objective_direction = _objective_direction(objective)
        descending = objective_direction == "maximize"
        (
            df,
            disqualified_trials,
            gate_details,
            warnings,
        ) = self._rank_trials(
            rows=rows,
            param_keys=keys,
            objective=objective,
            descending=descending,
        )
        best_params = {k: df[k][0] for k in keys}

        best_is = self._run_backtest(engine_factory, best_params, is_bars, is_ts, force_flat_indices=is_ffi)
        best_oos = (
            self._run_backtest(engine_factory, best_params, oos_bars, oos_ts, force_flat_indices=oos_ffi)
            if oos_bars else None
        )

        gate_results = self._build_gate_results(
            best_is_result=best_is,
            best_oos_result=best_oos,
            objective=objective,
            objective_direction=objective_direction,
        )
        promotable = self._mode == "production_intent" and all(gate_results.values())

        return OptimizerResult(
            trials=df,
            best_params=best_params,
            best_is_result=best_is,
            best_oos_result=best_oos,
            warnings=warnings,
            objective_name=objective,
            objective_direction=objective_direction,
            disqualified_trials=disqualified_trials,
            gate_results=gate_results,
            gate_details=gate_details,
            promotable=promotable,
            mode=self._mode,
        )

    def walk_forward(
        self,
        engine_factory: Callable[..., PositionEngine],
        param_grid: dict[str, list[Any]],
        bars: list[dict[str, Any]],
        timestamps: list[datetime],
        train_bars: int,
        test_bars: int,
        objective: str = "sortino",
        force_flat_indices: set[int] | None = None,
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

            # Remap absolute force_flat_indices to window-local indices
            w_is_ffi = (
                {idx - is_start for idx in force_flat_indices if is_start <= idx < is_end}
                if force_flat_indices else None
            )
            w_oos_ffi = (
                {idx - is_end for idx in force_flat_indices if is_end <= idx < oos_end}
                if force_flat_indices else None
            )

            # Optimize on IS
            is_opt = self.grid_search(
                engine_factory, param_grid, w_is_bars, w_is_ts,
                objective=objective, is_fraction=1.0, force_flat_indices=w_is_ffi,
            )
            best = is_opt.best_params
            is_trades = int(is_opt.best_is_result.metrics.get("trade_count", 0.0))
            oos_result = self._run_backtest(engine_factory, best, w_oos_bars, w_oos_ts, force_flat_indices=w_oos_ffi)

            windows.append(WindowResult(
                window_idx=w,
                is_bars=len(w_is_bars),
                oos_bars=len(w_oos_bars),
                best_params=best,
                is_result=is_opt.best_is_result,
                oos_result=oos_result,
                low_trade_count=is_trades < self._min_trade_count,
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
        objective: str = "sortino",
        is_fraction: float = 0.8,
        seed: int | None = None,
        force_flat_indices: set[int] | None = None,
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

        # Remap force_flat_indices to IS/OOS slices
        is_ffi = (
            {idx for idx in force_flat_indices if idx < is_end} if force_flat_indices else None
        )
        oos_ffi = (
            {idx - is_end for idx in force_flat_indices if idx >= is_end} if force_flat_indices and oos_bars else None
        )

        rows = self._dispatch(engine_factory, param_list, is_bars, is_ts, force_flat_indices=is_ffi)

        if rows:
            _validate_objective(objective, rows)

        objective_direction = _objective_direction(objective)
        descending = objective_direction == "maximize"
        (
            df,
            disqualified_trials,
            gate_details,
            warnings,
        ) = self._rank_trials(
            rows=rows,
            param_keys=keys,
            objective=objective,
            descending=descending,
        )
        best_params = {k: df[k][0] for k in keys}

        best_is = self._run_backtest(engine_factory, best_params, is_bars, is_ts, force_flat_indices=is_ffi)
        best_oos = (
            self._run_backtest(engine_factory, best_params, oos_bars, oos_ts, force_flat_indices=oos_ffi)
            if oos_bars else None
        )

        gate_results = self._build_gate_results(
            best_is_result=best_is,
            best_oos_result=best_oos,
            objective=objective,
            objective_direction=objective_direction,
        )
        promotable = self._mode == "production_intent" and all(gate_results.values())

        return OptimizerResult(
            trials=df,
            best_params=best_params,
            best_is_result=best_is,
            best_oos_result=best_oos,
            warnings=warnings,
            objective_name=objective,
            objective_direction=objective_direction,
            disqualified_trials=disqualified_trials,
            gate_results=gate_results,
            gate_details=gate_details,
            promotable=promotable,
            mode=self._mode,
        )

    # -- Private helpers --

    def _run_backtest(
        self,
        factory: Callable[..., PositionEngine],
        params: dict[str, Any],
        bars: list[dict[str, Any]],
        timestamps: list[datetime],
        force_flat_indices: set[int] | None = None,
    ) -> BacktestResult:
        engine = factory(**params)
        runner = BacktestRunner(
            config=lambda: engine,
            adapter=self._adapter,
            fill_model=self._fill_model,
            initial_equity=self._initial_equity,
        )
        return runner.run(bars, timestamps=timestamps, force_flat_indices=force_flat_indices)

    def _dispatch(
        self,
        factory: Callable[..., PositionEngine],
        param_list: list[dict[str, Any]],
        bars: list[dict[str, Any]],
        timestamps: list[datetime],
        force_flat_indices: set[int] | None = None,
    ) -> list[dict[str, Any]]:
        if self._n_jobs == 1 or len(param_list) <= 1:
            return [
                self._run_trial_serial(factory, p, bars, timestamps, force_flat_indices=force_flat_indices)
                for p in param_list
            ]

        # Parallel path
        a_mod = inspect.getmodule(self._adapter).__name__  # type: ignore[union-attr]
        a_cls = type(self._adapter).__name__

        futures_map = {}
        # Use pre-initialized pool if provided; otherwise create one per-call.
        # The pre-initialized pool is forked before asyncio starts, avoiding
        # signal-handling deadlocks when called from a thread inside asyncio.
        _owned_pool = None
        if self._worker_pool is not None:
            pool = self._worker_pool
        else:
            _ctx = multiprocessing.get_context("forkserver")
            _owned_pool = ProcessPoolExecutor(max_workers=self._n_jobs, mp_context=_ctx)
            pool = _owned_pool
        try:
            if inspect.isfunction(factory):
                # Module-level function: serialize by module+name
                mod_name = inspect.getmodule(factory).__name__  # type: ignore[union-attr]
                fn_name = factory.__name__
                for params in param_list:
                    f = pool.submit(
                        _run_single_trial,
                        bars, timestamps,
                        mod_name, fn_name, params,
                        a_mod, a_cls, {},
                        self._initial_equity, self._slippage,
                        force_flat_indices,
                    )
                    futures_map[f] = params
            else:
                # Callable class: serialize by pickling
                import pickle as _pickle
                factory_pickle = _pickle.dumps(factory)
                for params in param_list:
                    f = pool.submit(
                        _run_single_trial_callable,
                        bars, timestamps,
                        factory_pickle, params,
                        a_mod, a_cls, {},
                        self._initial_equity, self._slippage,
                        force_flat_indices,
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
        finally:
            if _owned_pool is not None:
                _owned_pool.shutdown(wait=False)

    def _run_trial_serial(
        self,
        factory: Callable[..., PositionEngine],
        params: dict[str, Any],
        bars: list[dict[str, Any]],
        timestamps: list[datetime],
        force_flat_indices: set[int] | None = None,
    ) -> dict[str, Any]:
        result = self._run_backtest(factory, params, bars, timestamps, force_flat_indices=force_flat_indices)
        row: dict[str, Any] = dict(params)
        row.update(result.metrics)
        row["_trade_count"] = int(result.metrics.get("trade_count", 0.0))
        return row

    def _rank_trials(
        self,
        rows: list[dict[str, Any]],
        param_keys: list[str],
        objective: str,
        descending: bool,
    ) -> tuple[pl.DataFrame, int, dict[str, float | str], list[str]]:
        valid_rows = [r for r in rows if "_error" not in r]
        if not valid_rows:
            raise ValueError("All optimizer trials failed — check engine factory and params")
        disqualified_trials = 0
        eligible_rows = valid_rows
        gate_details: dict[str, float | str] = {
            "min_trade_count": float(self._min_trade_count),
            "min_expectancy": self._min_expectancy,
        }
        if self._mode == "production_intent":
            eligible_rows = []
            for row in valid_rows:
                trade_count = _extract_trade_count(row)
                expectancy = _extract_expectancy(row)
                trade_ok = trade_count >= self._min_trade_count
                expectancy_ok = expectancy is None or expectancy >= self._min_expectancy
                if trade_ok and expectancy_ok:
                    eligible_rows.append(row)
                    continue
                disqualified_trials += 1
            gate_details["eligible_trials"] = float(len(eligible_rows))
            gate_details["total_trials"] = float(len(valid_rows))
            if not eligible_rows:
                raise ValueError(
                    "No promotable candidate after production-intent gates "
                    f"(min_trade_count={self._min_trade_count}, min_expectancy={self._min_expectancy})"
                )
        warnings = _low_trade_count_warnings(rows, param_keys, threshold=self._min_trade_count)
        df = pl.DataFrame(eligible_rows).sort(objective, descending=descending)
        return df, disqualified_trials, gate_details, warnings

    def _build_gate_results(
        self,
        best_is_result: BacktestResult,
        best_oos_result: BacktestResult | None,
        objective: str,
        objective_direction: str,
    ) -> dict[str, bool]:
        if self._mode != "production_intent":
            return {}
        is_trade_count = int(best_is_result.metrics.get("trade_count", 0.0))
        is_expectancy = _extract_expectancy(best_is_result.metrics)
        min_trade_count_pass = is_trade_count >= self._min_trade_count
        min_expectancy_pass = is_expectancy is None or is_expectancy >= self._min_expectancy
        oos_floor_pass = True
        if best_oos_result is not None:
            oos_value = float(best_oos_result.metrics.get(objective, 0.0))
            if objective_direction == "maximize":
                oos_floor_pass = oos_value >= self._min_oos_objective
        return {
            "min_trade_count_pass": min_trade_count_pass,
            "min_expectancy_pass": min_expectancy_pass,
            "oos_floor_pass": oos_floor_pass,
        }


# ---------------------------------------------------------------------------
# Free helper functions
# ---------------------------------------------------------------------------

def _objective_direction(objective: str) -> str:
    return _OBJECTIVE_DIRECTIONS.get(objective, "maximize")


def _extract_trade_count(row: dict[str, Any]) -> int:
    value = row.get("trade_count", row.get("_trade_count", 0))
    return int(value)


def _extract_expectancy(row: dict[str, Any]) -> float | None:
    if "expectancy" in row and row["expectancy"] is not None:
        return float(row["expectancy"])
    required = ("win_rate", "avg_win", "avg_loss")
    if not all(k in row and row[k] is not None for k in required):
        return None
    win_rate = float(row["win_rate"])
    avg_win = float(row["avg_win"])
    avg_loss = float(row["avg_loss"])
    return (win_rate * avg_win) + ((1.0 - win_rate) * avg_loss)


def _validate_objective(objective: str, rows: list[dict[str, Any]]) -> None:
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
    """Raise ValueError if factory cannot be pickled for parallel execution."""
    name = getattr(factory, "__name__", "")
    qualname = getattr(factory, "__qualname__", "")
    if name == "<lambda>" or "<locals>" in qualname:
        raise ValueError(
            f"engine_factory '{qualname}' is a lambda or closure and cannot be "
            "pickled for parallel execution (n_jobs > 1). "
            "Use a module-level function or a picklable callable class instead."
        )
    if not inspect.isfunction(factory):
        # Callable class: verify it can actually be pickled before dispatching workers
        import pickle as _pickle
        try:
            _pickle.dumps(factory)
        except Exception as exc:
            raise ValueError(
                f"engine_factory '{type(factory).__name__}' cannot be pickled for "
                f"parallel execution (n_jobs > 1): {exc}"
            ) from exc


def _low_trade_count_warnings(
    rows: list[dict[str, Any]],
    param_keys: list[str],
    threshold: int = _LOW_TRADE_THRESHOLD,
) -> list[str]:
    warnings: list[str] = []
    for row in rows:
        count = row.get("_trade_count", threshold)
        if count < threshold:
            label = ", ".join(f"{k}={row[k]}" for k in param_keys if k in row)
            warnings.append(
                f"Low IS trade count ({count} < {threshold}) for params: {label}"
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
