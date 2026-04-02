"""Facade bridging MCP tool calls to existing simulator APIs.

All functions accept flat dicts and return JSON-serializable dicts.
"""

from __future__ import annotations

import importlib
from typing import Any

from src.simulator.types import PRESETS, PathConfig


def _compute_code_hash(slug: str) -> tuple[str | None, str | None]:
    """Compute strategy hash and code, returning None on FileNotFoundError."""
    try:
        from src.strategies.code_hash import compute_strategy_hash

        return compute_strategy_hash(slug)
    except FileNotFoundError:
        return (None, None)


# ---------------------------------------------------------------------------
# Strategy factory resolution
# ---------------------------------------------------------------------------


def resolve_factory(strategy: str) -> Any:
    """Return a callable engine factory for the given strategy name.

    Resolution order:
    1. Strategy registry (slug or alias)
    2. "module:factory" format (external strategies)
    3. Raise ValueError
    """
    from src.strategies.registry import get_all, get_info

    try:
        info = get_info(strategy)
        mod = importlib.import_module(info.module)
        return getattr(mod, info.factory)
    except KeyError:
        pass
    if ":" in strategy:
        mod_path, fn_name = strategy.rsplit(":", 1)
        mod = importlib.import_module(mod_path)
        return getattr(mod, fn_name)
    available = list(get_all().keys())
    raise ValueError(f"Unknown strategy '{strategy}'. Available: {available}")


def resolve_strategy_slug(strategy: str) -> str:
    """Convert any strategy identifier to its canonical registry slug.

    Handles: slug, legacy alias, module:factory format.
    Falls back to the raw string if resolution fails.
    """
    from src.strategies.registry import get_info

    try:
        info = get_info(strategy)
        return info.slug
    except (KeyError, AttributeError):
        pass
    if ":" in strategy:
        mod_part = strategy.split(":")[0]
        prefix = "src.strategies."
        if mod_part.startswith(prefix):
            return mod_part[len(prefix) :].replace(".", "/")
    return strategy



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
            drift=base.drift,
            volatility=base.volatility,
            garch_omega=base.garch_omega,
            garch_alpha=base.garch_alpha,
            garch_beta=base.garch_beta,
            student_t_df=base.student_t_df,
            jump_intensity=base.jump_intensity,
            jump_mean=base.jump_mean,
            jump_std=base.jump_std,
            ou_theta=base.ou_theta,
            ou_mu=base.ou_mu,
            ou_sigma=base.ou_sigma,
            n_bars=effective_n,
            start_price=base.start_price,
            seed=base.seed,
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
    path,
    config: PathConfig,
    timeframe: str = "daily",
):
    """Generate bars with correct timestamps for the given timeframe."""
    if timeframe in ("intraday", "1m"):
        from src.simulator.monte_carlo import _path_to_intraday_bars

        return _path_to_intraday_bars(path, config)
    from src.simulator.monte_carlo import _path_to_bars

    return _path_to_bars(path, config)


def _aggregate_bars(raw, bar_agg: int):
    """Aggregate 1-min OHLCVBar objects into N-min bars."""
    from src.data.db import OHLCVBar

    if bar_agg <= 1 or not raw:
        return raw
    bucket_secs = bar_agg * 60
    buckets: dict[int, list] = {}
    for b in raw:
        ts_epoch = int(b.timestamp.timestamp())
        key = ts_epoch // bucket_secs
        buckets.setdefault(key, []).append(b)
    aggregated = []
    for key in sorted(buckets):
        group = buckets[key]
        aggregated.append(OHLCVBar(
            symbol=group[0].symbol,
            timestamp=group[0].timestamp,
            open=group[0].open,
            high=max(b.high for b in group),
            low=min(b.low for b in group),
            close=group[-1].close,
            volume=sum(b.volume for b in group),
        ))
    return aggregated


def _build_runner(
    strategy: str,
    strategy_params: dict[str, Any] | None,
    periods_per_year: float = 252.0,
    fill_model=None,
    initial_equity: float = 2_000_000.0,
):
    """Build a BacktestRunner for any strategy. Single source of truth."""
    from src.simulator.backtester import BacktestRunner
    from src.core.types import ImpactParams
    from src.simulator.fill_model import MarketImpactFillModel

    factory = resolve_factory(strategy)
    adapter = _get_adapter()
    merged = dict(strategy_params or {})
    slippage_bps = float(merged.pop("slippage_bps", 0.0))
    commission_bps = float(merged.pop("commission_bps", 0.0))
    commission_fixed = float(merged.pop("commission_fixed_per_contract", 0.0))
    if fill_model is None:
        impact_params = ImpactParams(
            spread_bps=slippage_bps,
            commission_bps=commission_bps,
            commission_fixed_per_contract=commission_fixed,
        )
        fm = MarketImpactFillModel(params=impact_params)
    else:
        fm = fill_model
    merged.pop("bar_agg", None)
    if "max_loss" not in merged:
        merged["max_loss"] = 500_000
    engine_factory = lambda: factory(**merged)  # noqa: E731
    return BacktestRunner(
        engine_factory,
        adapter,
        fill_model=fm,
        initial_equity=initial_equity,
        periods_per_year=periods_per_year,
    )


def _format_backtest_result(
    result, *, label: str, strategy: str, n_bars: int, extra: dict | None = None
):
    """Format a BacktestResult into a JSON-serializable dict."""
    out = {
        "label": label,
        "strategy": strategy,
        "n_bars": n_bars,
        "metrics": result.metrics,
        "trade_count": int(result.metrics.get("trade_count", 0)),
        "equity_start": result.equity_curve[0],
        "equity_end": result.equity_curve[-1],
        "total_pnl": result.equity_curve[-1] - result.equity_curve[0],
    }
    if result.impact_report is not None:
        out["impact_report"] = {
            "naive_pnl": result.impact_report.naive_pnl,
            "realistic_pnl": result.impact_report.realistic_pnl,
            "pnl_ratio": result.impact_report.pnl_ratio,
            "total_market_impact": result.impact_report.total_market_impact,
            "total_spread_cost": result.impact_report.total_spread_cost,
            "total_commission_cost": result.impact_report.total_commission_cost,
            "avg_latency_ms": result.impact_report.avg_latency_ms,
            "partial_fill_count": result.impact_report.partial_fill_count,
        }
    if extra:
        out.update(extra)
    return out


def _extract_trade_pnls(trade_log) -> list[float]:
    """Pair entry/exit fills to compute per-trade PnL in price points * lots."""
    pnls: list[float] = []
    entry = None
    for fill in trade_log:
        if entry is None:
            entry = fill
        else:
            if fill.side != entry.side:
                diff = (fill.fill_price - entry.fill_price) * entry.lots
                pnls.append(diff if entry.side == "buy" else -diff)
                entry = None
    return pnls


def _serialize_trade_log(trade_log) -> list[dict[str, Any]]:
    """Convert Fill objects to JSON-serializable dicts for the frontend."""
    return [
        {
            "timestamp": f.timestamp.isoformat()
            if hasattr(f.timestamp, "isoformat")
            else str(f.timestamp),
            "side": f.side,
            "price": f.fill_price,
            "lots": f.lots,
            "reason": f.reason,
        }
        for f in trade_log
    ]


def run_backtest_for_mcp(
    scenario: str,
    strategy_params: dict[str, Any] | None = None,
    strategy: str = "pyramid",
    n_bars: int | None = None,
    timeframe: str = "daily",
    initial_equity: float = 2_000_000.0,
) -> dict[str, Any]:
    """Run a single backtest on synthetic data."""
    from src.simulator.monte_carlo import TAIFEX_BARS_PER_DAY
    from src.simulator.price_gen import generate_paths

    resolved_slug = resolve_strategy_slug(strategy)
    clamped_params, param_warnings = ({} if strategy_params is None else strategy_params), []
    if strategy_params:
        from src.strategies.registry import validate_and_clamp

        clamped_params, param_warnings = validate_and_clamp(resolved_slug, strategy_params)

    path_config = _make_path_config(scenario, n_bars, timeframe)
    is_intraday = timeframe in ("intraday", "1m")
    ppy = TAIFEX_BARS_PER_DAY * 252.0 if is_intraday else 252.0
    runner = _build_runner(
        resolved_slug, clamped_params, periods_per_year=ppy, initial_equity=initial_equity
    )
    paths = generate_paths(1, path_config)
    bars, timestamps = _bars_from_path(paths[0], path_config, timeframe)
    result = runner.run(bars, timestamps=timestamps)
    out = _format_backtest_result(
        result,
        label=f"synthetic:{scenario}",
        strategy=strategy,
        n_bars=len(bars),
        extra={"scenario": scenario, "timeframe": timeframe},
    )
    out["data_source"] = "synthetic"
    out["source_label"] = f"synthetic:{scenario}"
    out["termination_eligible"] = False
    out["termination_block_reason"] = "synthetic_data"
    out["param_warnings"] = param_warnings
    strategy_hash, strategy_code = _compute_code_hash(resolved_slug)
    if strategy_hash is not None:
        out["strategy_hash"] = strategy_hash
    try:
        from src.strategies.param_registry import ParamRegistry

        registry = ParamRegistry()
        save_metrics = {**out.get("metrics", {}), "total_pnl": out.get("total_pnl")}
        run_id = registry.save_backtest_run(
            strategy=resolved_slug,
            symbol=f"synthetic:{scenario}",
            params=strategy_params or {},
            metrics=save_metrics,
            source="mcp",
            tool="run_backtest",
            initial_capital=initial_equity,
            strategy_hash=strategy_hash,
            strategy_code=strategy_code,
        )
        registry.close()
        if run_id > 0:
            out["run_id"] = run_id
    except Exception:
        pass
    return out


def run_backtest_realdata_for_mcp(
    symbol: str,
    start: str,
    end: str,
    strategy: str = "pyramid",
    strategy_params: dict[str, Any] | None = None,
    initial_equity: float = 2_000_000.0,
) -> dict[str, Any]:
    """Run a backtest on real historical data from the DB.

    This is the single source of truth for real-data backtests.
    Both the MCP tool and the dashboard call this function so results
    are guaranteed identical for the same inputs.
    """
    from datetime import datetime
    from pathlib import Path
    from statistics import mean as _mean

    import numpy as np

    db_path = Path(__file__).resolve().parent.parent.parent / "data" / "taifex_data.db"
    if not db_path.exists():
        return {"error": f"Database not found at {db_path}"}

    from src.data.db import Database

    db = Database(f"sqlite:///{db_path}")
    start_dt = datetime.fromisoformat(start)
    end_dt = datetime.fromisoformat(end)
    raw = db.get_ohlcv(symbol, start_dt, end_dt)
    if not raw:
        return {"error": f"No data for {symbol} in {start}–{end}"}

    resolved_slug = resolve_strategy_slug(strategy)
    clamped_params, param_warnings = ({} if strategy_params is None else strategy_params), []
    if strategy_params:
        from src.strategies.registry import validate_and_clamp

        clamped_params, param_warnings = validate_and_clamp(resolved_slug, strategy_params)

    bar_agg = int((strategy_params or {}).get("bar_agg", 1))

    # Compute true daily ATR from daily high-low ranges, not 1-min bar ranges
    _daily_hl: dict[str, tuple[float, float]] = {}
    for b in raw:
        d = b.timestamp.date() if hasattr(b.timestamp, "date") else str(b.timestamp)[:10]
        if d not in _daily_hl:
            _daily_hl[d] = (b.high, b.low)
        else:
            prev = _daily_hl[d]
            _daily_hl[d] = (max(prev[0], b.high), min(prev[1], b.low))
    daily_ranges = [hi - lo for hi, lo in _daily_hl.values() if hi > lo]
    daily_atr = _mean(daily_ranges) if daily_ranges else _mean(b.high - b.low for b in raw)

    # Aggregate 1-min bars into N-min bars when bar_agg > 1
    if bar_agg > 1:
        raw = _aggregate_bars(raw, bar_agg)

    trading_days = len(_daily_hl)
    bars_per_day = len(raw) / max(trading_days, 1)
    periods_per_year = bars_per_day * 252 if bars_per_day > 10 else 252.0
    runner = _build_runner(
        resolved_slug,
        clamped_params,
        periods_per_year=periods_per_year,
        initial_equity=initial_equity,
    )

    bars = [
        {
            "symbol": symbol,
            "price": b.close,
            "open": b.open,
            "high": b.high,
            "low": b.low,
            "close": b.close,
            "volume": float(b.volume),
            "daily_atr": daily_atr,
            "timestamp": b.timestamp,
        }
        for b in raw
    ]
    timestamps = [b.timestamp for b in raw]
    result = runner.run(bars, timestamps=timestamps)

    eq = np.array(result.equity_curve)
    strat_returns = np.diff(eq) / eq[:-1] if len(eq) > 1 else np.array([0.0])
    strat_returns = strat_returns[np.isfinite(strat_returns)]
    closes = np.array([b.close for b in raw], dtype=float)
    bnh_returns = np.diff(closes) / closes[:-1] if len(closes) > 1 else np.array([0.0])
    bnh_eq = initial_equity * np.cumprod(np.concatenate([[1.0], 1 + bnh_returns]))

    # Aggregate per-bar equity to true daily returns (last equity per date)
    daily_eq: dict[str, float] = {}
    for ts_str, e in zip(timestamps, eq):
        day = ts_str[:10] if isinstance(ts_str, str) else str(ts_str)[:10]
        daily_eq[day] = e
    daily_eq_arr = np.array(list(daily_eq.values()))
    true_daily_returns = (
        np.diff(daily_eq_arr) / daily_eq_arr[:-1]
        if len(daily_eq_arr) > 1
        else np.array([0.0])
    )
    true_daily_returns = true_daily_returns[np.isfinite(true_daily_returns)]

    base = _format_backtest_result(
        result,
        label=f"real:{symbol}:{start}:{end}",
        strategy=strategy,
        n_bars=len(bars),
        extra={"symbol": symbol, "start": start, "end": end},
    )
    base["data_source"] = "real"
    base["source_label"] = f"real:{symbol}:{start}:{end}"
    base["termination_eligible"] = True
    strat_total_ret = (eq[-1] - eq[0]) / eq[0] if len(eq) > 1 and eq[0] > 0 else 0.0
    bnh_total_ret = (bnh_eq[-1] - bnh_eq[0]) / bnh_eq[0] if len(bnh_eq) > 1 and bnh_eq[0] > 0 else 0.0
    alpha = float(strat_total_ret - bnh_total_ret)
    base["metrics"]["alpha"] = alpha
    base["daily_returns"] = true_daily_returns
    base["equity_curve"] = result.equity_curve
    base["bnh_returns"] = bnh_returns
    base["bnh_equity"] = bnh_eq.tolist()
    base["bars_count"] = len(bars)
    base["trade_pnls"] = _extract_trade_pnls(result.trade_log)
    base["trade_signals"] = _serialize_trade_log(result.trade_log)
    base["timeframe_minutes"] = bar_agg
    ts_epochs = [
        int(ts.timestamp()) if hasattr(ts, "timestamp") else int(ts)
        for ts in timestamps
    ]
    # equity_curve has n+1 values (initial + per-bar); prepend a ts 1s before first bar
    if ts_epochs:
        ts_epochs = [ts_epochs[0] - 1] + ts_epochs
    base["equity_timestamps"] = ts_epochs
    base["param_warnings"] = param_warnings
    strategy_hash, strategy_code = _compute_code_hash(resolved_slug)
    if strategy_hash is not None:
        base["strategy_hash"] = strategy_hash
    try:
        from src.strategies.param_registry import ParamRegistry

        registry = ParamRegistry()
        save_metrics = {**base.get("metrics", {}), "total_pnl": base.get("total_pnl"), "alpha": alpha}
        run_id = registry.save_backtest_run(
            strategy=resolved_slug,
            symbol=symbol,
            params=strategy_params or {},
            metrics=save_metrics,
            source="mcp",
            tool="run_backtest_realdata",
            start=start,
            end=end,
            timeframe=f"{bar_agg}min",
            initial_capital=initial_equity,
            strategy_hash=strategy_hash,
            strategy_code=strategy_code,
        )
        registry.close()
        if run_id > 0:
            base["run_id"] = run_id
    except Exception:
        pass
    return base


def run_monte_carlo_for_mcp(
    scenario: str,
    strategy_params: dict[str, Any] | None = None,
    strategy: str = "pyramid",
    n_paths: int = 200,
    n_bars: int | None = None,
    timeframe: str = "daily",
) -> dict[str, Any]:
    """Run Monte Carlo simulation with N paths."""
    clamped = min(n_paths, 1000)
    warning = f"n_paths clamped from {n_paths} to 1000" if n_paths > 1000 else None

    resolved_slug = resolve_strategy_slug(strategy)
    clamped_params, param_warnings = ({} if strategy_params is None else strategy_params), []
    if strategy_params:
        from src.strategies.registry import validate_and_clamp

        clamped_params, param_warnings = validate_and_clamp(resolved_slug, strategy_params)

    path_config = _make_path_config(scenario, n_bars, timeframe)

    merged = dict(clamped_params)
    if "max_loss" not in merged:
        merged["max_loss"] = 500_000
    mc_result = _run_mc_with_runner(resolved_slug, merged, clamped, path_config, timeframe)

    result: dict[str, Any] = {
        "scenario": scenario,
        "strategy": strategy,
        "n_paths": clamped,
        "data_source": "synthetic",
        "source_label": f"synthetic:{scenario}",
        "percentiles": mc_result.percentiles,
        "mean_pnl": (
            sum(mc_result.terminal_pnl_distribution) / len(mc_result.terminal_pnl_distribution)
            if mc_result.terminal_pnl_distribution
            else 0.0
        ),
        "win_rate": mc_result.win_rate,
        "ruin_probability": mc_result.ruin_probability,
        "max_drawdown_p50": sorted(mc_result.max_drawdown_distribution)[
            len(mc_result.max_drawdown_distribution) // 2
        ]
        if mc_result.max_drawdown_distribution
        else 0.0,
        "sharpe_p50": sorted(mc_result.sharpe_distribution)[len(mc_result.sharpe_distribution) // 2]
        if mc_result.sharpe_distribution
        else 0.0,
    }
    if warning:
        result["warning"] = warning
    result["termination_eligible"] = False
    result["termination_block_reason"] = "synthetic_data"
    result["param_warnings"] = param_warnings
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
            (strategy_name, strategy_params, path, path_config, timeframe) for path in paths
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
            results_list.append(
                (pnl, max_drawdown_pct(result.equity_curve), sharpe_ratio(result.equity_curve))
            )

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
    metric: str = "sortino",
    mode: str = "production_intent",
    scenario: str = "strong_bull",
    symbol: str | None = None,
    start: str | None = None,
    end: str | None = None,
    is_fraction: float = 0.8,
    min_trade_count: int = 100,
    min_expectancy: float = 0.0,
    min_oos_metric: float = 0.0,
    train_bars: int | None = None,
    test_bars: int | None = None,
    n_bars: int | None = None,
    timeframe: str = "daily",
    require_real_data: bool = True,
) -> dict[str, Any]:
    """Run parameter sweep (grid or random search)."""
    if mode not in {"research", "production_intent"}:
        return {"error": "mode must be 'research' or 'production_intent'"}
    if require_real_data and mode != "production_intent":
        return {
            "error": (
                "Real-data guard blocked synthetic optimization. "
                "Use mode='production_intent' with symbol/start/end, "
                "or explicitly set require_real_data=false for exploratory research only."
            )
        }
    if len(sweep_params) > 3:
        return {
            "error": (
                f"Too many sweep parameters ({len(sweep_params)}). "
                "Maximum 3 allowed to avoid overfitting. "
                "Fix the most important 1-2 parameters and sweep the rest."
            )
        }

    from datetime import datetime
    from pathlib import Path
    from statistics import mean as _mean

    from src.data.db import Database
    from src.simulator.price_gen import generate_paths
    from src.simulator.strategy_optimizer import StrategyOptimizer

    resolved_slug = resolve_strategy_slug(strategy)
    clamped_base, param_warnings = base_params, []
    from src.strategies.registry import validate_and_clamp

    clamped_base, param_warnings = validate_and_clamp(resolved_slug, base_params)

    if mode == "production_intent":
        if not (symbol and start and end):
            return {
                "error": (
                    "production_intent mode requires symbol, start, and end "
                    "for real-data evaluation"
                )
            }
        db_path = Path(__file__).resolve().parent.parent.parent / "data" / "taifex_data.db"
        if not db_path.exists():
            return {"error": f"Database not found at {db_path}"}
        db = Database(f"sqlite:///{db_path}")
        raw = db.get_ohlcv(symbol, datetime.fromisoformat(start), datetime.fromisoformat(end))
        if not raw:
            return {"error": f"No data for {symbol} in {start}–{end}"}
        daily_ranges = [b.high - b.low for b in raw]
        daily_atr = _mean(daily_ranges) if daily_ranges else 0.0
        bars = [
            {
                "symbol": symbol,
                "price": b.close,
                "open": b.open,
                "high": b.high,
                "low": b.low,
                "close": b.close,
                "volume": float(b.volume),
                "daily_atr": daily_atr,
                "timestamp": b.timestamp,
            }
            for b in raw
        ]
        timestamps = [b.timestamp for b in raw]
        source_label = f"real:{symbol}:{start}:{end}"
    else:
        path_config = _make_path_config(scenario, n_bars, timeframe)
        paths = generate_paths(1, path_config)
        bars, timestamps = _bars_from_path(paths[0], path_config, timeframe)
        source_label = f"synthetic:{scenario}"
    adapter = _get_adapter()
    factory = resolve_factory(resolved_slug)
    optimizer = StrategyOptimizer(
        adapter,
        mode=mode,
        min_trade_count=min_trade_count,
        min_expectancy=min_expectancy,
        min_oos_objective=min_oos_metric,
    )
    walk_forward_summary: dict[str, Any] | None = None

    if n_samples is not None:
        # Random search with continuous bounds
        param_bounds = {}
        for k, v in sweep_params.items():
            if isinstance(v, (list, tuple)) and len(v) == 2:
                param_bounds[k] = (float(v[0]), float(v[1]))
            else:
                return {"error": f"For random search, sweep_params['{k}'] must be [min, max]"}
        result = optimizer.random_search(
            engine_factory=lambda **p: factory(**{**clamped_base, **p}),
            param_bounds=param_bounds,
            bars=bars,
            timestamps=timestamps,
            n_trials=n_samples,
            objective=metric,
            is_fraction=is_fraction,
        )
    else:
        # Grid search
        param_grid = {}
        for k, v in sweep_params.items():
            if isinstance(v, list):
                param_grid[k] = v
            else:
                return {"error": f"For grid search, sweep_params['{k}'] must be a list of values"}
        if mode == "production_intent":
            effective_train = train_bars or max(int(len(bars) * 0.6), 50)
            effective_test = test_bars or max(int(len(bars) * 0.2), 20)
            if effective_train + effective_test <= len(bars):
                wf = optimizer.walk_forward(
                    engine_factory=lambda **p: factory(**{**clamped_base, **p}),
                    param_grid=param_grid,
                    bars=bars,
                    timestamps=timestamps,
                    train_bars=effective_train,
                    test_bars=effective_test,
                    objective=metric,
                )
                walk_forward_summary = {
                    "windows": len(wf.windows),
                    "efficiency": wf.efficiency,
                    "combined_oos_metrics": wf.combined_oos_metrics,
                }
        result = optimizer.grid_search(
            engine_factory=lambda **p: factory(**{**clamped_base, **p}),
            param_grid=param_grid,
            bars=bars,
            timestamps=timestamps,
            objective=metric,
            is_fraction=is_fraction,
        )

    trials_data = result.trials.to_dicts() if len(result.trials) > 0 else []
    # Persist to param registry
    run_id = None
    pareto_candidates = []
    strategy_hash, strategy_code = _compute_code_hash(resolved_slug)
    try:
        from src.strategies.param_registry import ParamRegistry

        registry = ParamRegistry()
        search = "random" if n_samples is not None else "grid"
        run_id = registry.save_run(
            result=result,
            strategy=resolved_slug,
            symbol=source_label,
            objective=metric,
            search_type=search,
            source="mcp",
            initial_capital=2_000_000.0,
            strategy_hash=strategy_hash,
            strategy_code=strategy_code,
        )
        pareto = registry.get_pareto_frontier(run_id)
        pareto_candidates = [
            {"params": p["params"], "sharpe": p.get("sharpe"), "calmar": p.get("calmar")}
            for p in pareto
        ]
        registry.close()
    except Exception:
        pass
    out: dict[str, Any] = {
        "scenario": scenario,
        "strategy": strategy,
        "metric": metric,
        "mode": mode,
        "data_source": "real" if mode == "production_intent" else "synthetic",
        "source_label": source_label,
        "termination_eligible": mode == "production_intent",
        "real_data_guard": {
            "require_real_data": require_real_data,
            "passed": mode == "production_intent",
        },
        "objective_direction": result.objective_direction,
        "disqualified_trials": result.disqualified_trials,
        "gate_results": result.gate_results,
        "gate_details": result.gate_details,
        "promotable": result.promotable if mode == "production_intent" else False,
        "auto_activation_disabled": True,
        "best_params": result.best_params,
        "best_is_metrics": result.best_is_result.metrics,
        "best_oos_metrics": result.best_oos_result.metrics if result.best_oos_result else None,
        "n_trials": len(trials_data),
        "top_5": trials_data[:5],
        "warnings": result.warnings,
        "param_warnings": param_warnings,
    }
    if mode != "production_intent":
        existing_warnings = out.get("warnings") or []
        out["warnings"] = [*existing_warnings, "Synthetic/research sweep is non-promotable."]
        out["promotion_blocked_reason"] = "synthetic_data"
        out["termination_block_reason"] = "synthetic_data"
    if run_id is not None:
        out["run_id"] = run_id
        out["pareto_candidates"] = pareto_candidates
    if walk_forward_summary is not None:
        out["walk_forward"] = walk_forward_summary
    if mode == "production_intent":
        out["evaluation_data"] = {"symbol": symbol, "start": start, "end": end}
    return out


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

    resolved_slug = resolve_strategy_slug(strategy)
    clamped_params, param_warnings = ({} if strategy_params is None else strategy_params), []
    if strategy_params:
        from src.strategies.registry import validate_and_clamp

        clamped_params, param_warnings = validate_and_clamp(resolved_slug, strategy_params)

    adapter = _get_adapter()
    results = []

    for name in names:
        scenario_obj = all_scenarios[name]()
        from src.simulator.backtester import BacktestRunner

        factory = resolve_factory(resolved_slug)
        merged = dict(clamped_params)
        if "max_loss" not in merged:
            merged["max_loss"] = 500_000
        engine_factory = lambda: factory(**merged)  # noqa: E731
        runner = BacktestRunner(engine_factory, adapter)
        prices = _generate_scenario_prices(scenario_obj, 20000.0)
        bars, timestamps = _prices_to_bars(prices)
        result = runner.run(bars, timestamps=timestamps)
        cb_triggered = any(f.reason == "circuit_breaker" for f in result.trade_log)
        stops = [f.reason for f in result.trade_log if "stop" in f.reason.lower()]
        from src.simulator.types import StressResult

        stress_result = StressResult(
            scenario_name=scenario_obj.name,
            final_pnl=result.equity_curve[-1] - result.equity_curve[0],
            max_drawdown=result.metrics.get("max_drawdown_pct", 0.0),
            circuit_breaker_triggered=cb_triggered,
            stops_triggered=stops,
            equity_curve=result.equity_curve,
        )
        results.append(
            {
                "scenario": stress_result.scenario_name,
                "final_pnl": stress_result.final_pnl,
                "max_drawdown": stress_result.max_drawdown,
                "circuit_breaker_triggered": stress_result.circuit_breaker_triggered,
                "stops_triggered": stress_result.stops_triggered,
            }
        )

    return {"strategy": strategy, "results": results, "param_warnings": param_warnings}


def get_strategy_parameter_schema(
    strategy: str = "daily/trend_following/pyramid_wrapper",
) -> dict[str, Any]:
    """Return parameter schema with current values, types, and ranges."""
    from src.strategies.registry import get_schema

    try:
        schema = get_schema(strategy)
    except KeyError:
        return {"error": f"No schema available for strategy '{strategy}'"}
    schema["scenarios"] = _scenario_descriptions()
    # Inject max_loss as a fixed param (not from PARAM_SCHEMA)
    schema["parameters"].setdefault(
        "max_loss",
        {
            "current": 500_000,
            "type": "float",
            "description": "Maximum dollar loss before engine halts. DO NOT CHANGE.",
        },
    )
    return schema


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


# ---------------------------------------------------------------------------
# Param registry facade functions (for MCP tools)
# ---------------------------------------------------------------------------


def get_run_history_for_mcp(
    strategy: str | None = None,
    limit: int = 10,
) -> dict[str, Any]:
    """Query persisted optimization runs from the registry."""
    from src.strategies.param_registry import ParamRegistry

    registry = ParamRegistry()
    if strategy:
        runs = registry.get_run_history(strategy, limit=limit)
    else:
        # Cross-strategy: query each known strategy
        from src.strategies.registry import get_all

        runs = []
        for slug in get_all():
            runs.extend(registry.get_run_history(slug, limit=limit))
        runs.sort(key=lambda r: r["run_at"], reverse=True)
        runs = runs[:limit]
    registry.close()
    return {"runs": runs, "count": len(runs)}


def activate_candidate_for_mcp(candidate_id: int) -> dict[str, Any]:
    """Activate a parameter candidate for production use."""
    from src.strategies.param_registry import ParamRegistry

    registry = ParamRegistry()
    try:
        registry.activate(candidate_id)
    except ValueError as e:
        registry.close()
        return {"error": str(e)}
    detail = registry._conn.execute(
        """SELECT c.strategy, c.params, c.label, c.activated_at,
                  r.objective, r.tag
           FROM param_candidates c
           JOIN param_runs r ON r.id = c.run_id
           WHERE c.id = ?""",
        (candidate_id,),
    ).fetchone()
    registry.close()
    import json

    return {
        "status": "activated",
        "candidate_id": candidate_id,
        "strategy": detail["strategy"],
        "params": json.loads(detail["params"]),
        "label": detail["label"],
        "activated_at": detail["activated_at"],
        "objective": detail["objective"],
        "tag": detail["tag"],
    }


def get_active_params_for_mcp(strategy: str = "pyramid") -> dict[str, Any]:
    """Return currently active optimized params, or schema defaults."""
    from src.strategies.param_registry import ParamRegistry

    registry = ParamRegistry()
    detail = registry.get_active_detail(strategy)
    registry.close()
    if detail:
        return {**detail, "source": "registry"}
    # Fallback to schema defaults
    slug = "pyramid_wrapper" if strategy == "pyramid" else strategy
    try:
        from src.strategies.registry import get_defaults

        defaults = get_defaults(slug)
        return {
            "params": defaults,
            "source": "defaults",
            "note": "No optimized params found; returning PARAM_SCHEMA defaults.",
        }
    except KeyError:
        return {"error": f"Unknown strategy '{strategy}'"}
