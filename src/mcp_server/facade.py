"""Facade bridging MCP tool calls to existing simulator APIs.

All functions accept flat dicts and return JSON-serializable dicts.
"""

from __future__ import annotations

import collections
import dataclasses
import importlib
import json
import os
from typing import Any

import structlog

from src.simulator.types import PRESETS, PathConfig

_facade_log = structlog.get_logger(__name__)

# Factory cache: avoids importlib.reload() on every MC worker / sweep trial.
# Code-hash change detection auto-invalidates; env QUANT_RELOAD_STRATEGY=1 forces reload.
_factory_cache: dict[str, Any] = {}
_factory_hashes: dict[str, str] = {}

# Pinned-code cache keyed by (slug, hash). Bounded LRU — strategies change source
# rarely, so 64 entries covers 16 strategies with up to 4 historical versions each.
_PIN_CACHE_MAX = int(os.environ.get("QUANT_PIN_CACHE_SIZE", "64"))
_factory_cache_by_hash: "collections.OrderedDict[tuple[str, str], Any]" = collections.OrderedDict()

# One-shot set so the "pin differs from current file" warning fires exactly once
# per (slug, reason) per process.
_warned_drift_slugs: set[str] = set()
_warned_fallback_slugs: set[tuple[str, str]] = set()


class StrategyHashNotFound(LookupError):
    """Raised when an explicit strategy_hash has no matching stored code."""


class PinnedExecutionError(RuntimeError):
    """Raised when pinned strategy code is present but cannot be compiled/loaded."""


def _should_reload_strategy(slug: str) -> bool:
    """Return True when strategy source changed since last load."""
    if os.environ.get("QUANT_RELOAD_STRATEGY", "0") == "1":
        return True
    try:
        new_hash, _ = _compute_code_hash(slug)
    except Exception:
        return False
    old = _factory_hashes.get(slug)
    if old is None:
        return False
    return new_hash != old


def _normalize_params_for_hash(params: dict[str, Any]) -> str:
    """Normalize params for consistent hashing: all numeric values become floats.

    Prevents int/float type mismatches (e.g. 20 vs 20.0) from producing
    different hash values for logically identical parameter sets.
    """
    def _norm(v: Any) -> Any:
        if isinstance(v, bool):
            return v  # bool is a subclass of int; preserve it
        if isinstance(v, (int, float)):
            return float(v)
        if isinstance(v, dict):
            return {k: _norm(val) for k, val in v.items()}
        if isinstance(v, list):
            return [_norm(i) for i in v]
        return v

    return json.dumps({k: _norm(v) for k, v in params.items()}, sort_keys=True)


def _compute_force_flat_indices(timestamps: list, slug: str | None = None) -> set[int]:
    """Compute the set of bar indices where force-flat (session close) should occur.

    Adds an index whenever the session ID changes between consecutive bars, and
    always adds the final bar index so the last open position is closed.

    The classifier for whether a strategy needs session-close liquidation is
    ``holding_period`` (via ``is_intraday_strategy(slug)``), not the bar
    timeframe. A SWING strategy that consumes 5m bars holds positions across
    sessions; an INTRADAY strategy on the same bars flattens at session close.

    When ``slug`` is provided and the strategy is non-intraday (SWING /
    long-horizon), this returns an empty set as a defense-in-depth guard so
    callers that forget to gate the call still produce correct behavior. The
    final bar index is still added in all cases so the runner can close any
    residual position at the end of the test window.
    """
    if not timestamps:
        return set()

    if slug is not None:
        from src.strategies.registry import is_intraday_strategy
        if not is_intraday_strategy(slug):
            return {len(timestamps) - 1}

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

    Results are cached per-process. Auto-invalidated when the strategy source
    file changes (code-hash check). Set QUANT_RELOAD_STRATEGY=1 to force reload.
    """
    need_reload = _should_reload_strategy(strategy)
    if strategy in _factory_cache and not need_reload:
        return _factory_cache[strategy]

    from src.strategies.registry import get_all, get_info

    result = None
    try:
        info = get_info(strategy)
        mod = importlib.import_module(info.module)
        if need_reload or strategy not in _factory_cache:
            importlib.reload(mod)
        result = getattr(mod, info.factory)
    except KeyError:
        pass
    if result is None and ":" in strategy:
        mod_path, fn_name = strategy.rsplit(":", 1)
        mod = importlib.import_module(mod_path)
        if need_reload:
            importlib.reload(mod)
        result = getattr(mod, fn_name)
    if result is None:
        available = list(get_all().keys())
        raise ValueError(f"Unknown strategy '{strategy}'. Available: {available}")
    _factory_cache[strategy] = result
    try:
        h, _ = _compute_code_hash(strategy)
        _factory_hashes[strategy] = h
    except Exception:
        pass
    return result


def _snapshot_meta_json(slug: str) -> str | None:
    """Return the module-level ``STRATEGY_META`` for ``slug`` as a JSON string.

    Values that are not JSON-native (enums, tuples) are coerced. Returns
    ``None`` when the strategy cannot be resolved or has no META.
    """
    try:
        from src.strategies.registry import get_info
        from src.strategies.pinned_loader import _coerce_meta

        meta = get_info(slug).meta
    except Exception:
        return None
    if not meta:
        return None
    return json.dumps(_coerce_meta(meta))


def _pin_enabled() -> bool:
    """Return True when pinned execution is active.

    Defaults to ``"1"`` (on). Set ``QUANT_PINNED_EXECUTION=0`` as an
    emergency escape hatch that reverts to resolving strategies from
    ``src/strategies/<slug>.py`` on disk.
    """
    return os.environ.get("QUANT_PINNED_EXECUTION", "1") == "1"


def _lru_get(key: tuple[str, str]):
    entry = _factory_cache_by_hash.get(key)
    if entry is not None:
        _factory_cache_by_hash.move_to_end(key)
    return entry


def _lru_put(key: tuple[str, str], value) -> None:
    _factory_cache_by_hash[key] = value
    _factory_cache_by_hash.move_to_end(key)
    while len(_factory_cache_by_hash) > _PIN_CACHE_MAX:
        _factory_cache_by_hash.popitem(last=False)


def _log_fallback_once(slug: str, reason: str) -> None:
    key = (slug, reason)
    if key in _warned_fallback_slugs:
        return
    _warned_fallback_slugs.add(key)
    _facade_log.info("pinned_fallback", slug=slug, reason=reason)


def _log_drift_once(slug: str, pinned_hash: str, file_hash: str | None) -> None:
    if slug in _warned_drift_slugs:
        return
    _warned_drift_slugs.add(slug)
    _facade_log.info(
        "pinned_strategy_drift",
        slug=slug,
        pinned_hash=pinned_hash[:12] if pinned_hash else None,
        file_hash=(file_hash or "")[:12] or None,
    )


def resolve_factory_by_hash(
    slug: str,
    strategy_hash: str | None = None,
    strategy_code: str | None = None,
    force_current_file: bool = False,
) -> tuple[Any, dict]:
    """Return ``(factory, meta)`` pinned to a specific source version.

    Resolution ladder (first match wins):
        1. Flag ``QUANT_PINNED_EXECUTION`` off → current-file fallback.
        2. ``force_current_file=True`` → pin to the current file's source.
           Used by ``run_parameter_sweep`` where the optimizer is creating the
           *next* pin and must execute against current code, not a stale pin.
        3. ``(slug, strategy_hash)`` in the LRU cache → cached factory.
        4. Explicit ``strategy_code`` argument → compile + cache.
        5. Explicit ``strategy_hash`` only → look up code via
           :meth:`ParamRegistry.get_code_by_hash`; raise
           :class:`StrategyHashNotFound` if absent.
        6. Neither provided → consult the active candidate for ``slug``. If it
           has a pinned hash + code, use those.
        7. Otherwise → current-file fallback via :func:`resolve_factory`.

    ``meta`` is the JSON-safe ``STRATEGY_META`` dict of whichever source was
    chosen. Callers use it for spread-leg routing and other META-driven
    behavior so the dispatch stays hash-aware.
    """
    if not _pin_enabled():
        factory = resolve_factory(slug)
        from src.strategies.registry import get_info
        return factory, dict(get_info(slug).meta or {})

    # Force pinning to the current file — compile it through the pinned loader
    # so workers still receive a picklable factory, but the source is taken from
    # disk rather than a stored candidate.
    if force_current_file:
        file_hash, file_code = _compute_code_hash(slug)
        if file_hash and file_code:
            cached = _lru_get((slug, file_hash))
            if cached is not None:
                return cached.factory, dict(cached.meta)
            return _compile_and_cache(slug, file_hash, file_code)
        factory = resolve_factory(slug)
        from src.strategies.registry import get_info
        return factory, dict(get_info(slug).meta or {})

    # Short-circuit on cache hit for the exact (slug, hash).
    if strategy_hash:
        cached = _lru_get((slug, strategy_hash))
        if cached is not None:
            pinned = cached
            return pinned.factory, dict(pinned.meta)

    # Explicit code provided → compile directly.
    if strategy_code is not None and strategy_hash is not None:
        return _compile_and_cache(slug, strategy_hash, strategy_code)

    # Hash only → look up code from registry.
    if strategy_hash is not None:
        code, meta = _fetch_code_by_hash(slug, strategy_hash)
        if code is None:
            raise StrategyHashNotFound(
                f"No stored strategy_code for slug={slug} hash={strategy_hash[:12]}"
            )
        return _compile_and_cache(slug, strategy_hash, code, stored_meta=meta)

    # Nothing provided → consult the active candidate.
    active_hash, active_code, active_meta = _fetch_active_pin(slug)
    if active_hash and active_code:
        _maybe_warn_drift(slug, active_hash)
        return _compile_and_cache(slug, active_hash, active_code, stored_meta=active_meta)

    # No pin available anywhere → fall back to the current file.
    _log_fallback_once(slug, "no_active_pin" if active_hash is None else "no_active_code")
    factory = resolve_factory(slug)
    from src.strategies.registry import get_info
    return factory, dict(get_info(slug).meta or {})


def _compile_and_cache(
    slug: str,
    strategy_hash: str,
    strategy_code: str,
    stored_meta: dict | None = None,
) -> tuple[Any, dict]:
    """Compile the pinned source, cache the result, return factory + meta."""
    from src.strategies.pinned_loader import load_pinned_strategy

    try:
        pinned = load_pinned_strategy(slug, strategy_code, expected_hash=strategy_hash)
    except Exception as exc:
        raise PinnedExecutionError(
            f"Failed to compile pinned code for {slug}@{strategy_hash[:12]}: {exc}"
        ) from exc
    _lru_put((slug, strategy_hash), pinned)
    # Prefer the stored meta snapshot (JSON-safe) when available; fall back to
    # the meta extracted from the compiled module so older rows without
    # strategy_meta_json still work.
    meta = dict(stored_meta) if stored_meta else dict(pinned.meta)
    return pinned.factory, meta


def _fetch_code_by_hash(
    slug: str, strategy_hash: str,
) -> tuple[str | None, dict | None]:
    from src.strategies.param_registry import ParamRegistry

    reg = ParamRegistry()
    try:
        return reg.get_code_by_hash(slug, strategy_hash)
    finally:
        reg.close()


def _fetch_active_pin(slug: str) -> tuple[str | None, str | None, dict | None]:
    """Return ``(hash, code, meta)`` for the active candidate, or all ``None``."""
    from src.strategies.param_registry import ParamRegistry

    reg = ParamRegistry()
    try:
        detail = reg.get_active_detail(slug)
    finally:
        reg.close()
    if not detail:
        return None, None, None
    return (
        detail.get("strategy_hash"),
        detail.get("strategy_code"),
        detail.get("strategy_meta"),
    )


def _maybe_warn_drift(slug: str, pinned_hash: str) -> None:
    file_hash, _ = _compute_code_hash(slug)
    if file_hash and file_hash != pinned_hash:
        _log_drift_once(slug, pinned_hash, file_hash)


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
    bar_agg: int = 1,
) -> PathConfig:
    """Create a PathConfig, rescaling daily-calibrated params for intraday.

    bar_agg: strategy's native bar aggregation (e.g., 15 for 15m strategies).
    When bar_agg > 1 and timeframe is intraday, n_bars is scaled up so that
    after aggregation the caller receives exactly n_bars N-min bars.
    """
    import math
    from src.simulator.monte_carlo import TAIFEX_BARS_PER_DAY

    base = _resolve_path_config(scenario)
    is_intraday = timeframe in ("intraday", "1m")
    bpd = TAIFEX_BARS_PER_DAY  # 1065
    # Scale requested N-min bars back to 1-min count for generation.
    # Default when n_bars is None: 20 trading days of 1-min bars.
    _scale = bar_agg if (is_intraday and bar_agg > 1) else 1
    effective_n = (n_bars * _scale) if n_bars is not None else (bpd * 20 if is_intraday else base.n_bars)
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


def _aggregate_synthetic_bars(
    bars: list[dict[str, Any]],
    timestamps: list,
    bar_agg: int,
) -> tuple[list[dict[str, Any]], list]:
    """Aggregate 1-min synthetic bars (dicts) to N-min bars.

    Groups every bar_agg consecutive bars: open=first.open, high=max(highs),
    low=min(lows), close=last.close, volume=sum. Timestamp from first bar.
    """
    if bar_agg <= 1 or not bars:
        return bars, timestamps
    agg_bars: list[dict[str, Any]] = []
    agg_ts = []
    for i in range(0, len(bars), bar_agg):
        group = bars[i : i + bar_agg]
        ts_group = timestamps[i : i + bar_agg]
        if not group:
            break
        agg_bars.append({
            "price": group[-1]["close"],
            "symbol": group[0].get("symbol", ""),
            "daily_atr": group[-1].get("daily_atr", 0.0),
            "open": group[0]["open"],
            "high": max(b["high"] for b in group),
            "low": min(b["low"] for b in group),
            "close": group[-1]["close"],
            "volume": sum(b.get("volume", 0.0) for b in group),
        })
        agg_ts.append(ts_group[0])
    return agg_bars, agg_ts


def _bars_from_path(
    path,
    config: PathConfig,
    timeframe: str = "daily",
    bar_agg: int = 1,
):
    """Generate bars with correct timestamps for the given timeframe.

    When bar_agg > 1 and timeframe is intraday, the 1-min bars are
    aggregated into N-min bars so the strategy receives its native timeframe.
    """
    if timeframe in ("intraday", "1m"):
        from src.simulator.monte_carlo import _path_to_intraday_bars

        bars, timestamps = _path_to_intraday_bars(path, config)
        if bar_agg > 1:
            bars, timestamps = _aggregate_synthetic_bars(bars, timestamps, bar_agg)
        return bars, timestamps
    from src.simulator.monte_carlo import _path_to_bars

    return _path_to_bars(path, config)


def _load_bars_for_tf(db, symbol: str, start, end, bar_agg: int):
    """Load bars at the right timeframe, using pre-aggregated tables when available.

    Routing:
      bar_agg=1  → ohlcv_bars (raw 1m)
      bar_agg=5  → ohlcv_5m (pre-aggregated, session-correct)
      bar_agg=60 → ohlcv_1h (pre-aggregated, session-correct)
      other      → load 1m + _aggregate_bars() fallback
    """
    if bar_agg in (5, 60):
        raw = db.get_ohlcv_tf(symbol, start, end, minutes=bar_agg)
        if raw:
            return raw
        # Table empty — fall through to 1m + aggregation

    raw = db.get_ohlcv(symbol, start, end)
    if bar_agg <= 1 or not raw:
        return raw
    return _aggregate_bars(raw, bar_agg)


def _aggregate_bars(raw, bar_agg: int):
    """Aggregate 1-min OHLCVBar objects into N-min bars (fallback).

    Prefer pre-aggregated tables via _load_bars_for_tf() when available.
    This function does NOT respect session boundaries — it uses simple
    epoch bucketing. Only used when pre-aggregated tables are empty.
    """
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


def _get_spread_meta(
    strategy_slug: str, pinned_meta: dict | None = None,
) -> dict | None:
    """Return ``spread_legs`` metadata if the strategy is a spread strategy.

    When ``pinned_meta`` is supplied (e.g. from :func:`resolve_factory_by_hash`
    during a pinned backtest), it takes precedence over the current-file
    ``STRATEGY_META`` so spread-leg routing stays consistent with whatever
    source the engine is actually executing.
    """
    if pinned_meta:
        legs = pinned_meta.get("spread_legs")
        if legs and len(legs) == 2:
            return pinned_meta
    try:
        from src.strategies.registry import get_info
        info = get_info(strategy_slug)
        legs = info.meta.get("spread_legs")
        if legs and len(legs) == 2:
            return info.meta
    except (KeyError, AttributeError):
        pass
    return None


@dataclasses.dataclass
class SpreadBarsResult:
    """Output of _build_spread_bars.

    Carries synthetic spread bars plus the inner-joined R1/R2 source bars and
    the offset applied, so callers (backtest serialization, live chart) can
    render all three aligned series without re-loading legs.
    """
    spread_bars: list
    r1_aligned: list
    r2_aligned: list
    offset: float
    error: str | None


def _build_spread_bars(
    db,
    leg1_sym: str,
    leg2_sym: str,
    start,
    end,
    bar_agg: int = 1,
    offset_override: float | None = None,
) -> SpreadBarsResult:
    """Construct synthetic spread bars: price = leg1 - leg2 + offset.

    The spread (R1-R2) can be negative, but MarketSnapshot requires price>0.
    A constant offset shifts all values positive without affecting z-score
    signals (z = (x-mean)/std is shift-invariant).

    Args:
        offset_override: If provided, use this offset instead of computing
            from historical min. Used by live spread visualization to maintain
            z-score continuity with the live session offset.

    Returns:
        SpreadBarsResult with spread_bars + aligned R1/R2 source bars + offset.
        On failure, error is populated and the bar lists are empty.
    """
    from src.data.db import OHLCVBar
    r1_raw = _load_bars_for_tf(db, leg1_sym, start, end, bar_agg)
    r2_raw = _load_bars_for_tf(db, leg2_sym, start, end, bar_agg)
    if not r1_raw or not r2_raw:
        return SpreadBarsResult(
            [], [], [], 0.0,
            f"Missing data: {leg1_sym}={len(r1_raw or [])} bars, {leg2_sym}={len(r2_raw or [])} bars",
        )
    r2_map = {b.timestamp: b for b in r2_raw}
    # First pass: find min spread to determine offset (unless overridden)
    raw_closes = []
    for b1 in r1_raw:
        b2 = r2_map.get(b1.timestamp)
        if b2 is not None:
            raw_closes.append(b1.close - b2.close)
    if not raw_closes:
        return SpreadBarsResult([], [], [], 0.0, "No overlapping timestamps between legs")
    if offset_override is not None and offset_override >= 0:
        offset = offset_override
    else:
        offset = max(-min(raw_closes) + 100.0, 0.0)
    # Second pass: build bars with offset applied, collecting aligned source bars
    spread_bars = []
    r1_aligned = []
    r2_aligned = []
    for b1 in r1_raw:
        b2 = r2_map.get(b1.timestamp)
        if b2 is None:
            continue
        sc = b1.close - b2.close + offset
        so = b1.open - b2.open + offset
        spread_bars.append(OHLCVBar(
            timestamp=b1.timestamp,
            open=so,
            high=max(sc, so),
            low=min(sc, so),
            close=sc,
            volume=min(b1.volume, b2.volume),
        ))
        r1_aligned.append(b1)
        r2_aligned.append(b2)
    return SpreadBarsResult(spread_bars, r1_aligned, r2_aligned, offset, None)


def _build_runner(
    strategy: str,
    strategy_params: dict[str, Any] | None,
    periods_per_year: float = 252.0,
    fill_model=None,
    initial_equity: float = 2_000_000.0,
    instrument: str | None = None,
    spread_meta: dict | None = None,
    strategy_hash: str | None = None,
    strategy_code: str | None = None,
    force_current_file: bool = False,
):
    """Build a BacktestRunner for any strategy. Single source of truth.

    When ``QUANT_PINNED_EXECUTION`` is enabled, the factory is resolved via
    :func:`resolve_factory_by_hash` so the engine executes the pinned source
    recorded in ``param_runs.strategy_code``. ``force_current_file=True``
    bypasses pinning and reads the current ``src/strategies/<slug>.py`` — used
    by the optimization sweep where the user is creating the next pin.
    """
    from src.simulator.backtester import BacktestRunner
    from src.core.types import ImpactParams, get_instrument_cost_config
    from src.simulator.fill_model import MarketImpactFillModel

    cost_config = get_instrument_cost_config(instrument or "")
    factory, _pinned_meta = resolve_factory_by_hash(
        strategy,
        strategy_hash=strategy_hash,
        strategy_code=strategy_code,
        force_current_file=force_current_file,
    )
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
    # Spread strategies: override cost model (4 legs, fixed per-fill cost)
    if spread_meta and fill_model is None:
        cost_per_fill = spread_meta.get("spread_cost_per_fill", 700.0)
        impact_params = ImpactParams(
            spread_bps=0.0,
            commission_bps=0.0,
            commission_fixed_per_contract=cost_per_fill,
            k=0.0,
        )
        fm = MarketImpactFillModel(params=impact_params)
    elif fill_model is None:
        impact_params = ImpactParams(
            spread_bps=slippage_bps,
            commission_bps=commission_bps,
            commission_fixed_per_contract=commission_fixed,
        )
        fm = MarketImpactFillModel(params=impact_params)
    else:
        fm = fill_model
    # Extract optional sizing overrides from strategy_params (stripped before
    # passing to factory). Two generic tuning knobs: `risk_per_trade` sets the
    # fraction of equity risked per trade (drives `risk_lots = equity ×
    # risk_per_trade / (stop_distance × point_value)`), and `margin_cap` sets
    # the upper bound (`max_lots_by_margin = equity × margin_cap /
    # margin_per_unit`). The sizer applies `min(risk_lots, margin_cap_lots)`,
    # so margin_cap IS the hard cap — no separate max_lots knob needed.
    # `max_lots` is accepted for advanced callers who explicitly want an
    # additional hard cap; popped here so it never reaches the factory.
    _risk_per_trade = float(merged.pop("risk_per_trade", 0.02))
    _margin_cap = float(merged.pop("margin_cap", 0.50))
    _max_lots_override = merged.pop("max_lots", None)

    merged.pop("bar_agg", None)
    if "max_loss" not in merged:
        merged["max_loss"] = 500_000
    # Pass initial_capital to factories that accept it (e.g. vol_managed_bnh)
    import inspect
    _sig = inspect.signature(factory)
    if "initial_capital" in _sig.parameters:
        merged["initial_capital"] = initial_equity
    engine_factory = lambda: factory(**merged)  # noqa: E731
    # Default SizingConfig so strategies emitting `lots=1` scale with equity.
    # Without this the BacktestRunner runs with sizer=None and the literal lots
    # from each EntryDecision flows through unchanged — i.e. 1 contract at any
    # account size, which silently wastes the Sharpe of any strategy that does
    # not hand-roll its own sizing. See docs/night-session-investigation.md.
    from src.core.sizing import default_sizing_config
    default_sizing = default_sizing_config(
        initial_equity=initial_equity,
        risk_per_trade=_risk_per_trade,
        margin_cap=_margin_cap,
    )
    if _max_lots_override is not None:
        default_sizing.max_lots = int(_max_lots_override)
    return BacktestRunner(
        engine_factory,
        adapter,
        fill_model=fm,
        initial_equity=initial_equity,
        periods_per_year=periods_per_year,
        sizing_config=default_sizing,
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


def _extract_trade_pnls(trade_log, last_price: float | None = None) -> list[float]:
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
    # Mark-to-market remaining open position
    if entry is not None and last_price is not None:
        diff = (last_price - entry.fill_price) * entry.lots
        pnls.append(diff if entry.side == "buy" else -diff)
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

    from src.strategies.registry import get_bar_agg
    bar_agg = get_bar_agg(resolved_slug)
    path_config = _make_path_config(scenario, n_bars, timeframe, bar_agg)
    is_intraday = timeframe in ("intraday", "1m")
    effective_bpd = TAIFEX_BARS_PER_DAY / max(bar_agg, 1) if is_intraday else 1
    ppy = effective_bpd * 252.0 if is_intraday else 252.0
    runner = _build_runner(
        resolved_slug, clamped_params, periods_per_year=ppy, initial_equity=initial_equity
    )
    paths = generate_paths(1, path_config)
    bars, timestamps = _bars_from_path(paths[0], path_config, timeframe, bar_agg)
    # Intraday mode: compute session boundaries for force-close
    force_flat_indices: set[int] | None = None
    if is_intraday and len(timestamps) > 1:
        force_flat_indices = _compute_force_flat_indices(timestamps, slug=resolved_slug)
    result = runner.run(bars, timestamps=timestamps, force_flat_indices=force_flat_indices)
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
            strategy_meta_json=_snapshot_meta_json(resolved_slug),
        )
        registry.close()
        if run_id > 0:
            out["run_id"] = run_id
    except Exception:
        pass
    return out


class _CacheKey:
    """Cache key components for a real-data backtest."""

    __slots__ = ("strategy_hash", "combined_notes", "cost_note", "timeframe_str")

    def __init__(self, strategy_hash: str | None, combined_notes: str,
                 cost_note: str | None, timeframe_str: str):
        self.strategy_hash = strategy_hash
        self.combined_notes = combined_notes
        self.cost_note = cost_note
        self.timeframe_str = timeframe_str


def _build_cache_key(
    strategy: str,
    strategy_params: dict[str, Any] | None = None,
    intraday: bool = False,
    symbol: str = "",
    initial_equity: float | None = None,
) -> _CacheKey:
    """Compute cache key components for a real-data backtest.

    ``initial_equity`` is hashed into the key because the persisted
    equity_curve is denominated in NT dollars at the requested capital;
    omitting it lets a cached run done with one initial_equity be served
    back to a caller asking for a different initial_equity, producing
    silently wrong PnL. The same applies to the equity ratios, drawdown
    pct, and lot sizing emitted by the simulator.
    """
    import hashlib
    from src.core.types import get_instrument_cost_config

    resolved_slug = resolve_strategy_slug(strategy)

    if not intraday:
        from src.strategies.registry import is_intraday_strategy
        intraday = is_intraday_strategy(resolved_slug)

    from src.strategies.registry import get_bar_agg
    meta_bar_agg = get_bar_agg(resolved_slug)
    bar_agg = int((strategy_params or {}).get("bar_agg", meta_bar_agg))

    strategy_hash, _ = _compute_code_hash(resolved_slug)
    _sp = strategy_params or {}
    # Use instrument cost defaults when not explicitly provided (matches _build_runner)
    cost_config = get_instrument_cost_config(symbol)
    _slip_bps = _sp.get("slippage_bps", cost_config.slippage_bps)
    _comm_fixed = _sp.get("commission_fixed_per_contract", cost_config.commission_per_contract)
    # Always generate cost_note so frontend can display costs
    cost_note = f"sbps={_slip_bps}|cfix={_comm_fixed}"
    _p_str = _normalize_params_for_hash(_sp)
    _p_hash = hashlib.md5(_p_str.encode()).hexdigest()[:8]
    cost_note = f"p={_p_hash}|{cost_note}"
    # Equity is folded into the cost_note prefix so it gets persisted
    # alongside other cost-relevant metadata when `save_backtest_run`
    # later appends `; tf=...`. This keeps the save-side and lookup-side
    # combined notes byte-identical:
    #   save:    "p=...; sbps=...; cfix=...; eq=N" + "; tf=..."
    #   lookup:  "p=...; sbps=...; cfix=...; eq=N; tf=..."
    if initial_equity is not None:
        cost_note = f"{cost_note}; eq={int(initial_equity)}"
    timeframe_str = f"{bar_agg}min{'|intraday' if intraday else ''}"
    _tf_notes = f"tf={timeframe_str}"
    combined_notes = "; ".join(filter(None, [cost_note, _tf_notes]))
    return _CacheKey(strategy_hash, combined_notes, cost_note, timeframe_str)


def lookup_backtest_cache(
    symbol: str,
    start: str,
    end: str,
    strategy: str,
    strategy_params: dict[str, Any] | None = None,
    intraday: bool = False,
    initial_equity: float | None = None,
) -> dict[str, Any] | None:
    """Return cached backtest result if available, else None.

    Runs the same cache key computation as run_backtest_realdata_for_mcp
    without loading bars or running simulation. Fast (~10ms).

    ``initial_equity`` participates in the cache key so a result computed
    at a different starting capital is not silently served back.
    """
    ck = _build_cache_key(strategy, strategy_params, intraday, symbol, initial_equity)
    if not ck.strategy_hash:
        return None

    from src.strategies.param_registry import ParamRegistry
    reg = ParamRegistry()
    cached = reg.get_cached_result(
        strategy_hash=ck.strategy_hash,
        symbol=symbol,
        start=start,
        end=end,
        notes=ck.combined_notes,
    )
    reg.close()
    if cached is not None:
        cached["cache_hit"] = True
    return cached


def run_backtest_realdata_for_mcp(
    symbol: str,
    start: str,
    end: str,
    strategy: str = "pyramid",
    strategy_params: dict[str, Any] | None = None,
    initial_equity: float = 2_000_000.0,
    intraday: bool = False,
    force_current_file: bool = False,
    spread_legs_override: list[str] | None = None,
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

    db_path = Path(__file__).resolve().parent.parent.parent / "data" / "market.db"
    if not db_path.exists():
        return {"error": f"Database not found at {db_path}"}

    from src.data.db import Database

    db = Database(f"sqlite:///{db_path}")
    start_dt = datetime.fromisoformat(start)
    end_dt = datetime.fromisoformat(end)
    resolved_slug = resolve_strategy_slug(strategy)

    # Auto-detect intraday mode from strategy metadata (slug prefix or StrategyTimeframe)
    if not intraday:
        from src.strategies.registry import is_intraday_strategy
        intraday = is_intraday_strategy(resolved_slug)

    # If no explicit params, load active params from registry (falls back to code defaults)
    if strategy_params is None:
        active_info = get_active_params_for_mcp(strategy=resolved_slug)
        if active_info.get("source") == "registry":
            strategy_params = active_info.get("params")

    clamped_params, param_warnings = ({} if strategy_params is None else strategy_params), []
    if strategy_params:
        from src.strategies.registry import validate_and_clamp

        clamped_params, param_warnings = validate_and_clamp(resolved_slug, strategy_params)

    from src.strategies.registry import get_bar_agg
    meta_bar_agg = get_bar_agg(resolved_slug)
    bar_agg = int((strategy_params or {}).get("bar_agg", meta_bar_agg))

    # -- Cache key + lookup (reuses _build_cache_key) --
    # initial_equity participates in the key now; previously the cache only
    # checked when equity exactly equalled 2_000_000.0, AND the key omitted
    # equity entirely, which let cached results from one capital level
    # silently leak to callers asking for another (the bug that made the
    # War Room playback diverge from MCP by ~70%).
    _ck = _build_cache_key(strategy, strategy_params, intraday, symbol, initial_equity)
    strategy_hash = _ck.strategy_hash
    _cost_note = _ck.cost_note
    _timeframe_str = _ck.timeframe_str
    _combined_notes = _ck.combined_notes
    strategy_code: str | None = None
    if strategy_hash:
        _, strategy_code = _compute_code_hash(resolved_slug)

    cached = lookup_backtest_cache(
        symbol, start, end, strategy, strategy_params, intraday, initial_equity,
    )
    if cached is not None:
        return cached

    # Pin-aware META: when QUANT_PINNED_EXECUTION is on, consult the active
    # candidate for the pinned source and reuse its META for spread-leg
    # routing so both the bar construction and the engine run against the
    # same source version. ``strategy_hash`` / ``strategy_code`` local vars
    # above refer to the CURRENT file (for the save_run payload), not the
    # pinned candidate, so we query the active pin explicitly here.
    _pin_hash: str | None = None
    _pin_code: str | None = None
    _pinned_meta: dict | None = None
    if _pin_enabled() and not force_current_file:
        _active_hash, _active_code, _active_meta = _fetch_active_pin(resolved_slug)
        if _active_hash and _active_code:
            _maybe_warn_drift(resolved_slug, _active_hash)
            _pin_hash = _active_hash
            _pin_code = _active_code
            try:
                _, _pinned_meta = resolve_factory_by_hash(
                    resolved_slug,
                    strategy_hash=_pin_hash,
                    strategy_code=_pin_code,
                )
            except (StrategyHashNotFound, PinnedExecutionError):
                _pinned_meta = _active_meta

    # Spread strategies: construct synthetic bars from two legs. The META's
    # declared legs (e.g. ['TX','TX_R2']) are the default, but callers may
    # override them for an account that deploys the same strategy on a
    # different underlying (e.g. MTX/MTX_R2). When overridden, shallow-clone
    # the meta so downstream components (cost model, leg serialization) see
    # the substituted symbols.
    spread_meta = _get_spread_meta(resolved_slug, pinned_meta=_pinned_meta)
    if spread_meta and spread_legs_override and len(spread_legs_override) == 2:
        spread_meta = {**spread_meta, "spread_legs": list(spread_legs_override)}
    spread_result: SpreadBarsResult | None = None
    if spread_meta:
        legs = spread_meta["spread_legs"]
        spread_result = _build_spread_bars(db, legs[0], legs[1], start_dt, end_dt, bar_agg)
        if spread_result.error:
            return {"error": f"Spread bar construction failed: {spread_result.error}"}
        raw = spread_result.spread_bars
    else:
        raw = _load_bars_for_tf(db, symbol, start_dt, end_dt, bar_agg)
    if not raw:
        return {"error": f"No data for {symbol} in {start}–{end}"}

    # Compute true daily ATR from bar high-low ranges
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

    trading_days = len(_daily_hl)
    bars_per_day = len(raw) / max(trading_days, 1)
    periods_per_year = bars_per_day * 252 if bars_per_day > 10 else 252.0
    runner = _build_runner(
        resolved_slug,
        clamped_params,
        periods_per_year=periods_per_year,
        initial_equity=initial_equity,
        instrument=symbol,
        spread_meta=spread_meta,
        strategy_hash=_pin_hash,
        strategy_code=_pin_code,
        force_current_file=force_current_file,
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
        force_flat_indices = _compute_force_flat_indices(timestamps, slug=resolved_slug)

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
    _last_close = raw[-1].close if raw else None
    base["trade_pnls"] = _extract_trade_pnls(result.trade_log, last_price=_last_close)
    base["trade_signals"] = _serialize_trade_log(result.trade_log)
    base["timeframe_minutes"] = bar_agg
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
    if strategy_hash is not None:
        base["strategy_hash"] = strategy_hash

    # Spread strategies: expose aligned R1/R2/spread bars + offset + legs so the
    # backtest page can render the same 3-panel view the live War Room uses.
    if spread_meta and spread_result is not None:
        def _bar_to_dict(b) -> dict:
            return {
                "timestamp": str(b.timestamp),
                "open": float(b.open),
                "high": float(b.high),
                "low": float(b.low),
                "close": float(b.close),
                "volume": float(b.volume),
            }
        base["spread_bars"] = [_bar_to_dict(b) for b in spread_result.spread_bars]
        base["spread_r1_bars"] = [_bar_to_dict(b) for b in spread_result.r1_aligned]
        base["spread_r2_bars"] = [_bar_to_dict(b) for b in spread_result.r2_aligned]
        base["spread_offset"] = float(spread_result.offset)
        base["spread_legs"] = list(spread_meta["spread_legs"])
    try:
        from src.strategies.param_registry import ParamRegistry

        registry = ParamRegistry()
        save_metrics = {**base.get("metrics", {}), "total_pnl": base.get("total_pnl"), "alpha": alpha}
        # Serialize result for cache — convert numpy arrays to lists
        _cache_base = dict(base)
        for _k in ("daily_returns", "bnh_returns"):
            if _k in _cache_base and hasattr(_cache_base[_k], "tolist"):
                _cache_base[_k] = _cache_base[_k].tolist()
        import json as _json

        def _np_default(obj):
            if hasattr(obj, "item"):
                return obj.item()
            if hasattr(obj, "tolist"):
                return obj.tolist()
            return str(obj)

        _result_json_str = _json.dumps(_cache_base, default=_np_default)
        run_id = registry.save_backtest_run(
            strategy=resolved_slug,
            symbol=symbol,
            params=strategy_params or {},
            metrics=save_metrics,
            source="mcp",
            tool="run_backtest_realdata",
            start=start,
            end=end,
            timeframe=_timeframe_str,
            notes=_cost_note,
            initial_capital=initial_equity,
            strategy_hash=strategy_hash,
            strategy_code=strategy_code,
            strategy_meta_json=_snapshot_meta_json(resolved_slug),
            result_json=_result_json_str,
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
    _cap = _HW["n_paths_cap"]
    clamped = min(n_paths, _cap)
    warning = f"n_paths clamped from {n_paths} to {_cap}" if n_paths > _cap else None

    resolved_slug = resolve_strategy_slug(strategy)
    clamped_params, param_warnings = ({} if strategy_params is None else strategy_params), []
    if strategy_params:
        from src.strategies.registry import validate_and_clamp

        clamped_params, param_warnings = validate_and_clamp(resolved_slug, strategy_params)

    from src.strategies.registry import get_bar_agg
    bar_agg = get_bar_agg(resolved_slug)
    path_config = _make_path_config(scenario, n_bars, timeframe, bar_agg)

    merged = dict(clamped_params)
    if "max_loss" not in merged:
        merged["max_loss"] = 500_000

    import time as _time
    _t0 = _time.perf_counter()
    mc_result = _run_mc_with_runner(resolved_slug, merged, clamped, path_config, timeframe, bar_agg)
    _elapsed = _time.perf_counter() - _t0

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
    result["_timing"] = getattr(mc_result, "_timing", None)
    return result


class _PicklableEngineFactory:
    """Picklable engine factory for parallel sweep/walk-forward workers.

    Replaces lambda closures that cannot cross process boundaries.
    The wrapped ``factory`` must be a module-level callable (returned by
    ``resolve_factory()``) so that it survives pickling.
    """

    __slots__ = ("factory", "base_params")

    def __init__(self, factory: Any, base_params: dict[str, Any]) -> None:
        self.factory = factory
        self.base_params = base_params

    def __call__(self, **overrides: Any) -> Any:
        return self.factory(**{**self.base_params, **overrides})


def _mc_single_path(args: tuple) -> tuple[float, float, float]:
    """Worker function for parallel MC. Must be at module level for pickling.

    Accepts a seed index instead of a pre-generated path array so that each
    worker generates its own path — avoids serializing large numpy arrays
    through the multiprocessing boundary.

    Supports three arg-tuple shapes for backward compatibility:
    - 5-tuple: (name, params, seed_idx, path_config, timeframe)
    - 6-tuple: + bar_agg
    - 8-tuple: + strategy_hash, strategy_code (pin-aware)
    """
    strategy_hash: str | None = None
    strategy_code: str | None = None
    if len(args) == 8:
        (strategy_name, strategy_params, seed_idx, path_config, timeframe,
         bar_agg, strategy_hash, strategy_code) = args
    elif len(args) == 6:
        strategy_name, strategy_params, seed_idx, path_config, timeframe, bar_agg = args
    else:
        strategy_name, strategy_params, seed_idx, path_config, timeframe = args
        bar_agg = 1
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

    # Pin-aware factory resolution. When strategy_hash/strategy_code come through
    # from the parent process, the worker compiles the pinned source locally (or
    # hits its per-process LRU cache on subsequent trials). Falls back to the
    # current file when no pin is present or the flag is off.
    factory, _ = resolve_factory_by_hash(
        strategy_name, strategy_hash=strategy_hash, strategy_code=strategy_code,
    )
    engine_factory = lambda: factory(**strategy_params)  # noqa: E731
    adapter = _get_adapter()
    from src.core.sizing import default_sizing_config
    runner = BacktestRunner(
        engine_factory, adapter,
        sizing_config=default_sizing_config(initial_equity=2_000_000.0),
    )
    bars, timestamps = _bars_from_path(path_array, path_config, timeframe, bar_agg)
    result = runner.run(bars, timestamps=timestamps)
    pnl = result.equity_curve[-1] - result.equity_curve[0]
    return (pnl, max_drawdown_pct(result.equity_curve), sharpe_ratio(result.equity_curve))


# ---------------------------------------------------------------------------
# Hardware-aware resource budgets
# ---------------------------------------------------------------------------
import os as _os


def _detect_total_ram_gb() -> float:
    """Return total RAM in GB without requiring psutil.

    Tries psutil first, then /proc/meminfo (Linux), then sysctl (macOS).
    Falls back to 4.0 GB only if all methods fail.
    """
    try:
        import psutil
        return psutil.virtual_memory().total / (1024 ** 3)
    except ImportError:
        pass
    try:
        with open("/proc/meminfo") as _f:
            for _line in _f:
                if _line.startswith("MemTotal:"):
                    return int(_line.split()[1]) / (1024 ** 2)  # kB → GB
    except OSError:
        pass
    try:
        import subprocess as _sp
        _r = _sp.run(["sysctl", "-n", "hw.memsize"], capture_output=True, text=True, timeout=2)
        if _r.returncode == 0:
            return int(_r.stdout.strip()) / (1024 ** 3)
    except Exception:
        pass
    return 4.0  # conservative fallback


def _classify_hardware() -> dict[str, Any]:
    """Detect hardware capacity and return resource budgets.

    Three tiers: powerful (dev workstation), moderate (mid server),
    constrained (small VPS).  Env vars override any auto-detected value.
    """
    cpu = _os.cpu_count() or 4
    total_ram_gb = _detect_total_ram_gb()

    if cpu >= 12 and total_ram_gb >= 32:
        tier = "powerful"
    elif (cpu >= 6 and total_ram_gb >= 16) or (cpu >= 16 and total_ram_gb >= 12):
        # Second branch: high-CPU machines with moderate RAM (e.g. 24-core/15 GB)
        # also qualify as moderate to avoid under-utilizing CPU headroom.
        tier = "moderate"
    else:
        tier = "constrained"

    _budgets: dict[str, dict[str, Any]] = {
        "powerful":    {"mc_workers": max(1, cpu // 2), "n_paths_cap": 2000, "memory_floor_gb": 4.0, "optimizer_n_jobs": max(1, cpu // 3)},
        "moderate":    {"mc_workers": max(1, cpu // 3), "n_paths_cap": 1000, "memory_floor_gb": 2.0, "optimizer_n_jobs": max(1, cpu // 4)},
        "constrained": {"mc_workers": max(1, cpu // 4), "n_paths_cap": 500,  "memory_floor_gb": 1.0, "optimizer_n_jobs": 1},
    }
    budget: dict[str, Any] = dict(_budgets[tier])
    budget["tier"] = tier
    budget["cpu_count"] = cpu
    budget["total_ram_gb"] = round(total_ram_gb, 1)

    # Env var overrides (operators can pin specific values)
    if v := _os.environ.get("QUANT_MC_WORKERS"):
        budget["mc_workers"] = int(v)
    if v := _os.environ.get("QUANT_N_PATHS_CAP"):
        budget["n_paths_cap"] = int(v)
    if v := _os.environ.get("QUANT_MEMORY_FLOOR_GB"):
        budget["memory_floor_gb"] = float(v)
    if v := _os.environ.get("QUANT_OPTIMIZER_JOBS"):
        budget["optimizer_n_jobs"] = int(v)

    return budget


_HW = _classify_hardware()
_MAX_MC_WORKERS = _HW["mc_workers"]

# Worker-pool dispatch:
#   1. QUANT_HOST_ROLE=production -> raise. Heavy compute is forbidden on the
#      trading VPS (defense in depth on top of QUANT_RAY_ADDRESS not being set).
#   2. QUANT_RAY_ADDRESS is set and reachable -> return a Ray-backed RayPool
#      that mimics ProcessPoolExecutor's submit()/map() surface.
#   3. Otherwise (dev/CI/laptop) -> fall back to a local ProcessPoolExecutor
#      using fork context, preserving the original "fork before asyncio starts"
#      invariant. Fork is safe here: the process has no background threads yet
#      (module import is single-threaded), so no asyncio lock can be inherited
#      in a locked state.
import multiprocessing as _mp
import os as _os
from concurrent.futures import ProcessPoolExecutor as _ProcessPoolExecutor
from typing import Any as _Any

_WORKER_POOL: _Any | None = None


def _get_worker_pool() -> _Any:
    """Return the module-level worker pool, creating it on first call.

    Returned object exposes ``.submit(fn, *args)`` (yielding a
    ``concurrent.futures.Future`` compatible with ``as_completed()``) and
    ``.map(fn, iterable)``. Concrete type is either ``ProcessPoolExecutor``
    or :class:`src.research.ray_executor.RayPool` depending on environment.
    """
    global _WORKER_POOL
    if _WORKER_POOL is not None:
        return _WORKER_POOL

    role = (_os.getenv("QUANT_HOST_ROLE") or "").strip().lower()
    if role == "production":
        raise RuntimeError(
            "heavy compute is disabled on the production host "
            "(QUANT_HOST_ROLE=production). Run research workloads on the WSL "
            "Ray cluster (set QUANT_RAY_ADDRESS) instead."
        )

    # Try Ray first if explicitly configured. We import lazily so that hosts
    # without ray installed (like the prod VPS) never try to import it.
    if (_os.getenv("QUANT_RAY_ADDRESS") or "").strip():
        try:
            from src.research.ray_client import RayUnavailable, get_research_ray
            from src.research.ray_executor import RayPool

            ray_module = get_research_ray()
            _WORKER_POOL = RayPool(ray_module, max_workers=_MAX_MC_WORKERS)
            return _WORKER_POOL
        except (ImportError, RayUnavailable) as exc:
            # Fall through to local ProcessPoolExecutor. The user explicitly
            # asked for Ray (set QUANT_RAY_ADDRESS) but it's not reachable —
            # log loudly so they notice instead of silently using local CPUs.
            import logging as _logging
            _logging.getLogger(__name__).warning(
                "QUANT_RAY_ADDRESS=%s is set but Ray is unreachable (%s). "
                "Falling back to local ProcessPoolExecutor.",
                _os.getenv("QUANT_RAY_ADDRESS"),
                exc,
            )

    ctx = _mp.get_context("fork")
    _WORKER_POOL = _ProcessPoolExecutor(max_workers=_MAX_MC_WORKERS, mp_context=ctx)
    # Warm up one worker immediately so the first real call pays no startup cost.
    # submit() is non-blocking; the future is never awaited here.
    _WORKER_POOL.submit(int, 0)
    return _WORKER_POOL


def _check_memory(min_available_gb: float | None = None) -> None:
    """Raise if available memory is below threshold.

    Uses hardware-tier-aware floor when min_available_gb is not specified.
    """
    effective_floor = min_available_gb if min_available_gb is not None else _HW["memory_floor_gb"]
    try:
        import psutil
        mem = psutil.virtual_memory()
        avail_gb = mem.available / (1024**3)
        if avail_gb < effective_floor:
            raise MemoryError(
                f"Only {avail_gb:.1f} GB available (need {effective_floor}). "
                f"Reduce n_paths or wait for other sessions to finish."
            )
    except ImportError:
        pass  # psutil not installed — skip check


def _run_mc_with_runner(
    strategy_name: str,
    strategy_params: dict[str, Any],
    n_paths: int,
    path_config: PathConfig,
    timeframe: str = "daily",
    bar_agg: int = 1,
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

    _check_memory()

    import time as _time
    _t_start = _time.perf_counter()

    # Parallelise whenever we have spare workers.
    # The old gate (timeframe=="intraday" or tier=="powerful") left daily strategies
    # single-threaded on every non-powerful machine — intentionally removed.
    # Threshold of 20 prevents ProcessPoolExecutor spawn overhead from dominating
    # on tiny runs where each path takes < 1 ms.
    use_mp = n_paths >= 20 and _MAX_MC_WORKERS > 1
    workers_used = 1

    # Pin-aware: resolve the active-candidate hash + code once in the parent so
    # every worker gets the same source version. ``resolve_factory_by_hash``
    # honours ``QUANT_PINNED_EXECUTION`` and falls through to the current file
    # when no pin is available.
    _mc_pin_hash: str | None = None
    _mc_pin_code: str | None = None
    if _pin_enabled():
        _mc_active_hash, _mc_active_code, _ = _fetch_active_pin(strategy_name)
        if _mc_active_hash and _mc_active_code:
            _maybe_warn_drift(strategy_name, _mc_active_hash)
            _mc_pin_hash = _mc_active_hash
            _mc_pin_code = _mc_active_code

    if use_mp:
        workers_used = min(n_paths, _MAX_MC_WORKERS)
        work_items = [
            (strategy_name, strategy_params, i, path_config, timeframe, bar_agg,
             _mc_pin_hash, _mc_pin_code)
            for i in range(n_paths)
        ]
        pool = _get_worker_pool()
        results_list = list(pool.map(_mc_single_path, work_items))
    else:
        from src.simulator.backtester import BacktestRunner
        from src.simulator.metrics import max_drawdown_pct, sharpe_ratio

        factory, _ = resolve_factory_by_hash(
            strategy_name,
            strategy_hash=_mc_pin_hash,
            strategy_code=_mc_pin_code,
        )
        engine_factory = lambda: factory(**strategy_params)  # noqa: E731
        adapter = _get_adapter()
        from src.core.sizing import default_sizing_config
        runner = BacktestRunner(
            engine_factory, adapter,
            sizing_config=default_sizing_config(initial_equity=2_000_000.0),
        )
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
            bars, timestamps = _bars_from_path(path, path_config, timeframe, bar_agg)
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

    _elapsed = _time.perf_counter() - _t_start
    mc_res = MonteCarloResult(
        terminal_pnl_distribution=terminal_pnls,
        percentiles=percentiles,
        win_rate=wr,
        max_drawdown_distribution=max_dds,
        sharpe_distribution=sharpes,
        ruin_probability=ruin_prob,
    )
    mc_res._timing = {
        "elapsed_s": round(_elapsed, 2),
        "use_mp": use_mp,
        "workers": workers_used,
        "n_paths": n_paths,
        "per_path_ms": round(_elapsed / n_paths * 1000, 1),
    }
    return mc_res


def run_sweep_for_mcp(
    base_params: dict[str, Any],
    sweep_params: dict[str, Any],
    strategy: str = "pyramid",
    n_samples: int | None = None,  # kept for backward compat; prefer n_trials
    metric: str = "sortino",
    mode: str = "production_intent",
    scenario: str = "strong_bull",
    symbol: str | None = None,
    start: str | None = None,
    end: str | None = None,
    is_fraction: float = 0.8,
    min_trade_count: int | None = None,
    min_expectancy: float = 0.0,
    min_oos_metric: float = 0.0,
    train_bars: int | None = None,
    test_bars: int | None = None,
    n_bars: int | None = None,
    timeframe: str = "daily",
    require_real_data: bool = True,
) -> dict[str, Any]:
    """Run Optuna Bayesian (TPE) parameter optimization.

    min_trade_count: When None (default), auto-resolved from strategy's
        holding_period and current optimization level.
    """
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

    # Resolve holding-period-aware min_trade_count if not explicitly provided
    resolved_slug = resolve_strategy_slug(strategy)
    from src.strategies import get_thresholds_for_strategy
    _stage_th = get_thresholds_for_strategy(resolved_slug)
    if min_trade_count is None:
        min_trade_count = _stage_th.min_trade_count

    _check_memory()

    from datetime import datetime
    from pathlib import Path
    from statistics import mean as _mean

    from src.data.db import Database
    from src.simulator.price_gen import generate_paths
    from src.simulator.strategy_optimizer import StrategyOptimizer

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
        db_path = Path(__file__).resolve().parent.parent.parent / "data" / "market.db"
        if not db_path.exists():
            return {"error": f"Database not found at {db_path}"}
        db = Database(f"sqlite:///{db_path}")
        start_dt = datetime.fromisoformat(start)
        end_dt = datetime.fromisoformat(end)
        # Spread-aware bar loading
        sweep_spread_meta = _get_spread_meta(resolved_slug)
        if sweep_spread_meta:
            legs = sweep_spread_meta["spread_legs"]
            _sweep_spread = _build_spread_bars(db, legs[0], legs[1], start_dt, end_dt, sweep_bar_agg)
            if _sweep_spread.error:
                return {"error": f"Spread bar construction failed: {_sweep_spread.error}"}
            raw = _sweep_spread.spread_bars
        else:
            raw = _load_bars_for_tf(db, symbol, start_dt, end_dt, sweep_bar_agg)
        if not raw:
            return {"error": f"No data for {symbol} in {start}–{end}"}
        # Compute true daily ATR from bar high-low ranges
        _daily_hl_sweep: dict[str, tuple[float, float]] = {}
        for b in raw:
            d = b.timestamp.date() if hasattr(b.timestamp, "date") else str(b.timestamp)[:10]
            if d not in _daily_hl_sweep:
                _daily_hl_sweep[d] = (b.high, b.low)
            else:
                prev = _daily_hl_sweep[d]
                _daily_hl_sweep[d] = (max(prev[0], b.high), min(prev[1], b.low))
        daily_ranges = [hi - lo for hi, lo in _daily_hl_sweep.values() if hi > lo]
        daily_atr = _mean(daily_ranges) if daily_ranges else _mean(b.high - b.low for b in raw)
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
        path_config = _make_path_config(scenario, n_bars, timeframe, sweep_bar_agg)
        paths = generate_paths(1, path_config)
        bars, timestamps = _bars_from_path(paths[0], path_config, timeframe, sweep_bar_agg)
        source_label = f"synthetic:{scenario}"

    # Compute force_flat_indices for intraday strategies (real data only)
    from src.strategies.registry import is_intraday_strategy
    sweep_force_flat: set[int] | None = None
    if is_intraday_strategy(resolved_slug) and len(timestamps) > 1:
        sweep_force_flat = _compute_force_flat_indices(timestamps, slug=resolved_slug)

    adapter = _get_adapter()
    # Sweep writes a NEW pin with hash == current file hash. If we pinned to an
    # old candidate's code, the best params would be tuned against stale logic
    # and then saved referencing the current file. force_current_file=True makes
    # the optimizer execute the edited source while still producing a picklable
    # factory for forkserver workers (compiled via the pinned loader).
    factory, _sweep_pinned_meta = resolve_factory_by_hash(
        resolved_slug, force_current_file=True,
    )
    # Use spread-aware fill model when applicable
    sweep_fill_model = None
    if sweep_spread_meta:
        from src.simulator.fill_model import ImpactParams, MarketImpactFillModel
        cost_per_fill = sweep_spread_meta.get("spread_cost_per_fill", 700.0)
        sweep_fill_model = MarketImpactFillModel(params=ImpactParams(
            spread_bps=0.0, commission_bps=0.0,
            commission_fixed_per_contract=cost_per_fill, k=0.0,
        ))
    optimizer = StrategyOptimizer(
        adapter,
        fill_model=sweep_fill_model,
        mode=mode,
        min_trade_count=min_trade_count,
        min_expectancy=min_expectancy,
        min_oos_objective=min_oos_metric,
        n_jobs=_HW["optimizer_n_jobs"],
        worker_pool=_get_worker_pool() if _HW["optimizer_n_jobs"] > 1 else None,
    )
    walk_forward_summary: dict[str, Any] | None = None

    # Build param_defs from PARAM_SCHEMA for Optuna optimization.
    # sweep_params can be:
    #   - list of param names (bounds from schema)
    #   - dict of param_name → value list (legacy grid: auto-infer bounds)
    #   - dict of param_name → {min, max, ...} (explicit bounds)
    schema = get_strategy_parameter_schema(resolved_slug)
    schema_params = schema.get("parameters", {})

    param_defs: dict[str, dict] = {}
    if isinstance(sweep_params, list):
        for name in sweep_params:
            spec = schema_params.get(name, {})
            if "min" not in spec or "max" not in spec:
                return {"error": f"Param '{name}' has no min/max in schema — cannot optimize"}
            param_defs[name] = {
                "type": spec.get("type", "float"),
                "min": spec["min"],
                "max": spec["max"],
                "step": spec.get("step"),
            }
    elif isinstance(sweep_params, dict):
        for name, v in sweep_params.items():
            if isinstance(v, dict) and "min" in v and "max" in v:
                param_defs[name] = v
            elif isinstance(v, (list, tuple)):
                lo, hi = float(min(v)), float(max(v))
                spec = schema_params.get(name, {})
                param_defs[name] = {
                    "type": spec.get("type", "float"),
                    "min": lo,
                    "max": hi,
                    "step": spec.get("step"),
                }
            else:
                return {"error": f"sweep_params['{name}'] must be a list, bounds dict, or param name list"}

    effective_n_trials = n_samples or 100

    if mode == "production_intent":
        effective_train = train_bars or max(int(len(bars) * 0.6), 50)
        effective_test = test_bars or max(int(len(bars) * 0.2), 20)
        if effective_train + effective_test <= len(bars):
            try:
                wf = optimizer.walk_forward(
                    engine_factory=_PicklableEngineFactory(factory, clamped_base),
                    param_defs=param_defs,
                    bars=bars,
                    timestamps=timestamps,
                    train_bars=effective_train,
                    test_bars=effective_test,
                    base_params=clamped_base,
                    n_trials=effective_n_trials,
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

    result = optimizer.optuna_search(
        engine_factory=_PicklableEngineFactory(factory, clamped_base),
        param_defs=param_defs,
        bars=bars,
        timestamps=timestamps,
        base_params=clamped_base,
        n_trials=effective_n_trials,
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
        search = "optuna"
        # Build notes with cost + timeframe info (matches run_backtest_realdata format)
        _is_intra = timeframe in ("intraday", "1m")
        _sweep_tf_str = f"{sweep_bar_agg}min{'|intraday' if _is_intra else ''}" if mode == "production_intent" and symbol else None
        # Include cost info in notes so frontend can display it
        _sweep_cost_config = get_instrument_cost_config(symbol)
        _sweep_slip_bps = clamped_base.get("slippage_bps", _sweep_cost_config.slippage_bps)
        _sweep_comm_fixed = clamped_base.get("commission_fixed_per_contract", _sweep_cost_config.commission_per_contract)
        _sweep_cost_note = f"sbps={_sweep_slip_bps}|cfix={_sweep_comm_fixed}"
        _sweep_tf_note = f"tf={_sweep_tf_str}" if _sweep_tf_str else None
        _sweep_notes = "; ".join(filter(None, [_sweep_cost_note, _sweep_tf_note]))
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
            strategy_meta_json=_snapshot_meta_json(resolved_slug),
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
                instrument=symbol,
                spread_meta=sweep_spread_meta,
                force_current_file=True,
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
        "quality_thresholds_applied": _stage_th.to_dict(),
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


def _run_single_sensitivity_grid_point(
    args: tuple[str, float, str, dict[str, Any]],
) -> tuple[str, float, float]:
    """Worker: run one (param_name, grid_value) backtest for sensitivity check.

    Module-level so it's picklable for ProcessPoolExecutor and serializable for
    Ray. Returns the inputs alongside the sharpe so results can be regrouped
    by param after the parallel map() completes.
    """
    param_name, grid_val, slug, test_params = args
    result = run_backtest_for_mcp(
        scenario="strong_bull",
        strategy=slug,
        strategy_params=test_params,
        n_bars=252,
        timeframe="daily",
    )
    sharpe = float(result.get("metrics", {}).get("sharpe", 0.0))
    return param_name, grid_val, sharpe


def _run_single_stress_scenario(args: tuple) -> dict[str, Any]:
    """Worker: run one stress scenario end-to-end.

    Module-level so the worker pool (Ray remote or fork-pool subprocess) can
    pickle / serialize it. Self-contained imports; no closure state.

    args = (slug, merged_params, scenario_name, bar_agg, pin_hash, pin_code)
    """
    slug, merged_params, scenario_name, bar_agg, pin_hash, pin_code = args

    from src.adapters.taifex import TaifexAdapter
    from src.core.sizing import default_sizing_config
    from src.simulator.backtester import BacktestRunner
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

    scenario_factories = {
        "gap_down": gap_down_scenario,
        "slow_bleed": slow_bleed_scenario,
        "flash_crash": flash_crash_scenario,
        "vol_regime_shift": vol_regime_shift_scenario,
        "liquidity_crisis": liquidity_crisis_scenario,
    }
    scenario_obj = scenario_factories[scenario_name]()

    factory, _ = resolve_factory_by_hash(
        slug, strategy_hash=pin_hash, strategy_code=pin_code,
    )
    engine_factory = lambda: factory(**merged_params)  # noqa: E731
    runner = BacktestRunner(
        engine_factory, TaifexAdapter(),
        sizing_config=default_sizing_config(initial_equity=2_000_000.0),
    )

    prices = _generate_scenario_prices(scenario_obj, 20000.0)
    # bar_agg is the per-bar minutes count from the strategy registry. The
    # TAIFEX session is ~1065 trading minutes/day. For an intraday strategy
    # (bar_agg in 1..1064) we get N bars per synthetic day. For a daily-bar
    # strategy (bar_agg >= 1065 — e.g. compounding_trend_long has bar_agg=1440)
    # the integer division 1065 // bar_agg is 0, which would divide-by-zero
    # in _prices_to_intraday_bars; treat those as one-bar-per-price (daily).
    if bar_agg > 1:
        bars_per_day = 1065 // bar_agg
    else:
        bars_per_day = 0
    if bars_per_day >= 1:
        bars, timestamps = _prices_to_intraday_bars(prices, bars_per_day)
    else:
        bars, timestamps = _prices_to_bars(prices)
    result = runner.run(bars, timestamps=timestamps)

    return {
        "scenario": scenario_obj.name,
        "final_pnl": result.equity_curve[-1] - result.equity_curve[0],
        "max_drawdown": result.metrics.get("max_drawdown_pct", 0.0),
        "circuit_breaker_triggered": any(
            f.reason == "circuit_breaker" for f in result.trade_log
        ),
        "stops_triggered": [
            f.reason for f in result.trade_log if "stop" in f.reason.lower()
        ],
    }


def run_stress_for_mcp(
    scenarios: list[str] | None = None,
    strategy_params: dict[str, Any] | None = None,
    strategy: str = "pyramid",
) -> dict[str, Any]:
    """Run stress test scenarios.

    Each scenario is independent; when 2+ scenarios are requested they run in
    parallel via the shared worker pool (Ray on WSL, ProcessPoolExecutor
    elsewhere, or refused on the production host).
    """
    all_scenarios = {
        "gap_down", "slow_bleed", "flash_crash", "vol_regime_shift", "liquidity_crisis",
    }
    names = scenarios or sorted(all_scenarios)
    invalid = [n for n in names if n not in all_scenarios]
    if invalid:
        return {"error": f"Unknown scenarios: {invalid}. Available: {sorted(all_scenarios)}"}

    resolved_slug = resolve_strategy_slug(strategy)
    clamped_params, param_warnings = ({} if strategy_params is None else strategy_params), []
    if strategy_params:
        from src.strategies.registry import validate_and_clamp

        clamped_params, param_warnings = validate_and_clamp(resolved_slug, strategy_params)

    merged = dict(clamped_params)
    if "max_loss" not in merged:
        merged["max_loss"] = 500_000

    # Pin-aware: resolve once in the parent so every worker uses the same source.
    pin_hash: str | None = None
    pin_code: str | None = None
    if _pin_enabled():
        active_hash, active_code, _ = _fetch_active_pin(resolved_slug)
        if active_hash and active_code:
            _maybe_warn_drift(resolved_slug, active_hash)
            pin_hash, pin_code = active_hash, active_code

    bar_agg = _get_stress_bar_agg(resolved_slug)
    work_items = [
        (resolved_slug, merged, name, bar_agg, pin_hash, pin_code)
        for name in names
    ]

    if len(work_items) <= 1:
        results = [_run_single_stress_scenario(work_items[0])] if work_items else []
    else:
        pool = _get_worker_pool()
        results = list(pool.map(_run_single_stress_scenario, work_items))

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

    db_path = Path(__file__).resolve().parent.parent.parent / "data" / "market.db"
    if not db_path.exists():
        return {"error": f"Database not found at {db_path}"}

    from src.data.db import Database

    db = Database(f"sqlite:///{db_path}")
    start_dt = _dt.fromisoformat(start)
    end_dt = _dt.fromisoformat(end)
    from src.strategies.registry import get_bar_agg
    meta_bar_agg = get_bar_agg(resolved_slug)
    bar_agg = int((strategy_params or {}).get("bar_agg", meta_bar_agg))

    # Pin-aware resolution: resolve the active candidate's hash + code once
    # so every fold's runner executes the same pinned source. Falls through
    # to current-file behavior when QUANT_PINNED_EXECUTION is off or no pin
    # exists.
    _wf_pin_hash: str | None = None
    _wf_pin_code: str | None = None
    _wf_pinned_meta: dict | None = None
    if _pin_enabled():
        _wf_active_hash, _wf_active_code, _wf_active_meta = _fetch_active_pin(resolved_slug)
        if _wf_active_hash and _wf_active_code:
            _maybe_warn_drift(resolved_slug, _wf_active_hash)
            _wf_pin_hash = _wf_active_hash
            _wf_pin_code = _wf_active_code
            try:
                _, _wf_pinned_meta = resolve_factory_by_hash(
                    resolved_slug,
                    strategy_hash=_wf_pin_hash,
                    strategy_code=_wf_pin_code,
                )
            except (StrategyHashNotFound, PinnedExecutionError):
                _wf_pinned_meta = _wf_active_meta

    # Spread-aware bar loading (prefer pinned META so legs stay consistent).
    wf_spread_meta = _get_spread_meta(resolved_slug, pinned_meta=_wf_pinned_meta)
    if wf_spread_meta:
        legs = wf_spread_meta["spread_legs"]
        _wf_spread = _build_spread_bars(db, legs[0], legs[1], start_dt, end_dt, bar_agg)
        if _wf_spread.error:
            return {"error": f"Spread bar construction failed: {_wf_spread.error}"}
        raw = _wf_spread.spread_bars
    else:
        raw = _load_bars_for_tf(db, symbol, start_dt, end_dt, bar_agg)
    if not raw:
        return {"error": f"No data for {symbol} in {start}–{end}"}

    from statistics import mean as _mean

    # Compute true daily ATR from bar high-low ranges (matching
    # run_backtest_realdata), NOT per-bar ranges which are ~6-8x smaller
    # for intraday bars and produce impossibly tight stops.
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
            spread_meta=wf_spread_meta,
            strategy_hash=_wf_pin_hash,
            strategy_code=_wf_pin_code,
        )
        is_force_flat: set[int] | None = None
        if is_intraday:
            is_force_flat = _compute_force_flat_indices(is_ts, slug=resolved_slug)
        is_result = is_runner.run(is_bars, timestamps=is_ts, force_flat_indices=is_force_flat)
        is_sharpe = is_result.metrics.get("sharpe", 0.0)

        # OOS: run backtest on OOS window with same params
        oos_runner = _build_runner(
            resolved_slug, strategy_params, periods_per_year=ppy,
            initial_equity=initial_equity, instrument=symbol,
            spread_meta=wf_spread_meta,
            strategy_hash=_wf_pin_hash,
            strategy_code=_wf_pin_code,
        )
        oos_force_flat: set[int] | None = None
        if is_intraday:
            oos_force_flat = _compute_force_flat_indices(oos_ts, slug=resolved_slug)
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

    # Resolve holding-period-aware quality gate thresholds
    from src.strategies import get_thresholds_for_strategy
    stage_thresholds = get_thresholds_for_strategy(resolved_slug)
    thresholds_dict = stage_thresholds.to_dict()

    wf_result = build_walk_forward_result(fold_results, thresholds=thresholds_dict)

    return {
        "strategy": strategy,
        "n_folds": n_folds,
        "session": session,
        "aggregate_oos_sharpe": wf_result.aggregate_oos_sharpe,
        "mean_overfit_ratio": wf_result.mean_overfit_ratio,
        "overfit_flag": wf_result.overfit_flag,
        "passed": wf_result.passed,
        "failure_reasons": wf_result.failure_reasons,
        "quality_thresholds_applied": thresholds_dict,
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
    instrument: str = "",
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
    param_defs = schema.get("parameters", {})

    if best_params is None:
        active = get_active_params_for_mcp(strategy=resolved_slug)
        best_params = active.get("params", {})

    if not best_params:
        return {
            "error": "No parameters provided and no active candidate found",
            "passed": False,
            "per_param": [],
        }

    # Step 2: Build a flat list of (param, grid_val) work items across ALL parameters,
    # then dispatch them through the shared worker pool. The original nested
    # loop ran 5 params × 5 grid points = 25 backtests serially; the flat layout
    # lets every backtest run on its own Ray worker / process at once.
    pct_range = perturbation_pct / 100.0
    grids_by_param: dict[str, list[float]] = {}
    work_items: list[tuple[str, float, str, dict[str, Any]]] = []

    for param_name, param_value in best_params.items():
        if param_name not in param_defs:
            continue  # Skip unknown params

        param_def = param_defs[param_name]
        grid = generate_perturbation_grid(
            current_value=float(param_value),
            pct_range=pct_range,
            n_steps=n_steps,
            is_integer=param_def.get("type") == "int",
            min_bound=float(param_def["min"]) if param_def.get("min") is not None else None,
            max_bound=float(param_def["max"]) if param_def.get("max") is not None else None,
        )
        grids_by_param[param_name] = grid
        for grid_val in grid:
            test_params = {**best_params, param_name: grid_val}
            work_items.append((param_name, grid_val, resolved_slug, test_params))

    if not work_items:
        return {
            "strategy": strategy,
            "perturbation_pct": perturbation_pct,
            "n_steps": n_steps,
            "passed": True,
            "likely_overfit": False,
            "per_param": [],
            "max_degradation_pct": 0.0,
        }

    if len(work_items) <= 1:
        flat_results = [_run_single_sensitivity_grid_point(work_items[0])]
    else:
        pool = _get_worker_pool()
        flat_results = list(pool.map(_run_single_sensitivity_grid_point, work_items))

    # Re-group flat results back into per-parameter lists, preserving the
    # original grid order (pool.map() returns results in input order, so the
    # subsequence per param is already correctly ordered).
    sharpe_by_param: dict[str, list[float]] = {p: [] for p in grids_by_param}
    baseline_by_param: dict[str, float | None] = {p: None for p in grids_by_param}
    for param_name, grid_val, sharpe in flat_results:
        sharpe_by_param[param_name].append(sharpe)
        if abs(grid_val - float(best_params[param_name])) < 1e-6:
            baseline_by_param[param_name] = sharpe

    sensitivity_results = []
    for param_name, grid in grids_by_param.items():
        baseline_sharpe = baseline_by_param[param_name]
        if baseline_sharpe is None:
            baseline_sharpe = float(best_params[param_name])
        sen_result = analyze_param_sensitivity(
            param_name=param_name,
            grid_values=grid,
            sharpe_values=sharpe_by_param[param_name],
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
    instrument: str = "",
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


def run_portfolio_optimization_for_mcp(
    strategies: list[dict[str, Any]],
    symbol: str = "TX",
    start: str = "2025-08-01",
    end: str = "2026-03-14",
    initial_equity: float = 2_000_000.0,
    min_weight: float = 0.10,
    slippage_bps: float = 0.0,
    commission_bps: float = 0.0,
    commission_fixed_per_contract: float = 0.0,
) -> dict[str, Any]:
    """Run portfolio weight optimization across multiple strategies.

    Backtests each strategy on real data, then finds optimal weight
    allocations for max Sharpe, max return, min drawdown, and risk parity.
    """
    from dataclasses import asdict

    if len(strategies) < 2:
        return {"error": "Need at least 2 strategies for portfolio optimization"}
    if len(strategies) > 5:
        return {"error": "Maximum 5 strategies supported"}

    cost_params: dict[str, Any] = {}
    if slippage_bps:
        cost_params["slippage_bps"] = slippage_bps
    if commission_bps:
        cost_params["commission_bps"] = commission_bps
    if commission_fixed_per_contract:
        cost_params["commission_fixed_per_contract"] = commission_fixed_per_contract

    # Each strategy's backtest is independent — dispatch through the shared
    # worker pool (Ray on WSL, ProcessPoolExecutor elsewhere). The helper
    # already merges cost_params via its extra_params arg.
    daily_returns, bt_errors = _collect_portfolio_daily_returns(
        strategies=strategies,
        symbol=symbol,
        start=start,
        end=end,
        initial_equity=initial_equity,
        extra_params=cost_params or None,
    )

    if bt_errors:
        return {"error": f"Backtest failures: {'; '.join(bt_errors)}"}
    if len(daily_returns) < 2:
        return {"error": "Need at least 2 successful backtests for optimization"}

    from src.core.portfolio_optimizer import PortfolioOptimizer

    try:
        optimizer = PortfolioOptimizer(
            daily_returns=daily_returns,
            initial_capital=initial_equity,
            min_weight=min_weight,
        )
        result = optimizer.optimize()
    except Exception as exc:
        return {"error": f"Optimization failed: {exc}"}

    output = {
        "strategy_slugs": result.strategy_slugs,
        "max_sharpe": asdict(result.max_sharpe),
        "max_return": asdict(result.max_return),
        "min_drawdown": asdict(result.min_drawdown),
        "risk_parity": asdict(result.risk_parity),
        "equal_weight": asdict(result.equal_weight),
        "pareto_front": [asdict(p) for p in result.pareto_front],
        "correlation_matrix": result.correlation_matrix,
        "individual_metrics": result.individual_metrics,
        "n_days": result.n_days,
    }

    # Auto-persist to portfolio store
    try:
        from src.core.portfolio_store import PortfolioStore
        store = PortfolioStore()
        run_id = store.save_optimization(
            result=output, symbol=symbol, start=start, end=end,
            initial_capital=initial_equity, min_weight=min_weight,
            slippage_bps=slippage_bps,
            commission_bps=commission_bps,
            commission_fixed_per_contract=commission_fixed_per_contract,
        )
        store.close()
        output["run_id"] = run_id
    except Exception as exc:
        output["persistence_warning"] = f"Failed to save to DB: {exc}"

    return output


# ---------------------------------------------------------------------------
# Portfolio-level MCP tools (walk-forward, risk report, promotion)
# ---------------------------------------------------------------------------

def _run_single_portfolio_backtest(
    args: tuple[str, dict[str, Any] | None, str, str, str, float, dict[str, Any] | None],
) -> tuple[str, list[float] | None, str | None]:
    """Worker: real-data backtest for one portfolio strategy slot.

    Module-level so it's picklable for ProcessPoolExecutor and serializable
    for Ray. Returns ``(slug, daily_returns_list_or_None, error_str_or_None)``
    so the parent can re-assemble the final {slug: array} mapping while
    preserving error messages.

    args = (slug, params, symbol, start, end, initial_equity, extra_params)
    """
    slug, params, symbol, start, end, initial_equity, extra_params = args

    merged: dict[str, Any] | None
    if extra_params:
        merged = dict(params or {})
        merged.update(extra_params)
    else:
        merged = params

    resolved = resolve_strategy_slug(slug)
    try:
        bt = run_backtest_realdata_for_mcp(
            symbol=symbol,
            start=start,
            end=end,
            strategy=resolved,
            strategy_params=merged,
            initial_equity=initial_equity,
        )
    except Exception as exc:  # noqa: BLE001 - surface backtest failures to caller
        return slug, None, f"{slug}: {exc}"
    if "error" in bt:
        return slug, None, f"{slug}: {bt['error']}"
    dr = bt.get("daily_returns", [])
    if hasattr(dr, "tolist"):
        dr = dr.tolist()
    if not dr:
        return slug, None, f"{slug}: no daily returns produced"
    return slug, dr, None


def _collect_portfolio_daily_returns(
    strategies: list[dict[str, Any]],
    symbol: str,
    start: str,
    end: str,
    initial_equity: float,
    extra_params: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """Backtest each strategy on real data; return ({slug: daily_returns_array}, errors).

    Each strategy's backtest is independent, so we dispatch them through the
    shared worker pool — typically 2-5 strategies in a portfolio, all running
    in parallel on the WSL Ray cluster.
    """
    import numpy as np

    work_items = [
        (entry["slug"], entry.get("params"), symbol, start, end, initial_equity, extra_params)
        for entry in strategies
    ]
    if not work_items:
        return {}, []

    if len(work_items) == 1:
        flat = [_run_single_portfolio_backtest(work_items[0])]
    else:
        pool = _get_worker_pool()
        flat = list(pool.map(_run_single_portfolio_backtest, work_items))

    daily_returns: dict[str, Any] = {}
    errors: list[str] = []
    for slug, dr_list, err in flat:
        if err is not None:
            errors.append(err)
            continue
        if dr_list:
            daily_returns[slug] = np.array(dr_list, dtype=np.float64)
    return daily_returns, errors


def run_portfolio_walk_forward_for_mcp(
    strategies: list[dict[str, Any]],
    symbol: str = "TX",
    start: str = "2024-06-01",
    end: str = "2026-04-10",
    initial_equity: float = 2_000_000.0,
    min_weight: float = 0.05,
    n_folds: int = 3,
    oos_fraction: float = 0.2,
    objective: str = "max_sharpe",
    link_run_id: int | None = None,
) -> dict[str, Any]:
    """Portfolio-level expanding-window walk-forward validation.

    When ``link_run_id`` is supplied, the walk-forward result is persisted
    to ``portfolio_opt.db`` with a foreign key back to the named
    ``portfolio_runs`` row so downstream audit can trace weights + OOS
    metrics back to the same strategy+param set. When ``link_run_id`` is
    ``None``, persistence still happens (for traceability) but without a
    run_id linkage.
    """
    from src.simulator.portfolio_walk_forward import PortfolioWalkForward

    if len(strategies) < 2:
        return {"error": "Need at least 2 strategies for portfolio walk-forward"}
    if len(strategies) > 5:
        return {"error": "Maximum 5 strategies supported"}

    daily_returns, errors = _collect_portfolio_daily_returns(
        strategies=strategies,
        symbol=symbol,
        start=start,
        end=end,
        initial_equity=initial_equity,
    )
    if errors:
        return {"error": f"Backtest failures: {'; '.join(errors)}"}
    if len(daily_returns) < 2:
        return {"error": "Need at least 2 successful backtests"}

    try:
        wf = PortfolioWalkForward(
            daily_returns=daily_returns,
            initial_capital=initial_equity,
            min_weight=min_weight,
            n_folds=n_folds,
            oos_fraction=oos_fraction,
            objective=objective,
        )
        result = wf.run()
    except Exception as exc:
        return {"error": f"Walk-forward failed: {exc}"}

    output = result.as_dict()

    # Auto-persist to portfolio_opt.db for audit / history
    try:
        from src.core.portfolio_store import PortfolioStore
        store = PortfolioStore()
        wf_id = store.save_walk_forward(
            result=output,
            symbol=symbol,
            start=start,
            end=end,
            n_folds=n_folds,
            oos_fraction=oos_fraction,
            run_id=link_run_id,
        )
        store.close()
        output["wf_id"] = wf_id
        if link_run_id is not None:
            output["run_id"] = link_run_id
    except Exception as exc:
        output["persistence_warning"] = f"Failed to save walk-forward: {exc}"
    return output


def activate_portfolio_allocation_for_mcp(
    run_id: int,
    objective: str = "max_sharpe",
) -> dict[str, Any]:
    """Mark a single allocation row (run_id, objective) as the selected
    portfolio allocation.

    Parallels ``activate_candidate`` for per-strategy params. On success,
    ``portfolio_allocations.is_selected`` becomes ``1`` for the named row
    and ``0`` for all other objectives in the same run. Returns the
    activated allocation record or an error dict.
    """
    from src.core.portfolio_store import PortfolioStore

    store = PortfolioStore()
    try:
        run = store.get_run(run_id)
        if run is None:
            return {"error": f"run_id {run_id} not found in portfolio_opt.db"}
        ok = store.select_allocation(run_id, objective)
        if not ok:
            return {
                "error": (
                    f"No allocation for run_id={run_id} objective={objective!r}. "
                    f"Available objectives: {sorted(run.get('allocations', {}).keys())}"
                ),
            }
        selected = store.get_selected_allocation(run_id)
        return {
            "status": "activated",
            "run_id": run_id,
            "objective": objective,
            "weights": selected.get("weights") if selected else None,
            "sharpe": selected.get("sharpe") if selected else None,
            "selected_at": selected.get("selected_at") if selected else None,
        }
    finally:
        store.close()


def run_portfolio_risk_report_for_mcp(
    strategies: list[dict[str, Any]],
    weights: dict[str, float],
    symbol: str = "TX",
    start: str = "2024-06-01",
    end: str = "2026-04-10",
    initial_equity: float = 2_000_000.0,
    thresholds: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Portfolio-level 5-layer risk report.

    ``weights`` must sum to ~1.0 and cover all strategy slugs in
    ``strategies``.
    """
    from src.simulator.portfolio_risk_report import PortfolioRiskReport

    if len(strategies) < 2:
        return {"error": "Need at least 2 strategies for portfolio risk report"}

    daily_returns, errors = _collect_portfolio_daily_returns(
        strategies=strategies,
        symbol=symbol,
        start=start,
        end=end,
        initial_equity=initial_equity,
    )
    if errors:
        return {"error": f"Backtest failures: {'; '.join(errors)}"}

    slug_set = set(daily_returns.keys())
    weight_slugs = set(weights.keys())
    if slug_set != weight_slugs:
        return {
            "error": (
                f"weights keys {sorted(weight_slugs)} must match "
                f"strategy slugs {sorted(slug_set)}"
            ),
        }

    try:
        report = PortfolioRiskReport(
            daily_returns=daily_returns,
            weights=weights,
            initial_capital=initial_equity,
            thresholds=thresholds,
        )
        result = report.run()
    except Exception as exc:
        return {"error": f"Risk report failed: {exc}"}
    return result.as_dict()


def promote_portfolio_optimization_level_for_mcp(
    portfolio_name: str,
    target_level: int,
    gate_results: dict[str, Any],
    portfolio_spec: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Attempt to promote a portfolio to ``target_level`` (L0=0 … L3=3).

    On successful promotion, writes the new level + ``gate_results`` into
    ``config/portfolios/<portfolio_name>.toml``. When the file does not
    yet exist, ``portfolio_spec`` (optional) supplies the initial
    ``[portfolio]`` metadata (name, symbol, strategies, kelly config).
    """
    from src.simulator.portfolio_promotion import (
        PortfolioOptimizationLevel,
        load_portfolio_config,
        promote_portfolio,
        save_portfolio_config,
    )

    try:
        tgt = PortfolioOptimizationLevel.from_int(int(target_level))
    except ValueError as exc:
        return {"error": str(exc)}

    config = load_portfolio_config(portfolio_name)
    if portfolio_spec:
        # Merge user-supplied spec into the [portfolio] section
        port = config.setdefault("portfolio", {})
        port.update(portfolio_spec)

    current_level_int = int(config.get("optimization", {}).get("level", 0))
    current_level = PortfolioOptimizationLevel.from_int(current_level_int)

    promotion = promote_portfolio(
        current_level=current_level,
        target_level=tgt,
        gate_results=gate_results,
    )

    if promotion.passed:
        config.setdefault("optimization", {})
        config["optimization"]["level"] = promotion.new_level.value
        config["optimization"]["level_name"] = promotion.new_level.name
        config["optimization"]["achieved_at"] = promotion.promoted_at or ""
        config["optimization"]["gate_results"] = gate_results
        # Persist any advisory warnings as a first-class section so
        # operators reading the TOML see regime / concentration notes.
        if promotion.warnings:
            config["optimization"]["warnings"] = list(promotion.warnings)
        elif "warnings" in config.get("optimization", {}):
            # Clear stale warnings when the re-promotion has none.
            del config["optimization"]["warnings"]
        saved_path = save_portfolio_config(portfolio_name, config)
    else:
        saved_path = None

    return {
        "portfolio_name": portfolio_name,
        "passed": promotion.passed,
        "new_level": promotion.new_level.value,
        "new_level_name": promotion.new_level.name,
        "failure_reasons": promotion.failure_reasons,
        "thresholds_checked": promotion.thresholds_checked,
        "advisory_thresholds_checked": promotion.advisory_thresholds_checked,
        "warnings": promotion.warnings,
        "promoted_at": promotion.promoted_at,
        "config_path": str(saved_path) if saved_path else None,
    }
