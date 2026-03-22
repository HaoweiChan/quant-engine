"""Facade bridging MCP tool calls to existing simulator APIs.

All functions accept flat dicts and return JSON-serializable dicts.
"""
from __future__ import annotations

import importlib
from typing import Any

from src.core.types import PyramidConfig
from src.simulator.types import PRESETS, PathConfig

# ---------------------------------------------------------------------------
# Strategy factory resolution
# ---------------------------------------------------------------------------

_BUILTIN_FACTORIES: dict[str, tuple[str, str]] = {
    "pyramid": ("src.core.position_engine", "create_pyramid_engine"),
    "atr_mean_reversion": (
        "src.strategies.atr_mean_reversion",
        "create_atr_mean_reversion_engine",
    ),
}


def resolve_factory(strategy: str) -> Any:
    """Return a callable engine factory for the given strategy name.

    Supports:
    - Built-in names: "pyramid", "atr_mean_reversion"
    - Dynamic: "module.path:factory_name"
    """
    if strategy in _BUILTIN_FACTORIES:
        mod_path, fn_name = _BUILTIN_FACTORIES[strategy]
        mod = importlib.import_module(mod_path)
        return getattr(mod, fn_name)
    if ":" in strategy:
        mod_path, fn_name = strategy.rsplit(":", 1)
        mod = importlib.import_module(mod_path)
        return getattr(mod, fn_name)
    available = list(_BUILTIN_FACTORIES.keys())
    raise ValueError(f"Unknown strategy '{strategy}'. Available: {available}")


def _build_pyramid_config(params: dict[str, Any] | None) -> PyramidConfig:
    """Merge provided params over defaults to create a PyramidConfig."""
    defaults = _load_default_pyramid_params()
    if params:
        defaults.update(params)
    return PyramidConfig(**defaults)


def _load_default_pyramid_params() -> dict[str, Any]:
    """Load default pyramid params from configs/default.toml or fallback."""
    try:
        from src.strategies.param_loader import load_strategy_params
        loaded = load_strategy_params("default")
        if loaded:
            return dict(loaded)
    except Exception:
        pass
    return {
        "max_loss": 500_000,
        "max_levels": 4,
        "stop_atr_mult": 1.5,
        "trail_atr_mult": 3.0,
        "trail_lookback": 22,
        "margin_limit": 0.50,
        "kelly_fraction": 0.25,
        "entry_conf_threshold": 0.65,
        "add_trigger_atr": [4.0, 8.0, 12.0],
        "lot_schedule": [[3, 4], [2, 0], [1, 4], [1, 4]],
    }


def _get_adapter():  # type: ignore[no-untyped-def]
    """Create a TaifexAdapter for backtest use."""
    from src.adapters.taifex import TaifexAdapter
    return TaifexAdapter()


def _resolve_path_config(scenario: str) -> PathConfig:
    if scenario not in PRESETS:
        available = list(PRESETS.keys())
        raise ValueError(f"Unknown scenario '{scenario}'. Available: {available}")
    return PRESETS[scenario]


# ---------------------------------------------------------------------------
# MCP facade functions
# ---------------------------------------------------------------------------

def _make_path_config(
    scenario: str,
    n_bars: int | None = None,
    timeframe: str = "daily",
) -> PathConfig:
    """Create a PathConfig, rescaling daily-calibrated params for intraday."""
    import math
    from src.simulator.monte_carlo import TAIFEX_BARS_PER_DAY
    base = _resolve_path_config(scenario)
    is_intraday = timeframe in ("intraday", "1m")
    bpd = TAIFEX_BARS_PER_DAY  # 1050
    effective_n = n_bars if n_bars is not None else (bpd * 20 if is_intraday else base.n_bars)
    if not is_intraday:
        if n_bars is None:
            return base
        return PathConfig(
            drift=base.drift, volatility=base.volatility,
            garch_omega=base.garch_omega, garch_alpha=base.garch_alpha,
            garch_beta=base.garch_beta, student_t_df=base.student_t_df,
            jump_intensity=base.jump_intensity, jump_mean=base.jump_mean,
            jump_std=base.jump_std, ou_theta=base.ou_theta,
            ou_mu=base.ou_mu, ou_sigma=base.ou_sigma,
            n_bars=effective_n, start_price=base.start_price, seed=base.seed,
        )
    sqrt_bpd = math.sqrt(bpd)
    vol_1m = base.volatility / sqrt_bpd
    # Daily-scale OU doesn't translate to 1-min bars (the OU level compounds
    # unrealistically when added to each bar's return). Intraday mean reversion
    # is handled by microstructure noise in _path_to_intraday_bars instead.
    return PathConfig(
        drift=base.drift / bpd,
        volatility=vol_1m,
        garch_omega=base.garch_omega / bpd,
        garch_alpha=base.garch_alpha,
        garch_beta=base.garch_beta,
        student_t_df=base.student_t_df,
        jump_intensity=base.jump_intensity / bpd,
        jump_mean=base.jump_mean,
        jump_std=base.jump_std,
        ou_theta=0.0,
        ou_mu=0.0,
        ou_sigma=0.0,
        n_bars=effective_n,
        start_price=base.start_price,
        seed=base.seed,
    )


def _bars_from_path(
    path, config: PathConfig, timeframe: str = "daily",
):
    """Generate bars with correct timestamps for the given timeframe."""
    if timeframe in ("intraday", "1m"):
        from src.simulator.monte_carlo import _path_to_intraday_bars
        return _path_to_intraday_bars(path, config)
    from src.simulator.monte_carlo import _path_to_bars
    return _path_to_bars(path, config)


def run_backtest_for_mcp(
    scenario: str,
    strategy_params: dict[str, Any] | None = None,
    strategy: str = "pyramid",
    n_bars: int | None = None,
    timeframe: str = "daily",
) -> dict[str, Any]:
    """Run a single backtest on synthetic data."""
    from src.simulator.backtester import BacktestRunner
    from src.simulator.price_gen import generate_paths

    path_config = _make_path_config(scenario, n_bars, timeframe)
    factory = resolve_factory(strategy)
    adapter = _get_adapter()

    if strategy == "pyramid":
        config = _build_pyramid_config(strategy_params)
        runner = BacktestRunner(config, adapter)
    else:
        merged = dict(strategy_params or {})
        if "max_loss" not in merged:
            merged["max_loss"] = 500_000
        engine = factory(**merged)
        runner = BacktestRunner(lambda: engine, adapter)

    paths = generate_paths(1, path_config)
    bars, timestamps = _bars_from_path(paths[0], path_config, timeframe)

    result = runner.run(bars, timestamps=timestamps)
    return {
        "scenario": scenario,
        "strategy": strategy,
        "n_bars": len(bars),
        "timeframe": timeframe,
        "metrics": result.metrics,
        "trade_count": len([f for f in result.trade_log if f.side == "buy"]),
        "equity_start": result.equity_curve[0],
        "equity_end": result.equity_curve[-1],
        "total_pnl": result.equity_curve[-1] - result.equity_curve[0],
    }


def run_monte_carlo_for_mcp(
    scenario: str,
    strategy_params: dict[str, Any] | None = None,
    strategy: str = "pyramid",
    n_paths: int = 200,
    n_bars: int | None = None,
    timeframe: str = "daily",
) -> dict[str, Any]:
    """Run Monte Carlo simulation with N paths."""
    from src.simulator.monte_carlo import run_monte_carlo

    clamped = min(n_paths, 1000)
    warning = f"n_paths clamped from {n_paths} to 1000" if n_paths > 1000 else None

    path_config = _make_path_config(scenario, n_bars, timeframe)
    adapter = _get_adapter()

    if strategy == "pyramid":
        config = _build_pyramid_config(strategy_params)
        mc_result = run_monte_carlo(clamped, config, adapter, path_config)
    else:
        merged = dict(strategy_params or {})
        if "max_loss" not in merged:
            merged["max_loss"] = 500_000
        mc_result = _run_mc_with_runner(strategy, merged, clamped, path_config, timeframe)

    result: dict[str, Any] = {
        "scenario": scenario,
        "strategy": strategy,
        "n_paths": clamped,
        "percentiles": mc_result.percentiles,
        "mean_pnl": (
            sum(mc_result.terminal_pnl_distribution)
            / len(mc_result.terminal_pnl_distribution)
            if mc_result.terminal_pnl_distribution
            else 0.0
        ),
        "win_rate": mc_result.win_rate,
        "ruin_probability": mc_result.ruin_probability,
        "max_drawdown_p50": sorted(mc_result.max_drawdown_distribution)[
            len(mc_result.max_drawdown_distribution) // 2
        ] if mc_result.max_drawdown_distribution else 0.0,
        "sharpe_p50": sorted(mc_result.sharpe_distribution)[
            len(mc_result.sharpe_distribution) // 2
        ] if mc_result.sharpe_distribution else 0.0,
    }
    if warning:
        result["warning"] = warning
    return result


def _mc_single_path(args: tuple) -> tuple[float, float, float]:
    """Worker function for parallel MC. Must be at module level for pickling."""
    strategy_name, strategy_params, path_array, path_config, timeframe = args
    from src.simulator.backtester import BacktestRunner
    from src.simulator.metrics import max_drawdown_pct, sharpe_ratio
    factory = resolve_factory(strategy_name)
    engine_factory = lambda: factory(**strategy_params)  # noqa: E731
    adapter = _get_adapter()
    runner = BacktestRunner(engine_factory, adapter)
    bars, timestamps = _bars_from_path(path_array, path_config, timeframe)
    result = runner.run(bars, timestamps=timestamps)
    pnl = result.equity_curve[-1] - result.equity_curve[0]
    return (pnl, max_drawdown_pct(result.equity_curve), sharpe_ratio(result.equity_curve))


def _run_mc_with_runner(
    strategy_name: str,
    strategy_params: dict[str, Any],
    n_paths: int,
    path_config: PathConfig,
    timeframe: str = "daily",
) -> Any:
    """Run MC for non-pyramid strategies, using multiprocessing for intraday."""
    import os

    import numpy as np

    from src.simulator.price_gen import generate_paths
    from src.simulator.types import MonteCarloResult

    paths = generate_paths(n_paths, path_config)
    use_mp = timeframe in ("intraday", "1m") and n_paths > 1
    if use_mp:
        from concurrent.futures import ProcessPoolExecutor
        workers = min(n_paths, os.cpu_count() or 4)
        work_items = [
            (strategy_name, strategy_params, path, path_config, timeframe)
            for path in paths
        ]
        with ProcessPoolExecutor(max_workers=workers) as pool:
            results_list = list(pool.map(_mc_single_path, work_items))
    else:
        from src.simulator.backtester import BacktestRunner
        from src.simulator.metrics import max_drawdown_pct, sharpe_ratio
        factory = resolve_factory(strategy_name)
        engine_factory = lambda: factory(**strategy_params)  # noqa: E731
        adapter = _get_adapter()
        runner = BacktestRunner(engine_factory, adapter)
        results_list = []
        for path in paths:
            bars, timestamps = _bars_from_path(path, path_config, timeframe)
            result = runner.run(bars, timestamps=timestamps)
            pnl = result.equity_curve[-1] - result.equity_curve[0]
            results_list.append((pnl, max_drawdown_pct(result.equity_curve), sharpe_ratio(result.equity_curve)))

    terminal_pnls = [r[0] for r in results_list]
    max_dds = [r[1] for r in results_list]
    sharpes = [r[2] for r in results_list]
    pnl_arr = np.array(terminal_pnls)
    percentiles = {
        "P5": float(np.percentile(pnl_arr, 5)),
        "P25": float(np.percentile(pnl_arr, 25)),
        "P50": float(np.percentile(pnl_arr, 50)),
        "P75": float(np.percentile(pnl_arr, 75)),
        "P95": float(np.percentile(pnl_arr, 95)),
    }
    wr = float(np.mean(pnl_arr > 0))
    ruin_count = sum(1 for p in terminal_pnls if p < -1_000_000)
    ruin_prob = ruin_count / n_paths if n_paths > 0 else 0.0

    return MonteCarloResult(
        terminal_pnl_distribution=terminal_pnls,
        percentiles=percentiles,
        win_rate=wr,
        max_drawdown_distribution=max_dds,
        sharpe_distribution=sharpes,
        ruin_probability=ruin_prob,
    )


def run_sweep_for_mcp(
    base_params: dict[str, Any],
    sweep_params: dict[str, Any],
    strategy: str = "pyramid",
    n_samples: int | None = None,
    metric: str = "sharpe",
    scenario: str = "strong_bull",
    n_bars: int | None = None,
    timeframe: str = "daily",
) -> dict[str, Any]:
    """Run parameter sweep (grid or random search)."""
    if len(sweep_params) > 3:
        return {
            "error": (
                f"Too many sweep parameters ({len(sweep_params)}). "
                "Maximum 3 allowed to avoid overfitting. "
                "Fix the most important 1-2 parameters and sweep the rest."
            )
        }

    from src.simulator.price_gen import generate_paths
    from src.simulator.strategy_optimizer import StrategyOptimizer

    path_config = _make_path_config(scenario, n_bars, timeframe)
    paths = generate_paths(1, path_config)
    bars, timestamps = _bars_from_path(paths[0], path_config, timeframe)
    adapter = _get_adapter()
    factory = resolve_factory(strategy)
    optimizer = StrategyOptimizer(adapter)

    if n_samples is not None:
        # Random search with continuous bounds
        param_bounds = {}
        for k, v in sweep_params.items():
            if isinstance(v, (list, tuple)) and len(v) == 2:
                param_bounds[k] = (float(v[0]), float(v[1]))
            else:
                return {"error": f"For random search, sweep_params['{k}'] must be [min, max]"}
        result = optimizer.random_search(
            engine_factory=lambda **p: factory(**{**base_params, **p}),
            param_bounds=param_bounds,
            bars=bars,
            timestamps=timestamps,
            n_trials=n_samples,
            objective=metric,
        )
    else:
        # Grid search
        param_grid = {}
        for k, v in sweep_params.items():
            if isinstance(v, list):
                param_grid[k] = v
            else:
                return {"error": f"For grid search, sweep_params['{k}'] must be a list of values"}
        result = optimizer.grid_search(
            engine_factory=lambda **p: factory(**{**base_params, **p}),
            param_grid=param_grid,
            bars=bars,
            timestamps=timestamps,
            objective=metric,
        )

    trials_data = result.trials.to_dicts() if len(result.trials) > 0 else []
    return {
        "scenario": scenario,
        "strategy": strategy,
        "metric": metric,
        "best_params": result.best_params,
        "best_is_metrics": result.best_is_result.metrics,
        "best_oos_metrics": result.best_oos_result.metrics if result.best_oos_result else None,
        "n_trials": len(trials_data),
        "top_5": trials_data[:5],
        "warnings": result.warnings,
    }


def run_stress_for_mcp(
    scenarios: list[str] | None = None,
    strategy_params: dict[str, Any] | None = None,
    strategy: str = "pyramid",
) -> dict[str, Any]:
    """Run stress test scenarios."""
    from src.simulator.stress import (
        _generate_scenario_prices,
        _prices_to_bars,
        flash_crash_scenario,
        gap_down_scenario,
        liquidity_crisis_scenario,
        run_stress_test,
        slow_bleed_scenario,
        vol_regime_shift_scenario,
    )

    all_scenarios = {
        "gap_down": gap_down_scenario,
        "slow_bleed": slow_bleed_scenario,
        "flash_crash": flash_crash_scenario,
        "vol_regime_shift": vol_regime_shift_scenario,
        "liquidity_crisis": liquidity_crisis_scenario,
    }

    names = scenarios or list(all_scenarios.keys())
    invalid = [n for n in names if n not in all_scenarios]
    if invalid:
        return {"error": f"Unknown scenarios: {invalid}. Available: {list(all_scenarios.keys())}"}

    adapter = _get_adapter()
    results = []

    for name in names:
        scenario_obj = all_scenarios[name]()
        if strategy == "pyramid":
            config = _build_pyramid_config(strategy_params)
            stress_result = run_stress_test(scenario_obj, config, adapter)
        else:
            from src.simulator.backtester import BacktestRunner
            factory = resolve_factory(strategy)
            merged = dict(strategy_params or {})
            if "max_loss" not in merged:
                merged["max_loss"] = 500_000
            engine_factory = lambda: factory(**merged)  # noqa: E731
            runner = BacktestRunner(engine_factory, adapter)
            prices = _generate_scenario_prices(scenario_obj, 20000.0)
            bars, timestamps = _prices_to_bars(prices)
            result = runner.run(bars, timestamps=timestamps)
            cb_triggered = any(
                f.reason == "circuit_breaker" for f in result.trade_log
            )
            stops = [
                f.reason for f in result.trade_log
                if "stop" in f.reason.lower()
            ]
            from src.simulator.types import StressResult
            stress_result = StressResult(
                scenario_name=scenario_obj.name,
                final_pnl=result.equity_curve[-1] - result.equity_curve[0],
                max_drawdown=result.metrics.get("max_drawdown_pct", 0.0),
                circuit_breaker_triggered=cb_triggered,
                stops_triggered=stops,
                equity_curve=result.equity_curve,
            )
        results.append({
            "scenario": stress_result.scenario_name,
            "final_pnl": stress_result.final_pnl,
            "max_drawdown": stress_result.max_drawdown,
            "circuit_breaker_triggered": stress_result.circuit_breaker_triggered,
            "stops_triggered": stress_result.stops_triggered,
        })

    return {"strategy": strategy, "results": results}


def get_strategy_parameter_schema(strategy: str = "pyramid") -> dict[str, Any]:
    """Return parameter schema with current values, types, and ranges."""
    if strategy == "pyramid":
        return _pyramid_schema()
    if strategy == "atr_mean_reversion":
        return _atr_mr_schema()
    return {"error": f"No schema available for strategy '{strategy}'"}


def _pyramid_schema() -> dict[str, Any]:
    defaults = _load_default_pyramid_params()
    schema: dict[str, Any] = {
        "strategy": "pyramid",
        "parameters": {
            "max_loss": {
                "current": defaults.get("max_loss", 500_000),
                "type": "float",
                "description": "Maximum dollar loss before engine halts. DO NOT CHANGE.",
            },
            "max_levels": {
                "current": defaults.get("max_levels", 4),
                "type": "int",
                "min": 1, "max": 8,
                "description": "Maximum pyramid levels.",
            },
            "stop_atr_mult": {
                "current": defaults.get("stop_atr_mult", 1.5),
                "type": "float",
                "min": 0.5, "max": 4.0,
                "description": "ATR multiplier for initial stop distance.",
            },
            "trail_atr_mult": {
                "current": defaults.get("trail_atr_mult", 3.0),
                "type": "float",
                "min": 1.0, "max": 6.0,
                "description": "ATR multiplier for chandelier trailing stop.",
            },
            "trail_lookback": {
                "current": defaults.get("trail_lookback", 22),
                "type": "int",
                "min": 5, "max": 60,
                "description": "Lookback bars for trailing stop high/low.",
            },
            "margin_limit": {
                "current": defaults.get("margin_limit", 0.50),
                "type": "float",
                "description": "Margin utilization cap. DO NOT CHANGE.",
            },
            "kelly_fraction": {
                "current": defaults.get("kelly_fraction", 0.25),
                "type": "float",
                "min": 0.05, "max": 0.50,
                "description": "Kelly criterion fraction for position sizing.",
            },
            "entry_conf_threshold": {
                "current": defaults.get("entry_conf_threshold", 0.65),
                "type": "float",
                "min": 0.30, "max": 0.90,
                "description": "Minimum model confidence to enter a trade.",
            },
        },
        "scenarios": _scenario_descriptions(),
    }
    return schema


def _atr_mr_schema() -> dict[str, Any]:
    return {
        "strategy": "atr_mean_reversion",
        "parameters": {
            "max_loss": {
                "current": 500_000,
                "type": "float",
                "description": "Maximum dollar loss. DO NOT CHANGE.",
            },
            "lots": {"current": 1.0, "type": "float", "min": 0.5, "max": 10.0,
                      "description": "Number of lots per entry."},
            "bb_len": {"current": 40, "type": "int", "min": 5, "max": 60,
                        "description": "Bollinger Bands lookback length."},
            "bb_upper_mult": {"current": 3.0, "type": "float", "min": 1.0, "max": 4.0,
                               "description": "BB upper band std multiplier."},
            "bb_lower_mult": {"current": 1.0, "type": "float", "min": 0.5, "max": 4.0,
                               "description": "BB lower band std multiplier."},
            "rsi_len": {"current": 5, "type": "int", "min": 3, "max": 30,
                         "description": "RSI lookback period."},
            "atr_len": {"current": 14, "type": "int", "min": 5, "max": 30,
                         "description": "ATR calculation length."},
            "atr_sl_multi": {"current": 3.5, "type": "float", "min": 1.0, "max": 5.0,
                              "description": "ATR multiplier for stop loss."},
            "atr_tp_multi": {"current": 1.5, "type": "float", "min": 0.5, "max": 5.0,
                              "description": "ATR multiplier for take profit."},
            "trend_ma_len": {"current": 60, "type": "int", "min": 20, "max": 200,
                              "description": "Trend MA lookback for extreme-trend filter."},
            "rsi_oversold": {"current": 45.0, "type": "float", "min": 10.0, "max": 50.0,
                              "description": "RSI threshold for oversold (long entry)."},
            "rsi_overbought": {"current": 60.0, "type": "float", "min": 55.0, "max": 90.0,
                                "description": "RSI threshold for overbought (short entry)."},
        },
        "scenarios": _scenario_descriptions(),
        "recommended_timeframe": {
            "timeframe": "intraday",
            "bars_per_day": 1050,
            "presets": {
                "quick": {"n_bars": 21000, "note": "~1 month (20 trading days)"},
                "standard": {"n_bars": 63000, "note": "~3 months (60 trading days)"},
                "full_year": {"n_bars": 264600, "note": "~1 year (252 trading days)"},
            },
            "note": (
                "ATR Mean Reversion is a 1-min intraday strategy. "
                "TAIFEX has ~1050 1-min bars/day (day 09:00-13:15 + night 15:15-04:30). "
                "Use timeframe='intraday'. For Monte Carlo, use 'quick' preset "
                "for iteration and 'standard' for validation."
            ),
        },
    }


def _scenario_descriptions() -> dict[str, str]:
    return {
        "strong_bull": "Strong uptrend: drift=0.001, vol=0.015",
        "gradual_bull": "Slow steady climb: drift=0.0003, vol=0.01",
        "bull_with_correction": "Bull with jump-driven corrections",
        "sideways": "Range-bound with mean reversion",
        "bear": "Downtrend: drift=-0.0005, vol=0.02",
        "volatile_bull": "Bull with GARCH vol clustering: drift=0.0005, vol=0.03",
        "flash_crash": "Bull with rare large negative jumps",
    }
