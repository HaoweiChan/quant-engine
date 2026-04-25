"""Monte Carlo simulation runner."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import numpy as np
import numpy.typing as npt

from src.core.adapter import BaseAdapter
from src.core.types import PyramidConfig
from src.simulator.backtester import BacktestRunner
from src.simulator.fill_model import FillModel
from src.simulator.metrics import max_drawdown_pct, sharpe_ratio
from src.simulator.price_gen import generate_paths
from src.simulator.types import MonteCarloResult, PathConfig


def run_monte_carlo(
    n_paths: int,
    config: PyramidConfig,
    adapter: BaseAdapter,
    path_config: PathConfig | None = None,
    fill_model: FillModel | None = None,
    initial_equity: float = 2_000_000.0,
    ruin_threshold: float = 0.5,
    use_ray: bool = False,
    ray_threshold: int = 50,
) -> MonteCarloResult:
    """Run N synthetic paths through PositionEngine and collect statistics."""
    if path_config is None:
        path_config = PathConfig()

    paths = generate_paths(n_paths, path_config)
    from src.core.sizing import default_sizing_config
    runner = BacktestRunner(
        config, adapter, fill_model, initial_equity,
        sizing_config=default_sizing_config(initial_equity=initial_equity),
    )

    if use_ray and n_paths >= ray_threshold:
        results = _run_parallel(paths, runner, path_config)
    else:
        results = _run_sequential(paths, runner, path_config)

    terminal_pnls, max_dds, sharpes = results
    pnl_arr = np.array(terminal_pnls)
    percentiles = {
        "P5": float(np.percentile(pnl_arr, 5)),
        "P25": float(np.percentile(pnl_arr, 25)),
        "P50": float(np.percentile(pnl_arr, 50)),
        "P75": float(np.percentile(pnl_arr, 75)),
        "P95": float(np.percentile(pnl_arr, 95)),
    }
    wr = float(np.mean(np.array(terminal_pnls) > 0))
    ruin_count = sum(1 for p in terminal_pnls if p < -ruin_threshold * initial_equity)
    ruin_prob = ruin_count / n_paths if n_paths > 0 else 0.0

    return MonteCarloResult(
        terminal_pnl_distribution=terminal_pnls,
        percentiles=percentiles,
        win_rate=wr,
        max_drawdown_distribution=max_dds,
        sharpe_distribution=sharpes,
        ruin_probability=ruin_prob,
    )


def _run_sequential(
    paths: npt.NDArray[np.float64], runner: BacktestRunner, path_config: PathConfig
) -> tuple[list[float], list[float], list[float]]:
    terminal_pnls: list[float] = []
    max_dds: list[float] = []
    sharpes: list[float] = []
    for path in paths:
        bars, timestamps = _path_to_bars(path, path_config)
        result = runner.run(bars, timestamps=timestamps)
        terminal_pnls.append(result.equity_curve[-1] - result.equity_curve[0])
        max_dds.append(max_drawdown_pct(result.equity_curve))
        sharpes.append(sharpe_ratio(result.equity_curve))
    return terminal_pnls, max_dds, sharpes


def _run_parallel(
    paths: npt.NDArray[np.float64], runner: BacktestRunner, path_config: PathConfig
) -> tuple[list[float], list[float], list[float]]:
    # Fallback to sequential if ray not available
    try:
        import ray  # type: ignore[import-not-found]

        @ray.remote  # type: ignore[untyped-decorator]
        def _run_one(path: npt.NDArray[np.float64]) -> tuple[float, float, float]:
            bars, timestamps = _path_to_bars(path, path_config)
            result = runner.run(bars, timestamps=timestamps)
            return (
                result.equity_curve[-1] - result.equity_curve[0],
                max_drawdown_pct(result.equity_curve),
                sharpe_ratio(result.equity_curve),
            )

        if not ray.is_initialized():
            ray.init(ignore_reinit_error=True)
        futures = [_run_one.remote(p) for p in paths]
        results = ray.get(futures)
        pnls = [r[0] for r in results]
        dds = [r[1] for r in results]
        sharps = [r[2] for r in results]
        return pnls, dds, sharps
    except ImportError:
        return _run_sequential(paths, runner, path_config)


def _path_to_bars(
    price_path: npt.NDArray[np.float64], config: PathConfig
) -> tuple[list[dict[str, Any]], list[datetime]]:
    bars: list[dict[str, Any]] = []
    timestamps: list[datetime] = []
    base_ts = datetime(2024, 1, 2, 9, 0, tzinfo=UTC)
    for i in range(1, len(price_path)):
        p = float(price_path[i])
        prev = float(price_path[i - 1])
        bars.append(
            {
                "price": p,
                "symbol": "TX",
                "daily_atr": abs(p - prev) * 2,
                "open": prev,
                "high": max(p, prev) * 1.001,
                "low": min(p, prev) * 0.999,
                "close": p,
            }
        )
        timestamps.append(base_ts + timedelta(days=i))
    return bars, timestamps


_TAIFEX_SESSIONS = [
    (8, 45, 15),  # Pre-open: 08:45–09:00 (15 minutes, ORB window)
    (9, 0, 255),  # Day session: 09:00–13:15 (255 minutes)
    (15, 15, 795),  # Night session: 15:15–04:30+1 (795 minutes)
]
TAIFEX_BARS_PER_DAY = sum(s[2] for s in _TAIFEX_SESSIONS)  # 1065


def _generate_taifex_timestamps(n_bars: int) -> list[datetime]:
    """Generate timestamps cycling through TAIFEX day + night sessions."""
    timestamps: list[datetime] = []
    day = datetime(2024, 1, 2, tzinfo=UTC)
    bar_idx = 0
    while bar_idx < n_bars:
        if day.weekday() >= 5:
            day += timedelta(days=1)
            continue
        for start_h, start_m, duration in _TAIFEX_SESSIONS:
            session_start = day.replace(hour=start_h, minute=start_m)
            for minute in range(duration):
                if bar_idx >= n_bars:
                    break
                timestamps.append(session_start + timedelta(minutes=minute))
                bar_idx += 1
        day += timedelta(days=1)
    return timestamps


def _add_microstructure(
    prices: npt.NDArray[np.float64],
    halflife: int = 2,
    amplitude_frac: float = 0.003,
) -> npt.NDArray[np.float64]:
    """Overlay price-level mean reversion (bid-ask bounce + microstructure).

    Generates an OU noise process on prices that mean-reverts around zero
    with the given halflife (in bars). amplitude_frac controls the noise
    size relative to price level (~3 ticks for TAIFEX TX at 20000).
    """
    rng = np.random.default_rng()
    n = len(prices)
    theta = np.log(2) / halflife
    noise = np.empty(n)
    noise[0] = 0.0
    for i in range(1, n):
        amplitude = prices[i] * amplitude_frac
        noise[i] = (1 - theta) * noise[i - 1] + amplitude * rng.standard_normal()
    return prices + noise


def _path_to_intraday_bars(
    price_path: npt.NDArray[np.float64], config: PathConfig
) -> tuple[list[dict[str, Any]], list[datetime]]:
    """Convert a price path to 1-min bars with TAIFEX session timestamps.

    Adds microstructure noise (bid-ask bounce, OU at the bar level) so
    mean-reversion strategies have realistic short-term reversal patterns.
    """
    import random

    adjusted = _add_microstructure(price_path)
    n = len(adjusted) - 1
    timestamps = _generate_taifex_timestamps(n)
    bars: list[dict[str, Any]] = []
    atr_window: list[float] = []
    rng = random.Random(42)
    for i in range(1, len(adjusted)):
        p = float(adjusted[i])
        prev = float(adjusted[i - 1])
        atr_window.append(abs(p - prev))
        if len(atr_window) > 14:
            atr_window.pop(0)
        daily_atr = sum(atr_window) / len(atr_window) * 14
        bars.append(
            {
                "price": p,
                "symbol": "TX",
                "daily_atr": daily_atr,
                "open": prev,
                "high": max(p, prev) * 1.0002,
                "low": min(p, prev) * 0.9998,
                "close": p,
                "volume": rng.uniform(1000, 5000),
            }
        )
    return bars, timestamps
