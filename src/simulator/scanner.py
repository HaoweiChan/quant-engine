"""Parameter grid search with robust region identification."""
from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import polars as pl

from src.core.adapter import BaseAdapter
from src.core.types import PyramidConfig
from src.simulator.backtester import BacktestRunner
from src.simulator.fill_model import FillModel


@dataclass
class SweepRange:
    stop_atr_mult: list[float] = field(default_factory=lambda: [1.0, 1.5, 2.0])
    trail_atr_mult: list[float] = field(default_factory=lambda: [2.0, 3.0, 4.0])
    add_trigger_atr: list[list[float]] = field(
        default_factory=lambda: [[4.0, 8.0, 12.0]]
    )
    kelly_fraction: list[float] = field(default_factory=lambda: [0.15, 0.25, 0.35])


def grid_search(
    base_config: PyramidConfig,
    adapter: BaseAdapter,
    bars: list[dict[str, Any]],
    sweep: SweepRange | None = None,
    fill_model: FillModel | None = None,
    initial_equity: float = 2_000_000.0,
    timestamps: list[datetime] | None = None,
) -> pl.DataFrame:
    """Run backtest for each parameter combination, return results DataFrame."""
    if sweep is None:
        sweep = SweepRange()

    combos = list(itertools.product(
        sweep.stop_atr_mult,
        sweep.trail_atr_mult,
        sweep.add_trigger_atr,
        sweep.kelly_fraction,
    ))

    rows: list[dict[str, float]] = []
    for stop_m, trail_m, add_trig, kelly in combos:
        cfg = PyramidConfig(
            max_loss=base_config.max_loss,
            max_levels=base_config.max_levels,
            add_trigger_atr=add_trig,
            lot_schedule=base_config.lot_schedule,
            stop_atr_mult=stop_m,
            trail_atr_mult=trail_m,
            trail_lookback=base_config.trail_lookback,
            margin_limit=base_config.margin_limit,
            kelly_fraction=kelly,
            entry_conf_threshold=base_config.entry_conf_threshold,
        )
        from src.core.sizing import default_sizing_config
        runner = BacktestRunner(
            cfg, adapter, fill_model, initial_equity,
            sizing_config=default_sizing_config(initial_equity=initial_equity),
        )
        result = runner.run(bars, timestamps=timestamps)
        row: dict[str, float] = {
            "stop_atr_mult": stop_m,
            "trail_atr_mult": trail_m,
            "kelly_fraction": kelly,
        }
        row.update(result.metrics)
        rows.append(row)

    return pl.DataFrame(rows)


def find_robust_regions(
    results: pl.DataFrame,
    metric: str = "sharpe",
    top_pct: float = 0.2,
) -> pl.DataFrame:
    """Identify parameter regions where the metric is consistently good.

    Selects the top `top_pct` fraction of results by `metric`, then checks
    if neighboring parameter points (adjacent in each dimension) are also
    in the top set. Points with at least one good neighbor are "robust".
    """
    if metric not in results.columns:
        return results.head(0)

    threshold_idx = max(1, int(len(results) * top_pct))
    sorted_df = results.sort(metric, descending=True)
    top_set = sorted_df.head(threshold_idx)

    param_cols = ["stop_atr_mult", "trail_atr_mult", "kelly_fraction"]
    available = [c for c in param_cols if c in results.columns]
    if not available:
        return top_set

    top_keys = set()
    for row in top_set.iter_rows(named=True):
        top_keys.add(tuple(row[c] for c in available))

    robust_rows: list[int] = []
    for idx, row in enumerate(top_set.iter_rows(named=True)):
        key = tuple(row[c] for c in available)
        has_neighbor = False
        for dim_i, col in enumerate(available):
            unique_vals = sorted(results[col].unique().to_list())
            cur_pos = unique_vals.index(key[dim_i]) if key[dim_i] in unique_vals else -1
            for offset in (-1, 1):
                neighbor_pos = cur_pos + offset
                if 0 <= neighbor_pos < len(unique_vals):
                    neighbor_key = list(key)
                    neighbor_key[dim_i] = unique_vals[neighbor_pos]
                    if tuple(neighbor_key) in top_keys:
                        has_neighbor = True
                        break
            if has_neighbor:
                break
        if has_neighbor:
            robust_rows.append(idx)

    if not robust_rows:
        return top_set
    return top_set[robust_rows]
