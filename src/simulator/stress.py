"""Stress test framework with configurable extreme market scenarios."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import numpy as np
import numpy.typing as npt

from src.core.adapter import BaseAdapter
from src.core.types import PyramidConfig
from src.simulator.backtester import BacktestRunner
from src.simulator.fill_model import FillModel, MarketImpactFillModel
from src.simulator.types import StressResult, StressScenario


def run_stress_test(
    scenario: StressScenario,
    config: PyramidConfig,
    adapter: BaseAdapter,
    fill_model: FillModel | None = None,
    initial_equity: float = 2_000_000.0,
    start_price: float = 20000.0,
) -> StressResult:
    """Run a stress scenario through PositionEngine."""
    prices = _generate_scenario_prices(scenario, start_price)
    bars, timestamps = _prices_to_bars(prices)
    from src.core.sizing import default_sizing_config
    runner = BacktestRunner(
        config, adapter, fill_model, initial_equity,
        sizing_config=default_sizing_config(initial_equity=initial_equity),
    )
    result = runner.run(bars, timestamps=timestamps)

    cb_triggered = any(
        f.reason == "circuit_breaker" for f in result.trade_log
    )
    stops = [
        f.reason for f in result.trade_log
        if "stop" in f.reason.lower()
    ]

    return StressResult(
        scenario_name=scenario.name,
        final_pnl=result.equity_curve[-1] - result.equity_curve[0],
        max_drawdown=result.metrics.get("max_drawdown_pct", 0.0),
        circuit_breaker_triggered=cb_triggered,
        stops_triggered=stops,
        equity_curve=result.equity_curve,
    )


def gap_down_scenario(magnitude: float = 0.10) -> StressScenario:
    return StressScenario(name="gap_down", magnitude=magnitude, duration=1, recovery=0)


def slow_bleed_scenario(magnitude: float = 0.15, duration: int = 60) -> StressScenario:
    return StressScenario(name="slow_bleed", magnitude=magnitude, duration=duration, recovery=0)


def flash_crash_scenario(
    magnitude: float = 0.12, duration: int = 3, recovery: int = 10
) -> StressScenario:
    return StressScenario(
        name="flash_crash", magnitude=magnitude, duration=duration, recovery=recovery
    )


def vol_regime_shift_scenario(magnitude: float = 0.03, duration: int = 60) -> StressScenario:
    return StressScenario(
        name="vol_regime_shift", magnitude=magnitude, duration=duration, recovery=0
    )


def liquidity_crisis_scenario(
    spread_multiplier: float = 5.0, duration: int = 20
) -> StressScenario:
    return StressScenario(
        name="liquidity_crisis", magnitude=spread_multiplier, duration=duration, recovery=0
    )


def run_liquidity_crisis(
    config: PyramidConfig,
    adapter: BaseAdapter,
    spread_multiplier: float = 5.0,
    duration: int = 20,
    initial_equity: float = 2_000_000.0,
    start_price: float = 20000.0,
    base_slippage: float = 1.0,
) -> StressResult:
    """Run a liquidity crisis with degraded fill quality."""
    from src.core.types import ImpactParams
    params = ImpactParams(spread_bps=base_slippage * spread_multiplier * 100)
    fill_model = MarketImpactFillModel(params)
    scenario = liquidity_crisis_scenario(spread_multiplier, duration)
    return run_stress_test(
        scenario, config, adapter, fill_model, initial_equity, start_price
    )


def _generate_scenario_prices(scenario: StressScenario, start: float) -> npt.NDArray[np.float64]:
    name = scenario.name
    if name == "gap_down":
        return _gap_down_prices(start, scenario.magnitude)
    if name == "slow_bleed":
        return _slow_bleed_prices(start, scenario.magnitude, scenario.duration)
    if name == "flash_crash":
        return _flash_crash_prices(
            start, scenario.magnitude, scenario.duration, scenario.recovery
        )
    if name == "vol_regime_shift":
        return _vol_shift_prices(start, scenario.magnitude, scenario.duration)
    if name == "liquidity_crisis":
        return _slow_bleed_prices(start, 0.05, scenario.duration)
    return np.array([start, start])


def _gap_down_prices(start: float, magnitude: float) -> npt.NDArray[np.float64]:
    n_warmup = 20
    rng = np.random.default_rng(42)
    warmup = start * np.cumprod(1 + rng.normal(0.0002, 0.005, n_warmup))
    prices = np.empty(n_warmup + 2)
    prices[0] = start
    prices[1 : n_warmup + 1] = warmup
    prices[n_warmup + 1] = prices[n_warmup] * (1 - magnitude)
    return prices


def _slow_bleed_prices(start: float, magnitude: float, duration: int) -> npt.NDArray[np.float64]:
    n_warmup = 20
    rng = np.random.default_rng(42)
    warmup = start * np.cumprod(1 + rng.normal(0.0002, 0.005, n_warmup))
    daily_decline = magnitude / duration
    bleed = np.empty(duration)
    base = warmup[-1]
    for i in range(duration):
        noise = rng.normal(0, 0.002)
        base = base * (1 - daily_decline + noise)
        bleed[i] = base
    prices = np.empty(n_warmup + duration + 1)
    prices[0] = start
    prices[1 : n_warmup + 1] = warmup
    prices[n_warmup + 1 :] = bleed
    return prices


def _flash_crash_prices(
    start: float, magnitude: float, crash_bars: int, recovery_bars: int
) -> npt.NDArray[np.float64]:
    n_warmup = 20
    rng = np.random.default_rng(42)
    warmup = start * np.cumprod(1 + rng.normal(0.0002, 0.005, n_warmup))
    peak = warmup[-1]
    crash_step = magnitude / crash_bars
    crash = np.empty(crash_bars)
    p = peak
    for i in range(crash_bars):
        p = p * (1 - crash_step)
        crash[i] = p
    trough = crash[-1]
    recovery_target = peak * 0.95
    recovery = np.linspace(trough, recovery_target, recovery_bars)
    total = n_warmup + crash_bars + recovery_bars + 1
    prices = np.empty(total)
    prices[0] = start
    prices[1 : n_warmup + 1] = warmup
    prices[n_warmup + 1 : n_warmup + 1 + crash_bars] = crash
    prices[n_warmup + 1 + crash_bars :] = recovery
    return prices


def _vol_shift_prices(start: float, high_vol: float, duration: int) -> npt.NDArray[np.float64]:
    n_low = 30
    rng = np.random.default_rng(42)
    low_vol_returns = rng.normal(0.0001, 0.005, n_low)
    high_vol_returns = rng.normal(0.0, high_vol, duration)
    all_returns = np.concatenate([low_vol_returns, high_vol_returns])
    prices = np.empty(len(all_returns) + 1)
    prices[0] = start
    for i, r in enumerate(all_returns):
        prices[i + 1] = prices[i] * (1 + r)
    return prices


def _prices_to_bars(
    prices: npt.NDArray[np.float64],
) -> tuple[list[dict[str, Any]], list[datetime]]:
    bars: list[dict[str, Any]] = []
    timestamps: list[datetime] = []
    base_ts = datetime(2024, 1, 2, 9, 0, tzinfo=UTC)
    for i in range(1, len(prices)):
        p = float(prices[i])
        prev = float(prices[i - 1])
        bars.append({
            "price": p,
            "symbol": "TX",
            "daily_atr": abs(p - prev) * 2,
            "open": prev,
            "high": max(p, prev) * 1.001,
            "low": min(p, prev) * 0.999,
            "close": p,
        })
        timestamps.append(base_ts + timedelta(days=i))
    return bars, timestamps


def _prices_to_intraday_bars(
    prices: npt.NDArray[np.float64],
    bars_per_day: int = 71,
) -> tuple[list[dict[str, Any]], list[datetime]]:
    """Expand daily scenario prices into intraday bars for sub-daily strategies.

    Each daily transition prices[i-1] -> prices[i] is interpolated across
    *bars_per_day* sub-bars with small noise, preserving the macro scenario
    shape while providing enough bars for strategies that aggregate internally.
    """
    from src.simulator.monte_carlo import _generate_taifex_timestamps

    n_days = len(prices) - 1
    total_bars = n_days * bars_per_day
    timestamps = _generate_taifex_timestamps(total_bars)
    rng = np.random.default_rng(42)

    bars: list[dict[str, Any]] = []
    for day_idx in range(n_days):
        day_open = float(prices[day_idx])
        day_close = float(prices[day_idx + 1])
        daily_atr = abs(day_close - day_open) * 2
        step = (day_close - day_open) / bars_per_day
        noise_std = max(abs(step) * 0.3, day_open * 0.0002)

        prev_p = day_open
        for bar_j in range(bars_per_day):
            target = day_open + step * (bar_j + 1)
            noise = rng.normal(0, noise_std) if bar_j < bars_per_day - 1 else 0.0
            p = target + noise
            o = prev_p
            h = max(o, p) * (1 + rng.uniform(0, 0.0005))
            l = min(o, p) * (1 - rng.uniform(0, 0.0005))  # noqa: E741
            bars.append({
                "price": p,
                "symbol": "TX",
                "daily_atr": daily_atr,
                "open": o,
                "high": h,
                "low": l,
                "close": p,
                "volume": float(rng.uniform(1000, 5000)),
            })
            prev_p = p

    return bars, timestamps[:len(bars)]
