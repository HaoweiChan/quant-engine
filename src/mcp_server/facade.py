"""Facade bridging MCP tool calls to existing simulator APIs.

All functions accept flat dicts and return JSON-serializable dicts.
"""

from __future__ import annotations

import importlib
import os
from typing import Any

from src.simulator.types import PRESETS, PathConfig

# Factory cache: avoids importlib.reload() on every MC worker / sweep trial.
# Set QUANT_RELOAD_STRATEGY=1 to force reload (useful during dev).
_factory_cache: dict[str, Any] = {}
_RELOAD_STRATEGY = os.environ.get("QUANT_RELOAD_STRATEGY", "0") == "1"


def _compute_force_flat_indices(timestamps: list) -> set[int]:
    """Compute the set of bar indices where force-flat (session close) should occur.

    Adds an index whenever the session ID changes between consecutive bars, and
    always adds the final bar index so the last open position is closed.
    """
    from src.data.session_utils import session_id as _session_id

    indices: set[int] = set()
    for idx in range(len(timestamps) - 1):
        curr_sid = _session_id(timestamps[idx])
        next_sid = _session_id(timestamps[idx + 1])
        if curr_sid != next_sid and curr_sid != "CLOSED":
            indices.add(idx)
    indices.add(len(timestamps) - 1)
    return indices


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

    Results are cached per-process to avoid expensive importlib.reload()
    on every MC path / sweep trial.  Set QUANT_RELOAD_STRATEGY=1 to bypass.
    """
    if strategy in _factory_cache and not _RELOAD_STRATEGY:
        return _factory_cache[strategy]

    from src.strategies.registry import get_all, get_info

    result = None
    try:
        info = get_info(strategy)
        mod = importlib.import_module(info.module)
        if _RELOAD_STRATEGY:
            importlib.reload(mod)
        result = getattr(mod, info.factory)
    except KeyError:
        pass
    if result is None and ":" in strategy:
        mod_path, fn_name = strategy.rsplit(":", 1)
        mod = importlib.import_module(mod_path)
        if _RELOAD_STRATEGY:
            importlib.reload(mod)
        result = getattr(mod, fn_name)
    if result is None:
        available = list(get_all().keys())
        raise ValueError(f"Unknown strategy '{strategy}'. Available: {available}")
    _factory_cache[strategy] = result
    return result


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


def _bar_agg_to_label(bar_agg: int) -> str:
    """Map bar aggregation minutes to a human-readable timeframe label."""
    return {1: "1m", 5: "5m", 15: "15m", 60: "1h", 1440: "1D"}.get(bar_agg, f"{bar_agg}m")


def _default_fill_model(instrument: str = "TX"):
    """Create a MarketImpactFillModel with standard instrument costs."""
    from src.core.types import ImpactParams, get_instrument_cost_config
    from src.simulator.fill_model import MarketImpactFillModel

    cost_config = get_instrument_cost_config(instrument)
    return MarketImpactFillModel(params=ImpactParams(
        spread_bps=cost_config.slippage_bps,
        commission_bps=cost_config.commission_bps,
        commission_fixed_per_contract=cost_config.commission_per_contract,
    ))


def _build_runner(
    strategy: str,
    strategy_params: dict[str, Any] | None,
    periods_per_year: float = 252.0,
    fill_model=None,
    initial_equity: float = 2_000_000.0,
    instrument: str = "TX",
):
    """Build a BacktestRunner for any strategy. Single source of truth."""
    from src.simulator.backtester import BacktestRunner
    from src.core.types import ImpactParams, get_instrument_cost_config
    from src.simulator.fill_model import MarketImpactFillModel

    cost_config = get_instrument_cost_config(instrument)
    factory = resolve_factory(strategy)
    adapter = _get_adapter()
    merged = dict(strategy_params or {})
    # Use instrument defaults when caller doesn't provide explicit cost params
    has_explicit_slippage = "slippage_bps" in merged
    has_explicit_commission_bps = "commission_bps" in merged
    has_explicit_commission_fixed = "commission_fixed_per_contract" in merged
    slippage_bps = float(merged.pop("slippage_bps", cost_config.slippage_bps))
    commission_bps = float(merged.pop("commission_bps", cost_config.commission_bps))
    commission_fixed = float(merged.pop(
        "commission_fixed_per_contract", cost_config.commission_per_contract
    ))
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
    intraday: bool = False,
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

    # Auto-detect intraday mode from strategy metadata (slug prefix or StrategyTimeframe)
    if not intraday:
        from src.strategies.registry import is_intraday_strategy
        intraday = is_intraday_strategy(resolved_slug)

    clamped_params, param_warnings = ({} if strategy_params is None else strategy_params), []
    if strategy_params:
        from src.strategies.registry import validate_and_clamp

        clamped_params, param_warnings = validate_and_clamp(resolved_slug, strategy_params)

    from src.strategies.registry import get_bar_agg
    meta_bar_agg = get_bar_agg(resolved_slug)
    bar_agg = int((strategy_params or {}).get("bar_agg", meta_bar_agg))

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

    # Intraday mode: compute session boundaries for force-close
    force_flat_indices: set[int] | None = None
    if intraday and len(timestamps) > 1:
        force_flat_indices = _compute_force_flat_indices(timestamps)

    result = runner.run(bars, timestamps=timestamps, force_flat_indices=force_flat_indices)

    eq = np.array(result.equity_curve)
    strat_returns = np.diff(eq) / eq[:-1] if len(eq) > 1 else np.array([0.0])
    strat_returns = strat_returns[np.isfinite(strat_returns)]
    if intraday:
        # Intraday B&H at bar-level: within each session track equity as if
        # buying session open and holding; between sessions equity stays flat.
        # This produces len(raw)+1 values, matching strategy equity_curve.
        from src.data.session_utils import session_id as _sid

        bnh_eq_vals: list[float] = [initial_equity]
        session_start_equity = initial_equity
        session_open_price: float | None = None
        prev_sid: str | None = None
        for b in raw:
            sid = _sid(b.timestamp)
            if sid == "CLOSED":
                bnh_eq_vals.append(bnh_eq_vals[-1])
                continue
            if sid != prev_sid:
                # New session: lock in equity, record new open
                session_start_equity = bnh_eq_vals[-1]
                session_open_price = b.open
                prev_sid = sid
            if session_open_price and session_open_price > 0:
                bnh_eq_vals.append(
                    session_start_equity * (b.close / session_open_price)
                )
            else:
                bnh_eq_vals.append(bnh_eq_vals[-1])
        bnh_eq = np.array(bnh_eq_vals)
        bnh_returns = (
            np.diff(bnh_eq) / bnh_eq[:-1]
            if len(bnh_eq) > 1
            else np.array([0.0])
        )
        bnh_returns = bnh_returns[np.isfinite(bnh_returns)]
    else:
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

    # Leverage-adjusted alpha
    lots_held = getattr(result, "lots_held_per_bar", None)
    if lots_held and len(lots_held) > 0:
        avg_leverage = sum(lots_held) / len(lots_held)
        alpha_lev = float(strat_total_ret / max(avg_leverage, 1.0) - bnh_total_ret)
    else:
        avg_leverage = 1.0
        alpha_lev = alpha
    base["metrics"]["alpha_leverage_adjusted"] = alpha_lev
    base["metrics"]["avg_leverage"] = float(avg_leverage)

    # Benchmark Sortino
    bnh_downside = bnh_returns[bnh_returns < 0]
    if len(bnh_downside) > 0 and np.std(bnh_downside) > 0:
        bnh_sortino = float(np.mean(bnh_returns) / np.std(bnh_downside) * np.sqrt(periods_per_year))
    else:
        bnh_sortino = 0.0
    base["metrics"]["bnh_sortino"] = bnh_sortino
    base["daily_returns"] = true_daily_returns
    base["equity_curve"] = result.equity_curve
    base["bnh_returns"] = bnh_returns
    base["bnh_equity"] = bnh_eq.tolist()
    base["bars_count"] = len(bars)
    base["trade_pnls"] = _extract_trade_pnls(result.trade_log)
    base["trade_signals"] = _serialize_trade_log(result.trade_log)
    base["timeframe_minutes"] = bar_agg
    # Add human-readable timeframe label for correct display
    if bar_agg == 1:
        base["timeframe_label"] = "1m"
    elif bar_agg == 5:
        base["timeframe_label"] = "5m"
    elif bar_agg == 15:
        base["timeframe_label"] = "15m"
    elif bar_agg == 60:
        base["timeframe_label"] = "1h"
    elif bar_agg == 1440:
        base["timeframe_label"] = "1D"
    else:
        base["timeframe_label"] = f"{bar_agg}m"
    _ind_series = getattr(result, "indicator_series", {})
    if _ind_series:
        base["indicator_series"] = _ind_series
        base["indicator_meta"] = getattr(result, "indicator_meta", {})
    ts_epochs = [
        int(ts.timestamp()) if hasattr(ts, "timestamp") else int(ts)
        for ts in timestamps
    ]
    # equity_curve has n+1 values (initial + per-bar); prepend a ts 1s before first bar
    if ts_epochs:
        ts_epochs = [ts_epochs[0] - 1] + ts_epochs
    base["equity_timestamps"] = ts_epochs
    base["param_warnings"] = param_warnings
    base["intraday"] = intraday
    strategy_hash, strategy_code = _compute_code_hash(resolved_slug)
    if strategy_hash is not None:
        base["strategy_hash"] = strategy_hash
    try:
        from src.strategies.param_registry import ParamRegistry

        registry = ParamRegistry()
        save_metrics = {**base.get("metrics", {}), "total_pnl": base.get("total_pnl"), "alpha": alpha}
        # Build notes with actual applied costs (explicit or defaults) and params fingerprint
        from src.core.types import get_instrument_cost_config
        cost_config = get_instrument_cost_config(symbol)
        _sp = strategy_params or {}
        # Use explicit costs if provided, otherwise use instrument defaults
        _slip_bps = _sp.get("slippage_bps", cost_config.slippage_bps)
        _comm_fixed = _sp.get("commission_fixed_per_contract", cost_config.commission_per_contract)
        cost_note = f"sbps={_slip_bps}|cfix={_comm_fixed}"
        # Include a short hash of params so different params = different runs
        import hashlib, json as _json
        _p_str = _json.dumps(_sp, sort_keys=True)
        _p_hash = hashlib.md5(_p_str.encode()).hexdigest()[:8]
        cost_note = f"p={_p_hash}|{cost_note}"
        # Map bar_agg to readable timeframe for database storage
        tf_label = _bar_agg_to_label(bar_agg)

        run_id = registry.save_backtest_run(
            strategy=resolved_slug,
            symbol=symbol,
            params=strategy_params or {},
            metrics=save_metrics,
            source="mcp",
            tool="run_backtest_realdata",
            start=start,
            end=end,
            timeframe=f"{tf_label}{'|intraday' if intraday else ''}",
            notes=cost_note,
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
    """Worker function for parallel MC. Must be at module level for pickling.

    Accepts a seed index instead of a pre-generated path array so that each
    worker generates its own path — avoids serializing large numpy arrays
    through the multiprocessing boundary.
    """
    strategy_name, strategy_params, seed_idx, path_config, timeframe = args
    from src.simulator.backtester import BacktestRunner
    from src.simulator.metrics import max_drawdown_pct, sharpe_ratio
    from src.simulator.price_gen import generate_path

    per_path_config = PathConfig(
        drift=path_config.drift, volatility=path_config.volatility,
        garch_omega=path_config.garch_omega, garch_alpha=path_config.garch_alpha,
        garch_beta=path_config.garch_beta, student_t_df=path_config.student_t_df,
        jump_intensity=path_config.jump_intensity, jump_mean=path_config.jump_mean,
        jump_std=path_config.jump_std, ou_theta=path_config.ou_theta,
        ou_mu=path_config.ou_mu, ou_sigma=path_config.ou_sigma,
        n_bars=path_config.n_bars, start_price=path_config.start_price,
        seed=path_config.seed + seed_idx if path_config.seed is not None else None,
    )
    path_array = generate_path(per_path_config)

    factory = resolve_factory(strategy_name)
    engine_factory = lambda: factory(**strategy_params)  # noqa: E731
    adapter = _get_adapter()
    runner = BacktestRunner(engine_factory, adapter, fill_model=_default_fill_model())
    bars, timestamps = _bars_from_path(path_array, path_config, timeframe)
    result = runner.run(bars, timestamps=timestamps)
    pnl = result.equity_curve[-1] - result.equity_curve[0]
    return (pnl, max_drawdown_pct(result.equity_curve), sharpe_ratio(result.equity_curve))


def _check_memory(min_available_gb: float = 1.0) -> None:
    """Raise if available memory is below threshold."""
    try:
        import psutil
        mem = psutil.virtual_memory()
        avail_gb = mem.available / (1024**3)
        if avail_gb < min_available_gb:
            raise MemoryError(
                f"Only {avail_gb:.1f} GB available (need {min_available_gb}). "
                f"Reduce n_paths or wait for other sessions to finish."
            )
    except ImportError:
        pass  # psutil not installed — skip check


# Per-session MC worker cap.  Divides CPU budget by 3 (assumes up to 3
# concurrent sessions).  Override via QUANT_MC_WORKERS env var.
import os as _os
_MAX_MC_WORKERS = int(
    _os.environ.get(
        "QUANT_MC_WORKERS",
        max(1, (_os.cpu_count() or 4) // 3),
    )
)


def _run_mc_with_runner(
    strategy_name: str,
    strategy_params: dict[str, Any],
    n_paths: int,
    path_config: PathConfig,
    timeframe: str = "daily",
) -> Any:
    """Run MC for non-pyramid strategies, using multiprocessing for intraday.

    Generates paths one-at-a-time (streaming) to keep peak memory at O(n_bars)
    instead of O(n_paths * n_bars).  Workers generate their own paths to avoid
    serializing large numpy arrays through IPC.
    """
    import os

    import numpy as np

    from src.simulator.price_gen import generate_path
    from src.simulator.types import MonteCarloResult

    _check_memory(min_available_gb=1.0)

    use_mp = timeframe in ("intraday", "1m") and n_paths > 1
    if use_mp:
        from concurrent.futures import ProcessPoolExecutor

        workers = min(n_paths, _MAX_MC_WORKERS)
        work_items = [
            (strategy_name, strategy_params, i, path_config, timeframe)
            for i in range(n_paths)
        ]
        with ProcessPoolExecutor(max_workers=workers) as pool:
            results_list = list(pool.map(_mc_single_path, work_items))
    else:
        from src.simulator.backtester import BacktestRunner
        from src.simulator.metrics import max_drawdown_pct, sharpe_ratio

        factory = resolve_factory(strategy_name)
        engine_factory = lambda: factory(**strategy_params)  # noqa: E731
        adapter = _get_adapter()
        runner = BacktestRunner(engine_factory, adapter, fill_model=_default_fill_model())
        results_list = []
        for i in range(n_paths):
            cfg = PathConfig(
                drift=path_config.drift, volatility=path_config.volatility,
                garch_omega=path_config.garch_omega, garch_alpha=path_config.garch_alpha,
                garch_beta=path_config.garch_beta, student_t_df=path_config.student_t_df,
                jump_intensity=path_config.jump_intensity, jump_mean=path_config.jump_mean,
                jump_std=path_config.jump_std, ou_theta=path_config.ou_theta,
                ou_mu=path_config.ou_mu, ou_sigma=path_config.ou_sigma,
                n_bars=path_config.n_bars, start_price=path_config.start_price,
                seed=path_config.seed + i if path_config.seed is not None else None,
            )
            path = generate_path(cfg)
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

    _check_memory(min_available_gb=1.0)

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

    from src.strategies.registry import get_bar_agg
    meta_bar_agg = get_bar_agg(resolved_slug)
    sweep_bar_agg = int(clamped_base.pop("bar_agg", meta_bar_agg))
    sweep_params = {k: v for k, v in sweep_params.items() if k != "bar_agg"}

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
        if sweep_bar_agg > 1:
            raw = _aggregate_bars(raw, sweep_bar_agg)
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

    # Compute force_flat_indices for intraday strategies (real data only)
    from src.strategies.registry import is_intraday_strategy
    sweep_force_flat: set[int] | None = None
    if is_intraday_strategy(resolved_slug) and mode == "production_intent" and len(timestamps) > 1:
        sweep_force_flat = _compute_force_flat_indices(timestamps)

    adapter = _get_adapter()
    factory = resolve_factory(resolved_slug)
    optimizer = StrategyOptimizer(
        adapter,
        fill_model=_default_fill_model(),
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
            force_flat_indices=sweep_force_flat,
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
                try:
                    wf = optimizer.walk_forward(
                        engine_factory=lambda **p: factory(**{**clamped_base, **p}),
                        param_grid=param_grid,
                        bars=bars,
                        timestamps=timestamps,
                        train_bars=effective_train,
                        test_bars=effective_test,
                        objective=metric,
                        force_flat_indices=sweep_force_flat,
                    )
                    walk_forward_summary = {
                        "windows": len(wf.windows),
                        "efficiency": wf.efficiency,
                        "combined_oos_metrics": wf.combined_oos_metrics,
                    }
                except ValueError as _wf_err:
                    walk_forward_summary = {"error": str(_wf_err)}
        result = optimizer.grid_search(
            engine_factory=lambda **p: factory(**{**clamped_base, **p}),
            param_grid=param_grid,
            bars=bars,
            timestamps=timestamps,
            objective=metric,
            is_fraction=is_fraction,
            force_flat_indices=sweep_force_flat,
        )

    # Only materialize top 5 trials — avoids converting the full DataFrame to
    # a list of dicts (which can be hundreds of rows for large sweeps).
    n_trials = len(result.trials)
    trials_data = result.trials.head(5).to_dicts() if n_trials > 0 else []
    # Persist to param registry
    run_id = None
    pareto_candidates = []
    strategy_hash, strategy_code = _compute_code_hash(resolved_slug)
    try:
        from src.strategies.param_registry import ParamRegistry

        registry = ParamRegistry()
        search = "random" if n_samples is not None else "grid"
        # Build notes with timeframe info (matches run_backtest_realdata format)
        _is_intra = timeframe in ("intraday", "1m")
        _sweep_tf_label = _bar_agg_to_label(sweep_bar_agg)
        _sweep_tf_str = f"{_sweep_tf_label}{'|intraday' if _is_intra else ''}" if mode == "production_intent" and symbol else None
        _sweep_notes = f"tf={_sweep_tf_str}" if _sweep_tf_str else None
        run_id = registry.save_run(
            result=result,
            strategy=resolved_slug,
            symbol=symbol,
            objective=metric,
            search_type=search,
            source="mcp",
            train_start=start if mode == "production_intent" else None,
            train_end=end if mode == "production_intent" else None,
            notes=_sweep_notes,
            initial_capital=2_000_000.0,
            strategy_hash=strategy_hash,
            strategy_code=strategy_code,
            base_params=clamped_base,
        )
        pareto = registry.get_pareto_frontier(run_id)
        pareto_candidates = [
            {"params": p["params"], "sharpe": p.get("sharpe"), "calmar": p.get("calmar")}
            for p in pareto
        ]
        registry.close()
    except Exception:
        pass

    # Auto-validate: run full-period backtest with winning params
    full_period_metrics = None
    if mode == "production_intent" and run_id is not None and result.best_params:
        try:
            from src.simulator.monte_carlo import TAIFEX_BARS_PER_DAY as _TBPD
            _is_intraday = timeframe in ("intraday", "1m")
            _fp_ppy = _TBPD * 252.0 if _is_intraday else 252.0
            if not _is_intraday and len(bars) > 10:
                _trading_days = len({str(b.get("timestamp", ""))[:10] for b in bars})
                if _trading_days > 0:
                    _fp_ppy = (len(bars) / _trading_days) * 252.0
            full_runner = _build_runner(
                resolved_slug, {**clamped_base, **result.best_params},
                periods_per_year=_fp_ppy,
            )
            full_result = full_runner.run(
                bars, timestamps=timestamps, force_flat_indices=sweep_force_flat,
            )
            full_metrics = dict(full_result.metrics)
            full_metrics["total_pnl"] = full_result.equity_curve[-1] - full_result.equity_curve[0]
            # Compute alpha vs buy-and-hold
            _eq = full_result.equity_curve
            if len(_eq) > 1 and _eq[0] > 0 and len(bars) > 1:
                _strat_ret = (_eq[-1] - _eq[0]) / _eq[0]
                _bnh_ret = (bars[-1]["close"] - bars[0]["close"]) / bars[0]["close"]
                full_metrics["alpha"] = _strat_ret - _bnh_ret
            from src.strategies.param_registry import ParamRegistry as _PR2
            _reg2 = _PR2()
            _reg2.save_fullperiod_trial(
                run_id=run_id,
                params={**clamped_base, **result.best_params},
                metrics=full_metrics,
            )
            _reg2.close()
            _fp_keys = [
                "sharpe", "calmar", "sortino", "profit_factor",
                "win_rate", "max_drawdown_pct", "trade_count", "total_pnl", "alpha",
            ]
            full_period_metrics = {k: full_metrics.get(k) for k in _fp_keys}
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
        "n_trials": n_trials,
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
    if full_period_metrics is not None:
        out["full_period_metrics"] = full_period_metrics
    if mode == "production_intent":
        out["evaluation_data"] = {"symbol": symbol, "start": start, "end": end}
    return out


def _get_stress_bar_agg(slug: str) -> int:
    """Get bar aggregation factor for a strategy, defaulting to 1 (daily)."""
    try:
        from src.strategies.registry import get_bar_agg
        return get_bar_agg(slug)
    except Exception:
        return 1


def run_stress_for_mcp(
    scenarios: list[str] | None = None,
    strategy_params: dict[str, Any] | None = None,
    strategy: str = "pyramid",
) -> dict[str, Any]:
    """Run stress test scenarios."""
    from src.simulator.stress import (
        _generate_scenario_prices,
        _prices_to_bars,
        _prices_to_intraday_bars,
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
        runner = BacktestRunner(engine_factory, adapter, fill_model=_default_fill_model())
        prices = _generate_scenario_prices(scenario_obj, 20000.0)
        bar_agg = _get_stress_bar_agg(resolved_slug)
        if bar_agg > 1:
            bars_per_day = 1065 // bar_agg
            bars, timestamps = _prices_to_intraday_bars(prices, bars_per_day)
        else:
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
    strategy: str = "swing/trend_following/pyramid_wrapper",
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
    try:
        from src.strategies.registry import get_defaults

        defaults = get_defaults(strategy)
        return {
            "params": defaults,
            "source": "defaults",
            "note": "No optimized params found; returning PARAM_SCHEMA defaults.",
        }
    except KeyError:
        return {"error": f"Unknown strategy '{strategy}'"}


# ---------------------------------------------------------------------------
# Walk-forward validation
# ---------------------------------------------------------------------------


def run_walk_forward_for_mcp(
    strategy: str = "pyramid",
    n_folds: int = 3,
    oos_fraction: float = 0.2,
    session: str = "all",
    max_sweep_combinations: int = 50,
    strategy_params: dict[str, Any] | None = None,
    symbol: str | None = None,
    start: str | None = None,
    end: str | None = None,
    initial_equity: float = 2_000_000.0,
) -> dict[str, Any]:
    """Run expanding-window walk-forward validation."""
    from datetime import datetime as _dt
    from pathlib import Path

    from src.simulator.walk_forward import (
        WalkForwardConfig,
        FoldResult,
        build_walk_forward_result,
        compute_expanding_folds,
        compute_overfit_ratio,
        filter_bars_by_session,
    )

    resolved_slug = resolve_strategy_slug(strategy)

    if not (symbol and start and end):
        return {
            "error": "Walk-forward requires symbol, start, and end for real-data evaluation"
        }

    db_path = Path(__file__).resolve().parent.parent.parent / "data" / "taifex_data.db"
    if not db_path.exists():
        return {"error": f"Database not found at {db_path}"}

    from src.data.db import Database

    db = Database(f"sqlite:///{db_path}")
    start_dt = _dt.fromisoformat(start)
    end_dt = _dt.fromisoformat(end)
    raw = db.get_ohlcv(symbol, start_dt, end_dt)
    if not raw:
        return {"error": f"No data for {symbol} in {start}–{end}"}

    from src.strategies.registry import get_bar_agg
    meta_bar_agg = get_bar_agg(resolved_slug)
    bar_agg = int((strategy_params or {}).get("bar_agg", meta_bar_agg))
    if bar_agg > 1:
        raw = _aggregate_bars(raw, bar_agg)

    from statistics import mean as _mean
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

    # Filter by session if needed
    bars, timestamps, _ = filter_bars_by_session(bars, timestamps, session)

    # Compute folds
    folds_splits = compute_expanding_folds(timestamps, n_folds, oos_fraction)

    from src.strategies.registry import is_intraday_strategy
    is_intraday = is_intraday_strategy(resolved_slug)
    bars_per_day = len(bars) / max(len(set(str(t)[:10] for t in timestamps)), 1)
    ppy = bars_per_day * 252 if bars_per_day > 10 else 252.0

    fold_results: list[FoldResult] = []
    for fold_idx, (is_indices, oos_indices) in enumerate(folds_splits):
        is_bars = [bars[i] for i in is_indices]
        is_ts = [timestamps[i] for i in is_indices]
        oos_bars = [bars[i] for i in oos_indices]
        oos_ts = [timestamps[i] for i in oos_indices]

        # IS: run a backtest with current params to get IS Sharpe
        is_runner = _build_runner(
            resolved_slug, strategy_params, periods_per_year=ppy,
            initial_equity=initial_equity, instrument=symbol,
        )
        is_force_flat: set[int] | None = None
        if is_intraday:
            is_force_flat = _compute_force_flat_indices(is_ts)
        is_result = is_runner.run(is_bars, timestamps=is_ts, force_flat_indices=is_force_flat)
        is_sharpe = is_result.metrics.get("sharpe", 0.0)

        # OOS: run backtest on OOS window with same params
        oos_runner = _build_runner(
            resolved_slug, strategy_params, periods_per_year=ppy,
            initial_equity=initial_equity, instrument=symbol,
        )
        oos_force_flat: set[int] | None = None
        if is_intraday:
            oos_force_flat = _compute_force_flat_indices(oos_ts)
        oos_result = oos_runner.run(oos_bars, timestamps=oos_ts, force_flat_indices=oos_force_flat)
        oos_sharpe = oos_result.metrics.get("sharpe", 0.0)
        oos_mdd = oos_result.metrics.get("max_drawdown_pct", 0.0)
        oos_win = oos_result.metrics.get("win_rate", 0.0)
        oos_trades = int(oos_result.metrics.get("trade_count", 0))
        oos_pf = oos_result.metrics.get("profit_factor", 0.0)

        fold_results.append(FoldResult(
            fold_index=fold_idx,
            is_start=is_ts[0] if is_ts else _dt(2020, 1, 1),
            is_end=is_ts[-1] if is_ts else _dt(2020, 1, 1),
            oos_start=oos_ts[0] if oos_ts else _dt(2020, 1, 1),
            oos_end=oos_ts[-1] if oos_ts else _dt(2020, 1, 1),
            is_best_params=strategy_params or {},
            is_sharpe=is_sharpe,
            oos_sharpe=oos_sharpe,
            oos_mdd_pct=oos_mdd,
            oos_win_rate=oos_win,
            oos_n_trades=oos_trades,
            oos_profit_factor=oos_pf,
            overfit_ratio=compute_overfit_ratio(is_sharpe, oos_sharpe),
        ))

    wf_result = build_walk_forward_result(fold_results)

    return {
        "strategy": strategy,
        "n_folds": n_folds,
        "session": session,
        "aggregate_oos_sharpe": wf_result.aggregate_oos_sharpe,
        "mean_overfit_ratio": wf_result.mean_overfit_ratio,
        "overfit_flag": wf_result.overfit_flag,
        "passed": wf_result.passed,
        "failure_reasons": wf_result.failure_reasons,
        "folds": [
            {
                "fold_index": f.fold_index,
                "is_start": f.is_start.isoformat() if hasattr(f.is_start, "isoformat") else str(f.is_start),
                "is_end": f.is_end.isoformat() if hasattr(f.is_end, "isoformat") else str(f.is_end),
                "oos_start": f.oos_start.isoformat() if hasattr(f.oos_start, "isoformat") else str(f.oos_start),
                "oos_end": f.oos_end.isoformat() if hasattr(f.oos_end, "isoformat") else str(f.oos_end),
                "is_sharpe": f.is_sharpe,
                "oos_sharpe": f.oos_sharpe,
                "oos_mdd_pct": f.oos_mdd_pct,
                "oos_win_rate": f.oos_win_rate,
                "oos_n_trades": f.oos_n_trades,
                "oos_profit_factor": f.oos_profit_factor,
                "overfit_ratio": f.overfit_ratio,
            }
            for f in wf_result.folds
        ],
    }


# ---------------------------------------------------------------------------
# Parameter sensitivity check (±20% perturbation)
# ---------------------------------------------------------------------------


def run_sensitivity_check_for_mcp(
    strategy: str,
    best_params: dict[str, Any] | None = None,
    perturbation_pct: float = 20.0,
    n_steps: int = 5,
    instrument: str = "TX",
) -> dict[str, Any]:
    """Run a ±N% parameter sensitivity sweep on a strategy.

    Tests robustness by perturbing each parameter and checking if performance
    degrades sharply (cliff), indicating overfitting.

    Returns:
    - per_param: list of sensitivity results per parameter
    - passed: bool, True if all params stable (no cliffs, CV < 0.20 for all)
    - max_degradation_pct: maximum Sharpe drop across all params
    - likely_overfit: bool, True if >50% of params show cliff or instability
    """
    from src.simulator.param_sensitivity import (
        analyze_param_sensitivity,
        aggregate_sensitivity,
        generate_perturbation_grid,
    )

    resolved_slug = resolve_strategy_slug(strategy)

    # Step 1: Get parameter schema and active/provided best params
    schema = get_strategy_parameter_schema(resolved_slug)
    param_defs = schema.get("PARAM_SCHEMA", {})

    if best_params is None:
        active = get_active_params_for_mcp(strategy=resolved_slug)
        best_params = active.get("params", {})

    if not best_params:
        return {
            "error": "No parameters provided and no active candidate found",
            "passed": False,
            "per_param": [],
        }

    # Step 2: For each parameter, generate perturbation grid and run backtests
    sensitivity_results = []
    pct_range = perturbation_pct / 100.0

    for param_name, param_value in best_params.items():
        if param_name not in param_defs:
            continue  # Skip unknown params

        param_def = param_defs[param_name]
        is_integer = param_def.get("type") == "int"
        min_bound = param_def.get("min")
        max_bound = param_def.get("max")

        # Generate grid
        grid = generate_perturbation_grid(
            current_value=float(param_value),
            pct_range=pct_range,
            n_steps=n_steps,
            is_integer=is_integer,
            min_bound=float(min_bound) if min_bound is not None else None,
            max_bound=float(max_bound) if max_bound is not None else None,
        )

        # Run backtest for each grid point (using a quick synthetic test)
        sharpe_values = []
        baseline_sharpe = None

        for grid_val in grid:
            test_params = {**best_params, param_name: grid_val}
            result = run_backtest_for_mcp(
                scenario="strong_bull",
                strategy=resolved_slug,
                strategy_params=test_params,
                n_bars=252,
                timeframe="daily",
            )
            sharpe = result.get("metrics", {}).get("sharpe", 0.0)
            sharpe_values.append(float(sharpe))

            # Capture baseline (the original value)
            if abs(grid_val - float(param_value)) < 1e-6:
                baseline_sharpe = float(sharpe)

        if baseline_sharpe is None:
            baseline_sharpe = float(best_params[param_name])

        # Analyze this parameter
        sen_result = analyze_param_sensitivity(
            param_name=param_name,
            grid_values=grid,
            sharpe_values=sharpe_values,
            baseline_sharpe=baseline_sharpe,
        )
        sensitivity_results.append(sen_result)

    # Step 3: Aggregate across all parameters
    agg = aggregate_sensitivity(sensitivity_results)

    # Step 4: Format output
    per_param_out = []
    for sr in agg.per_param:
        per_param_out.append({
            "param_name": sr.param_name,
            "grid_values": sr.grid_values,
            "sharpe_values": sr.sharpe_values,
            "baseline_sharpe": sr.baseline_sharpe,
            "max_sharpe_drop_pct": sr.max_sharpe_drop_pct,
            "cliff_detected": sr.cliff_detected,
            "stability_cv": sr.stability_cv,
            "stable": sr.stable,
            "optimal_at_boundary": sr.optimal_at_boundary,
        })

    return {
        "strategy": strategy,
        "perturbation_pct": perturbation_pct,
        "n_steps": n_steps,
        "passed": agg.robust,
        "likely_overfit": agg.likely_overfit,
        "per_param": per_param_out,
        "max_degradation_pct": max(
            (r.max_sharpe_drop_pct for r in agg.per_param), default=0.0
        ),
    }


# ---------------------------------------------------------------------------
# Risk report
# ---------------------------------------------------------------------------


def run_risk_report_for_mcp(
    strategy: str = "pyramid",
    instrument: str = "TX",
    symbol: str | None = None,
    start: str | None = None,
    end: str | None = None,
    n_folds: int = 3,
) -> dict[str, Any]:
    """Generate a unified risk report by orchestrating all 5 evaluation layers.

    Layers:
    - L1 (Cost): Always computed from strategy metrics
    - L2 (Sensitivity): Computed via run_sensitivity_check
    - L3 (Regime): Computed via run_monte_carlo across scenarios
    - L4 (Adversarial): Computed via run_stress_test
    - L5 (Walk-forward): Only computed if symbol, start, end provided (real data)
    """
    from src.simulator.risk_report import build_risk_report
    from src.simulator.param_sensitivity import AggregatedSensitivity, SensitivityResult
    from src.simulator.regime import RegimeMetrics
    from src.simulator.adversarial import AdversarialResult
    from src.simulator.walk_forward import WalkForwardResult, compute_overfit_ratio
    from src.core.types import get_instrument_cost_config

    resolved_slug = resolve_strategy_slug(strategy)
    cost_config = get_instrument_cost_config(instrument)

    # Get active params for the strategy (used in L2 and L3)
    active_params_info = get_active_params_for_mcp(strategy=resolved_slug)
    best_params = active_params_info.get("params", {})

    # ===== L1: Cost Model =====
    # Run a quick baseline backtest to get cost metrics
    l1_result = run_backtest_for_mcp(
        scenario="strong_bull",
        strategy=resolved_slug,
        strategy_params=best_params,
        n_bars=252,
    )
    l1_net_sharpe = l1_result.get("metrics", {}).get("sharpe", 0.0)
    l1_cost_drag = 0.0
    if "impact_report" in l1_result:
        ir = l1_result["impact_report"]
        if ir.get("naive_pnl", 0) != 0:
            l1_cost_drag = (
                (ir.get("naive_pnl", 0) - ir.get("realistic_pnl", 0))
                / ir.get("naive_pnl", 1.0) * 100.0
            )

    # ===== L2: Parameter Sensitivity =====
    l2_sensitivity = None
    try:
        l2_result = run_sensitivity_check_for_mcp(
            strategy=resolved_slug,
            best_params=best_params,
            perturbation_pct=20.0,
            n_steps=5,
            instrument=instrument,
        )
        # Convert to AggregatedSensitivity
        if l2_result.get("per_param"):
            per_param_results = []
            for pp in l2_result["per_param"]:
                sr = SensitivityResult(
                    param_name=pp["param_name"],
                    grid_values=pp["grid_values"],
                    sharpe_values=pp["sharpe_values"],
                    baseline_sharpe=pp["baseline_sharpe"],
                    max_sharpe_drop_pct=pp["max_sharpe_drop_pct"],
                    cliff_detected=pp["cliff_detected"],
                    stability_cv=pp["stability_cv"],
                    optimal_at_boundary=pp["optimal_at_boundary"],
                    unstable=pp["stability_cv"] > 0.30,
                )
                per_param_results.append(sr)
            l2_sensitivity = AggregatedSensitivity(
                per_param=per_param_results,
                likely_overfit=l2_result["likely_overfit"],
                robust=l2_result["passed"],
            )
    except Exception:
        l2_sensitivity = None

    # ===== L3: Regime Monte Carlo =====
    l3_regime_metrics = None
    try:
        regime_labels = ["strong_bull", "sideways", "bear"]
        regime_metrics_list = []
        for regime_label in regime_labels:
            mc_result = run_monte_carlo_for_mcp(
                scenario=regime_label,
                strategy=resolved_slug,
                strategy_params=best_params,
                n_paths=100,
                n_bars=252,
            )
            mc_metrics = mc_result.get("metrics", {})
            regime_metrics_list.append(
                RegimeMetrics(
                    regime_label=regime_label,
                    n_sessions=int(mc_result.get("n_paths", 1)),
                    sharpe=float(mc_metrics.get("sharpe_p50", 0.0)),
                    mdd_pct=float(mc_metrics.get("max_drawdown_p50", 0.0)),
                    win_rate=float(mc_metrics.get("win_rate_p50", 0.0)),
                    avg_return=float(mc_metrics.get("mean_daily_return_p50", 0.0)),
                    total_pnl=float(mc_result.get("metrics", {}).get("total_pnl_p50", 0.0)),
                )
            )
        l3_regime_metrics = regime_metrics_list if regime_metrics_list else None
    except Exception:
        l3_regime_metrics = None

    # ===== L4: Adversarial Injection (via stress test proxy) =====
    l4_adversarial = None
    try:
        stress_result = run_stress_for_mcp(
            scenarios=["flash_crash", "gap_down", "slow_bleed"],
            strategy=resolved_slug,
            strategy_params=best_params,
        )
        # Use worst-case scenario as adversarial proxy
        worst_equity = float("inf")
        if stress_result.get("results"):
            for scenario_name, res in stress_result["results"].items():
                final_eq = res.get("metrics", {}).get("total_pnl", 0.0)
                if final_eq < worst_equity:
                    worst_equity = final_eq
        if worst_equity != float("inf"):
            l4_adversarial = AdversarialResult(
                clean_paths=None,
                injected_paths=None,
                injection_metadata=[],
                clean_var_95=0.0,
                clean_var_99=0.0,
                clean_median_final=0.0,
                clean_prob_ruin=0.0,
                injected_var_95=0.0,
                injected_var_99=0.0,
                injected_median_final=worst_equity,
                injected_prob_ruin=0.0,
                worst_case_terminal_equity=worst_equity,
                median_impact_pct=0.0,
            )
    except Exception:
        l4_adversarial = None

    # ===== L5: Walk-Forward Validation (only if real data provided) =====
    l5_walk_forward = None
    if symbol and start and end:
        try:
            wf_result = run_walk_forward_for_mcp(
                strategy=resolved_slug,
                symbol=symbol,
                start=start,
                end=end,
                n_folds=n_folds,
                session="all",
                strategy_params=best_params,
            )
            # Convert dict result to WalkForwardResult-like object
            folds = []
            if "folds" in wf_result:
                from src.simulator.walk_forward import FoldResult
                from datetime import datetime as _dt

                for fold_dict in wf_result["folds"]:
                    fold = FoldResult(
                        fold_index=fold_dict.get("fold_index", 0),
                        is_start=_dt.fromisoformat(fold_dict.get("is_start", "2020-01-01")),
                        is_end=_dt.fromisoformat(fold_dict.get("is_end", "2020-01-01")),
                        oos_start=_dt.fromisoformat(fold_dict.get("oos_start", "2020-01-01")),
                        oos_end=_dt.fromisoformat(fold_dict.get("oos_end", "2020-01-01")),
                        is_best_params=best_params,
                        is_sharpe=fold_dict.get("is_sharpe", 0.0),
                        oos_sharpe=fold_dict.get("oos_sharpe", 0.0),
                        oos_mdd_pct=fold_dict.get("oos_mdd_pct", 0.0),
                        oos_win_rate=fold_dict.get("oos_win_rate", 0.0),
                        oos_n_trades=fold_dict.get("oos_n_trades", 0),
                        oos_profit_factor=fold_dict.get("oos_profit_factor", 0.0),
                        overfit_ratio=fold_dict.get("overfit_ratio", 0.0),
                    )
                    folds.append(fold)

            # Build WalkForwardResult manually
            mean_oos_sharpe = (
                sum(f.oos_sharpe for f in folds) / len(folds)
                if folds
                else 0.0
            )
            mean_overfit = (
                sum(f.overfit_ratio for f in folds) / len(folds)
                if folds
                else 0.0
            )

            from src.simulator.walk_forward import classify_overfit

            l5_walk_forward = WalkForwardResult(
                folds=folds,
                aggregate_oos_sharpe=mean_oos_sharpe,
                mean_overfit_ratio=mean_overfit,
                overfit_flag=classify_overfit(mean_overfit),
                passed=wf_result.get("passed", False),
                failure_reasons=wf_result.get("failure_reasons", []),
            )
        except Exception:
            l5_walk_forward = None

    # ===== Build unified report =====
    report = build_risk_report(
        strategy_name=resolved_slug,
        instrument=instrument,
        cost_config=cost_config,
        net_sharpe=l1_net_sharpe,
        cost_drag_pct=l1_cost_drag,
        sensitivity=l2_sensitivity,
        regime_metrics=l3_regime_metrics,
        adversarial_result=l4_adversarial,
        walk_forward_result=l5_walk_forward,
    )
    return report.to_dict()
