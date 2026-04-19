"""Mock War Room seeder.

Runs real backtests (via run_backtest_realdata_for_mcp) against the
strategies defined by the active portfolio allocation and persists the
results into `mock_session_snapshots`, `mock_fills`, and
`mock_positions`. Gated at startup via `QUANT_WARROOM_SEED=1`.

Strategy list is resolved dynamically from the PortfolioStore (whichever
allocation has ``is_selected=1``). Falls back to a hardcoded default
when no portfolio has been selected.
"""
from __future__ import annotations

import logging
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from src.trading_session.warroom_schema import (
    ensure_mock_warroom_schema,
    mock_warroom_db_path,
)

logger = logging.getLogger(__name__)

_TAIPEI_TZ = timezone(timedelta(hours=8))

# Fallback strategy list when no portfolio is selected in the store.
_DEFAULT_SEED_STRATEGIES: list[tuple[str, bool, str, float]] = [
    ("swing/trend_following/vol_managed_bnh", False, "MTX", 0.05),
    ("medium_term/trend_following/donchian_trend_strength", False, "MTX", 0.05),
    ("short_term/trend_following/night_session_long", True, "MTX", 0.05),
    ("short_term/mean_reversion/spread_reversion", True, "MTX", 0.85),
]


def _resolve_seed_strategies() -> list[tuple[str, bool, str, float]]:
    """Read the active portfolio allocation from the store.

    Returns (slug, intraday, symbol, weight) tuples. Falls back to
    ``_DEFAULT_SEED_STRATEGIES`` when no portfolio has been selected.
    """
    try:
        from src.core.portfolio_store import PortfolioStore
        from src.strategies.registry import is_intraday_strategy

        store = PortfolioStore()
        config = store.get_active_seed_config()
        store.close()
        if config:
            result = []
            for entry in config:
                slug = entry["slug"]
                intraday = is_intraday_strategy(slug)
                result.append((slug, intraday, entry["symbol"], entry["weight"]))
            logger.info(
                "warroom.seed.resolved_from_portfolio n=%d slugs=%s",
                len(result),
                [r[0] for r in result],
            )
            return result
    except Exception:
        logger.warning("warroom.seed.portfolio_resolve_failed", exc_info=True)
    logger.info("warroom.seed.using_defaults n=%d", len(_DEFAULT_SEED_STRATEGIES))
    return list(_DEFAULT_SEED_STRATEGIES)

_MOCK_ACCOUNT_DEFAULT = "mock-dev"
_INITIAL_EQUITY_TOTAL = 2_000_000.0
_SYMBOL = "TX"  # Default market-data symbol for availability check
_CONTRACT_MULTIPLIERS = {"TX": 200, "MTX": 50, "TMF": 200, "TX_R2": 200}


def _market_db_path() -> Path:
    return Path(__file__).resolve().parent.parent.parent / "data" / "market.db"


def _verify_market_data_available(lookback_days: int = 30) -> bool:
    """Return True iff data/market.db exists and has TX bars covering the window."""
    db_path = _market_db_path()
    if not db_path.exists():
        logger.warning(
            "warroom.seed.skipped reason=no_market_data path=%s", str(db_path)
        )
        return False
    try:
        conn = sqlite3.connect(str(db_path))
        try:
            cutoff = (datetime.now(_TAIPEI_TZ) - timedelta(days=lookback_days)).strftime("%Y-%m-%d %H:%M:%S")
            row = conn.execute(
                "SELECT COUNT(1) FROM ohlcv_bars WHERE symbol = ? AND timestamp >= ?",
                (_SYMBOL, cutoff),
            ).fetchone()
            count = int(row[0]) if row else 0
            if count <= 0:
                logger.warning(
                    "warroom.seed.skipped reason=no_market_data symbol=%s count=0",
                    _SYMBOL,
                )
                return False
            return True
        finally:
            conn.close()
    except Exception as exc:
        logger.warning(
            "warroom.seed.skipped reason=no_market_data error=%s", str(exc)
        )
        return False


def _resolve_params(slug: str) -> dict[str, Any] | None:
    """Resolve params for the seeder backtest.

    Returns ``None`` when the strategy has an active candidate in the
    facade's registry (so the facade does its own canonical resolution and
    cache-key construction, matching the MCP tool exactly). Returns the
    registry/schema defaults only when the facade has no active candidate
    — that path keeps the seeder usable on strategies that haven't been
    promoted yet.

    The previous implementation called ``registry.get_active_params``
    directly, which returns the merged PARAM_SCHEMA defaults rather than
    the empty-dict sentinel the facade emits for "use built-in defaults".
    The mismatch produced different cache keys for the seeder vs. the MCP
    tool, so the two paths could deserialise different cached
    backtest results — including ones with different ``initial_equity`` —
    causing playback equity to diverge from MCP by tens of percent.
    """
    try:
        from src.mcp_server.facade import get_active_params_for_mcp

        info = get_active_params_for_mcp(strategy=slug)
        if info.get("source") == "registry":
            # Defer to the facade's resolution so cache keys align with the
            # MCP tool. ``info["params"]`` may be empty here ('use defaults'),
            # but returning None lets the facade short-circuit identically.
            return None
    except Exception:
        logger.debug("warroom.seed.params_facade_failed slug=%s", slug, exc_info=True)
    try:
        from src.strategies.registry import get_defaults

        return get_defaults(slug)
    except Exception:
        logger.warning("warroom.seed.no_params_available slug=%s", slug)
        return {}


def _strategy_session_id(account_id: str, slug: str) -> str:
    return f"mock::{account_id}::{slug.replace('/', '__')}"


def _is_cached(
    conn: sqlite3.Connection,
    session_id: str,
    lookback_days: int,
) -> bool:
    cutoff = (datetime.now(_TAIPEI_TZ) - timedelta(days=lookback_days)).isoformat()
    row = conn.execute(
        """
        SELECT COUNT(1) FROM mock_session_snapshots
        WHERE session_id = ? AND timestamp >= ?
        """,
        (session_id, cutoff),
    ).fetchone()
    return bool(row and int(row[0]) >= 30)


def _clear_strategy(conn: sqlite3.Connection, session_id: str) -> None:
    conn.execute("DELETE FROM mock_session_snapshots WHERE session_id = ?", (session_id,))
    conn.execute("DELETE FROM mock_fills WHERE session_id = ?", (session_id,))
    conn.execute("DELETE FROM mock_positions WHERE session_id = ?", (session_id,))


def _epoch_to_iso(epoch: float | int) -> str:
    try:
        return (
            datetime.fromtimestamp(int(epoch), tz=timezone(timedelta(0)))
            .astimezone(_TAIPEI_TZ)
            .isoformat()
        )
    except Exception:
        return datetime.now(_TAIPEI_TZ).isoformat()


def _session_key_from_iso(iso_ts: str) -> str:
    """Bucket fills into TAIFEX sessions by calendar day + half (night vs day)."""
    try:
        dt = datetime.fromisoformat(iso_ts)
    except ValueError:
        return iso_ts[:10]
    hour = dt.hour
    # Day session 08:45-13:45, night 15:00-05:00+1d
    if 6 <= hour < 15:
        return f"day::{dt.date().isoformat()}"
    if hour >= 15:
        return f"night::{dt.date().isoformat()}"
    # 00:00-05:00 belongs to the previous calendar day's night session
    prev = (dt - timedelta(days=1)).date().isoformat()
    return f"night::{prev}"


_REASON_MAP: list[tuple[str, str]] = [
    ("session_close", "SESSION_CLOSE"),
    ("force_flat", "SESSION_CLOSE"),
    ("stop_loss", "STOP_LOSS"),
    ("stop", "STOP_LOSS"),
    ("take_profit", "TAKE_PROFIT"),
    ("profit", "TAKE_PROFIT"),
    ("breakout", "BREAKOUT"),
    ("trend_reversal", "TREND_REVERSAL"),
    ("reversal", "TREND_REVERSAL"),
    ("pyramid", "PYRAMID"),
    ("add", "PYRAMID"),
    ("entry", "ENTRY"),
    ("exit", "EXIT"),
]


def _normalize_signal_reason(raw: str, is_close: int) -> str:
    """Map a raw strategy reason string to a short display label."""
    if is_close:
        return "SESSION_CLOSE"
    if not raw:
        return "ENTRY"
    lower = raw.lower()
    for key, label in _REASON_MAP:
        if key in lower:
            return label
    return raw.upper()[:20]


def _insert_mock_pending_signals(
    conn: sqlite3.Connection,
    *,
    account_id: str,
    session_id: str,
    slug: str,
    symbol: str,
) -> None:
    """Add a couple of unfilled (triggered=0) signals to the blotter for demo purposes.

    These represent signals that were generated but not yet executed (e.g. limit
    orders waiting for price, or signals filtered by risk checks).
    """
    now = datetime.now(_TAIPEI_TZ)
    pending_rows: list[tuple] = [
        (
            (now - timedelta(minutes=12)).isoformat(),
            account_id,
            session_id,
            slug,
            symbol,
            "buy",
            0.0,   # price unknown — pending
            1,
            0.0,   # no fee yet
            0.0,
            0,
            "BREAKOUT",
            0,     # triggered=0
        ),
        (
            (now - timedelta(minutes=5)).isoformat(),
            account_id,
            session_id,
            slug,
            symbol,
            "sell",
            0.0,
            1,
            0.0,
            0.0,
            0,
            "STOP_LOSS",
            0,     # triggered=0
        ),
    ]
    conn.executemany(
        """
        INSERT INTO mock_fills
            (timestamp, account_id, session_id, strategy_slug, symbol, side,
             price, quantity, fee, pnl_realized, is_session_close,
             signal_reason, triggered)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        pending_rows,
    )


def _spread_meta_for_slug(slug: str) -> dict | None:
    """Return STRATEGY_META dict iff the slug is a 2-leg spread strategy."""
    try:
        from src.strategies.registry import get_info
        info = get_info(slug)
        legs = info.meta.get("spread_legs") if info and info.meta else None
        if legs and len(legs) == 2:
            return info.meta
    except Exception:
        logger.debug("warroom.seed.spread_meta_lookup_failed slug=%s", slug, exc_info=True)
        return None
    return None




def _canon_ts_epoch(ts: Any) -> int | None:
    """Canonicalize bar / signal timestamps to integer epoch seconds.

    Both OHLCVBar timestamps ('2026-04-11 00:00:00') and trade-signal
    timestamps ('2026-04-11T00:00:00+08:00' or naive ISO) collapse to the
    same minute-aligned epoch second. Naive timestamps are interpreted as
    Taipei local time. Returns None on parse failure so callers can fail
    fast rather than silently dropping data.
    """
    if ts is None:
        return None
    if isinstance(ts, (int, float)):
        return int(ts)
    s = str(ts).strip()
    # Normalize bar's space separator to ISO 'T' for fromisoformat.
    if " " in s and "T" not in s:
        s = s.replace(" ", "T", 1)
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_TAIPEI_TZ)
    return int(dt.timestamp())


def _build_leg_price_index(leg_bars: list[dict[str, Any]]) -> dict[int, float]:
    """Map epoch-second timestamp → close price for a list of aligned leg bars.

    Used when expanding synthetic spread trade_signals into real per-leg fills
    so each leg's fill price matches the R1/R2 bar at the same timestamp. The
    keyspace is integer epoch seconds so 'T' vs ' ' separator drift and
    timezone-suffix variation between OHLCVBar.timestamp and Fill.timestamp
    can never cause silent misses.
    """
    index: dict[int, float] = {}
    for b in leg_bars or []:
        epoch = _canon_ts_epoch(b.get("timestamp"))
        close = b.get("close")
        if epoch is None or close is None:
            continue
        index[epoch] = float(close)
    return index


def _persist_backtest_result(
    conn: sqlite3.Connection,
    *,
    account_id: str,
    slug: str,
    session_id: str,
    symbol: str,
    total_equity: float,
    weight: float,
    result: dict[str, Any],
    intraday: bool,
) -> tuple[int, int]:
    """Insert weighted equity snapshots, fills, and open positions.

    The backtest in ``result`` was run at the full pool ``total_equity``
    (typically 2_000_000). Per-strategy snapshots are persisted scaled by
    ``weight``: ``persisted_equity[i] = weight × backtest_equity[i]``. Summing
    across strategies at any timestamp yields the MCP-style portfolio
    aggregate ``Σ weight_i × strategy_equity_at_pool_i(t)`` (see war_room.py
    `_load_mock_as_of` aggregator).

    Fills are persisted as the strategy's natural execution units (lot count,
    price) so the blotter remains attributable. The per-fill ``pnl_realized``
    column reports the strategy's contribution to portfolio PnL — i.e. scaled
    by ``weight`` — so summing fills reconstructs the snapshot's realized PnL
    delta.

    Spread strategies: each synthetic trade_signal expands into TWO fill rows
    (one per leg). Leg prices are looked up by epoch-second canonical
    timestamp; a missing leg price raises rather than silently writing 0.0,
    because that case has historically masked alignment bugs in the bar
    builder.

    Returns (snapshots, fills).
    """
    equity_curve = result.get("equity_curve") or []
    equity_timestamps = result.get("equity_timestamps") or []
    trade_signals = result.get("trade_signals") or []

    spread_legs = result.get("spread_legs") or []
    is_spread = len(spread_legs) == 2
    r1_price_by_ts: dict[int, float] = {}
    r2_price_by_ts: dict[int, float] = {}
    if is_spread:
        r1_price_by_ts = _build_leg_price_index(result.get("spread_r1_bars") or [])
        r2_price_by_ts = _build_leg_price_index(result.get("spread_r2_bars") or [])

    initial_slot_equity = total_equity * weight
    # Snapshots: equity_curve is n+1 long, timestamps match after prepend in facade.
    snap_rows: list[tuple[Any, ...]] = []
    peak = initial_slot_equity
    n = min(len(equity_curve), len(equity_timestamps))
    running_trade_count = 0
    # Build an index of how many fills have occurred by each bar timestamp
    fill_ts_epochs: list[int] = []
    for f in trade_signals:
        try:
            dt = datetime.fromisoformat(f["timestamp"])
            fill_ts_epochs.append(int(dt.timestamp()))
        except Exception:
            continue
    fill_ts_epochs.sort()
    fill_idx = 0
    for i in range(n):
        eq_full = float(equity_curve[i])  # equity assuming strategy ran on full pool
        eq = weight * eq_full              # this strategy's contribution to portfolio
        ts_epoch = int(equity_timestamps[i])
        while fill_idx < len(fill_ts_epochs) and fill_ts_epochs[fill_idx] <= ts_epoch:
            running_trade_count += 1
            fill_idx += 1
        if eq > peak:
            peak = eq
        dd_pct = 0.0 if peak <= 0 else (peak - eq) / peak * 100.0
        realized = eq - initial_slot_equity
        snap_rows.append(
            (
                session_id,
                slug,
                _epoch_to_iso(ts_epoch),
                eq,
                0.0,  # unrealized — absorbed into realized here for simplicity
                realized,
                dd_pct,
                peak,
                running_trade_count,
            )
        )

    if snap_rows:
        conn.executemany(
            """
            INSERT INTO mock_session_snapshots
                (session_id, strategy_slug, timestamp, equity, unrealized_pnl,
                 realized_pnl, drawdown_pct, peak_equity, trade_count)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            snap_rows,
        )

    # Fills: mark the last fill in each session bucket as is_session_close.
    fill_rows: list[tuple[Any, ...]] = []
    bucket_last_index: dict[str, int] = {}
    prepared: list[dict[str, Any]] = []
    for f in trade_signals:
        try:
            ts_iso = f["timestamp"]
        except Exception:
            continue
        price = float(f.get("price", 0.0))
        lots = f.get("lots", 1)
        try:
            lots_int = int(round(float(lots)))
        except Exception:
            lots_int = 1
        side = str(f.get("side", "buy"))
        reason = str(f.get("reason", "") or "")
        prepared.append(
            {
                "timestamp": ts_iso,
                "side": side,
                "price": price,
                "lots": lots_int,
                "reason": reason,
                "bucket": _session_key_from_iso(ts_iso),
            }
        )
    for idx, f in enumerate(prepared):
        bucket_last_index[f["bucket"]] = idx

    # Default per-fill fee for single-contract strategies (TX round-trip ~100 → 50/leg).
    # For spread strategies the cost is split across the two synthetic legs so the
    # total per trade_signal equals the spread_cost_per_fill declared in META.
    spread_meta = _spread_meta_for_slug(slug)
    spread_cost_per_fill = float((spread_meta or {}).get("spread_cost_per_fill", 700.0))
    spread_leg_fee = round(spread_cost_per_fill / 2.0, 4)

    for idx, f in enumerate(prepared):
        is_close = 1 if (
            intraday and bucket_last_index.get(f["bucket"]) == idx
        ) or ("session_close" in f["reason"].lower() or "force_flat" in f["reason"].lower()) else 0
        signal_reason = _normalize_signal_reason(f["reason"], is_close)
        side_norm = "buy" if f["side"].lower().startswith("b") else "sell"
        lots = max(1, f["lots"])

        if is_spread:
            ts_key = f["timestamp"]
            epoch = _canon_ts_epoch(ts_key)
            if epoch is None:
                raise RuntimeError(
                    f"warroom_seeder: cannot parse spread fill timestamp {ts_key!r} for slug={slug}",
                )
            # Fail fast on missing leg price. Silent fallback (0.0 or synthetic
            # spread price) historically masked alignment bugs in the bar
            # builder and produced nonsense PnL — see plan A2.
            if epoch not in r1_price_by_ts or epoch not in r2_price_by_ts:
                raise RuntimeError(
                    f"warroom_seeder: missing leg price for slug={slug} epoch={epoch} ts={ts_key!r} "
                    f"(have_r1={epoch in r1_price_by_ts} have_r2={epoch in r2_price_by_ts}). "
                    f"Spread bar alignment is broken; check facade._build_spread_bars output.",
                )
            r1_px = r1_price_by_ts[epoch]
            r2_px = r2_price_by_ts[epoch]
            opposite_side = "sell" if side_norm == "buy" else "buy"
            # Leg 1 (e.g. TX) executes in the trade direction; leg 2 (e.g. TX_R2)
            # executes the opposite side so a "long spread" = long R1 + short R2.
            for leg_symbol, leg_side, leg_price in (
                (spread_legs[0], side_norm, r1_px),
                (spread_legs[1], opposite_side, r2_px),
            ):
                fill_rows.append(
                    (
                        ts_key,
                        account_id,
                        session_id,
                        slug,
                        leg_symbol,
                        leg_side,
                        float(leg_price),
                        lots,
                        spread_leg_fee,
                        0.0,
                        is_close,
                        signal_reason,
                        1,
                    )
                )
            continue

        fill_rows.append(
            (
                f["timestamp"],
                account_id,
                session_id,
                slug,
                symbol,
                side_norm,
                f["price"],
                lots,
                50.0,
                0.0,
                is_close,
                signal_reason,
                1,
            )
        )

    if fill_rows:
        conn.executemany(
            """
            INSERT INTO mock_fills
                (timestamp, account_id, session_id, strategy_slug, symbol, side,
                 price, quantity, fee, pnl_realized, is_session_close,
                 signal_reason, triggered)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            fill_rows,
        )

    # Insert a small set of mock "pending" (unfilled) signals so the blotter
    # shows both FILLED and PENDING rows for demo purposes.
    _insert_mock_pending_signals(conn, account_id=account_id, session_id=session_id, slug=slug, symbol=symbol)

    # Open positions at end of backtest: only if final fill is an entry and
    # there's no matching exit. For simplicity, we emit an open position for
    # non-intraday, non-spread strategies whose fill count is odd. Spread
    # strategies have their open positions synthesized separately via
    # _synthesize_open_positions using both legs of the spread.
    if not is_spread and not intraday and len(prepared) >= 1 and len(prepared) % 2 == 1:
        last = prepared[-1]
        last_price = float(result.get("equity_curve", [0])[-1]) and last["price"]
        conn.execute(
            """
            INSERT INTO mock_positions
                (account_id, session_id, strategy_slug, symbol, side, quantity,
                 avg_entry_price, current_price, unrealized_pnl, opened_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                account_id,
                session_id,
                slug,
                symbol,
                "long" if last["side"].lower().startswith("b") else "short",
                max(1, last["lots"]),
                last["price"],
                last_price,
                0.0,
                last["timestamp"],
            ),
        )

    return len(snap_rows), len(fill_rows)


def _latest_price(symbol: str) -> tuple[str, float] | None:
    try:
        mkt = sqlite3.connect(str(_market_db_path()))
        try:
            row = mkt.execute(
                "SELECT timestamp, close FROM ohlcv_bars WHERE symbol=? ORDER BY timestamp DESC LIMIT 1",
                (symbol,),
            ).fetchone()
        finally:
            mkt.close()
        if not row:
            return None
        return row[0], float(row[1])
    except Exception:
        return None


def _bar_at_lookback(symbol: str, days_back: int) -> tuple[str, float] | None:
    try:
        mkt = sqlite3.connect(str(_market_db_path()))
        try:
            start_ts = (datetime.now(_TAIPEI_TZ) - timedelta(days=days_back)).strftime("%Y-%m-%d %H:%M:%S")
            row = mkt.execute(
                "SELECT timestamp, close FROM ohlcv_bars WHERE symbol=? AND timestamp >= ? ORDER BY timestamp ASC LIMIT 1",
                (symbol, start_ts),
            ).fetchone()
        finally:
            mkt.close()
        if not row:
            return None
        return row[0], float(row[1])
    except Exception:
        return None


def _synthesize_open_positions(
    conn: sqlite3.Connection,
    account_id: str,
    seed_strategies: list[tuple[str, bool, str, float]] | None = None,
) -> None:
    """Ensure OPEN POSITIONS table has realistic rows at end-of-seeding.

    Each strategy gets a canonical current position based on its semantics.
    Only synthesizes positions for strategies present in *seed_strategies*.
    """
    seeded_slugs = {s[0] for s in (seed_strategies or _DEFAULT_SEED_STRATEGIES)}
    conn.execute("DELETE FROM mock_positions WHERE account_id = ?", (account_id,))

    mtx_latest = _latest_price("MTX")
    # Fall back to TX data for MTX if MTX bars are sparse
    if mtx_latest is None:
        mtx_latest = _latest_price("TX")

    if not mtx_latest:
        logger.warning("warroom.seed.synthesize_skipped reason=no_latest_bar")
        return

    mtx_mult = _CONTRACT_MULTIPLIERS["MTX"]
    seed_list = seed_strategies or _DEFAULT_SEED_STRATEGIES
    seeded_symbol_map = {slug: sym for slug, _intra, sym, _w in seed_list}

    # 1) Donchian — MTX mid-swing long entered ~3 days ago
    donchian_slug = "medium_term/trend_following/donchian_trend_strength"
    if donchian_slug in seeded_slugs:
        donchian_session = _strategy_session_id(account_id, donchian_slug)
        donchian_entry = mtx_latest[1] * 0.982
        donchian_qty = 2
        donchian_unrealized = (mtx_latest[1] - donchian_entry) * donchian_qty * mtx_mult
        conn.execute(
            """
            INSERT INTO mock_positions
                (account_id, session_id, strategy_slug, symbol, side, quantity,
                 avg_entry_price, current_price, unrealized_pnl, opened_at)
            VALUES (?, ?, ?, 'MTX', 'long', ?, ?, ?, ?, ?)
            """,
            (
                account_id,
                donchian_session,
                donchian_slug,
                donchian_qty,
                round(donchian_entry, 2),
                round(mtx_latest[1], 2),
                round(donchian_unrealized, 2),
                _lookback_iso(3),
            ),
        )

    # 2) night_session_long — MTX intraday long from a few hours ago
    night_slug = "short_term/trend_following/night_session_long"
    if night_slug in seeded_slugs:
        night_session = _strategy_session_id(account_id, night_slug)
        night_entry = mtx_latest[1] * 0.995
        night_qty = 4
        night_unrealized = (mtx_latest[1] - night_entry) * night_qty * mtx_mult
        conn.execute(
            """
            INSERT INTO mock_positions
                (account_id, session_id, strategy_slug, symbol, side, quantity,
                 avg_entry_price, current_price, unrealized_pnl, opened_at)
            VALUES (?, ?, ?, 'MTX', 'long', ?, ?, ?, ?, ?)
            """,
            (
                account_id,
                night_session,
                night_slug,
                night_qty,
                round(night_entry, 2),
                round(mtx_latest[1], 2),
                round(night_unrealized, 2),
                _lookback_iso_hours(6),
            ),
        )

    # 3) vol_managed_bnh — MTX base lot held since lookback start
    bnh_slug = "swing/trend_following/vol_managed_bnh"
    if bnh_slug in seeded_slugs:
        bnh_session = _strategy_session_id(account_id, bnh_slug)
        entry_bar = _bar_at_lookback("MTX", 30) or _bar_at_lookback("TX", 30)
        if entry_bar:
            bnh_entry = entry_bar[1]
            bnh_opened = entry_bar[0]
        else:
            bnh_entry = mtx_latest[1] * 0.95
            bnh_opened = _lookback_iso(30)
        bnh_qty = 3
        bnh_unrealized = (mtx_latest[1] - bnh_entry) * bnh_qty * mtx_mult
        conn.execute(
            """
            INSERT INTO mock_positions
                (account_id, session_id, strategy_slug, symbol, side, quantity,
                 avg_entry_price, current_price, unrealized_pnl, opened_at)
            VALUES (?, ?, ?, 'MTX', 'long', ?, ?, ?, ?, ?)
            """,
            (
                account_id,
                bnh_session,
                bnh_slug,
                bnh_qty,
                round(bnh_entry, 2),
                round(mtx_latest[1], 2),
                round(bnh_unrealized, 2),
                bnh_opened,
            ),
        )

    # 4) spread_reversion — synthesize both legs (leg1 long + leg2 short).
    spread_slug = "short_term/mean_reversion/spread_reversion"
    if spread_slug in seeded_slugs:
        spread_meta = _spread_meta_for_slug(spread_slug)
        seeded_symbol = seeded_symbol_map.get(spread_slug)
        if spread_meta:
            if seeded_symbol:
                leg1, leg2 = seeded_symbol, f"{seeded_symbol}_R2"
            else:
                leg1, leg2 = spread_meta["spread_legs"]
            leg1_latest = _latest_price(leg1)
            leg2_latest = _latest_price(leg2)
            if leg1_latest and leg2_latest:
                spread_session = _strategy_session_id(account_id, spread_slug)
                leg1_mult = _CONTRACT_MULTIPLIERS.get(leg1, 200)
                leg2_mult = _CONTRACT_MULTIPLIERS.get(leg2, 200)
                leg1_entry = leg1_latest[1] * 0.998
                leg2_entry = leg2_latest[1] * 1.002
                leg_qty = 1
                leg1_unrealized = (leg1_latest[1] - leg1_entry) * leg_qty * leg1_mult
                leg2_unrealized = (leg2_entry - leg2_latest[1]) * leg_qty * leg2_mult
                conn.execute(
                    """
                    INSERT INTO mock_positions
                        (account_id, session_id, strategy_slug, symbol, side, quantity,
                         avg_entry_price, current_price, unrealized_pnl, opened_at)
                    VALUES (?, ?, ?, ?, 'long', ?, ?, ?, ?, ?)
                    """,
                    (
                        account_id,
                        spread_session,
                        spread_slug,
                        leg1,
                        leg_qty,
                        round(leg1_entry, 2),
                        round(leg1_latest[1], 2),
                        round(leg1_unrealized, 2),
                        _lookback_iso_hours(3),
                    ),
                )
                conn.execute(
                    """
                    INSERT INTO mock_positions
                        (account_id, session_id, strategy_slug, symbol, side, quantity,
                         avg_entry_price, current_price, unrealized_pnl, opened_at)
                    VALUES (?, ?, ?, ?, 'short', ?, ?, ?, ?, ?)
                    """,
                    (
                        account_id,
                        spread_session,
                        spread_slug,
                        leg2,
                        leg_qty,
                        round(leg2_entry, 2),
                        round(leg2_latest[1], 2),
                        round(leg2_unrealized, 2),
                        _lookback_iso_hours(3),
                    ),
                )
                logger.info(
                    "warroom.seed.synthesize_spread_done account=%s legs=%s",
                    account_id,
                    spread_meta["spread_legs"],
                )
            else:
                logger.warning(
                    "warroom.seed.synthesize_spread_skipped reason=no_leg_prices legs=%s",
                    spread_meta["spread_legs"],
                )

    synth_count = conn.execute(
        "SELECT COUNT(1) FROM mock_positions WHERE account_id = ?", (account_id,),
    ).fetchone()[0]
    logger.info(
        "warroom.seed.synthesize_done positions=%d account=%s", synth_count, account_id,
    )


def _lookback_iso(days_back: int) -> str:
    ts = datetime.now(_TAIPEI_TZ) - timedelta(days=days_back)
    return ts.strftime("%Y-%m-%dT%H:%M:%S")


def _lookback_iso_hours(hours_back: int) -> str:
    ts = datetime.now(_TAIPEI_TZ) - timedelta(hours=hours_back)
    return ts.strftime("%Y-%m-%dT%H:%M:%S")


def seed_mock_warroom(
    account_id: str = _MOCK_ACCOUNT_DEFAULT,
    lookback_days: int = 365,
    force: bool = False,
) -> dict[str, Any]:
    """Populate the mock_* tables from real backtests.

    Idempotent: returns early if each strategy already has ≥ 30 snapshots
    within the lookback window and `force=False`.
    """
    t_start = time.perf_counter()
    report: dict[str, Any] = {
        "cached": False,
        "skipped": False,
        "total_duration_ms": 0,
        "strategies": {},
    }

    if not _verify_market_data_available(lookback_days=lookback_days):
        report["skipped"] = True
        return report

    # Lazy import facade so startup stays fast if QUANT_WARROOM_SEED is off.
    try:
        from src.mcp_server.facade import run_backtest_realdata_for_mcp
    except Exception as exc:
        logger.warning("warroom.seed.facade_import_failed error=%s", str(exc))
        report["skipped"] = True
        return report

    now = datetime.now(_TAIPEI_TZ)
    end_iso = now.strftime("%Y-%m-%d")
    start_iso = (now - timedelta(days=lookback_days)).strftime("%Y-%m-%d")

    seed_strategies = _resolve_seed_strategies()
    conn = sqlite3.connect(str(mock_warroom_db_path()))
    try:
        ensure_mock_warroom_schema(conn)

        if force:
            seeded_ids = {
                _strategy_session_id(account_id, s[0]) for s in seed_strategies
            }
            existing = {
                r[0] for r in conn.execute(
                    "SELECT DISTINCT session_id FROM mock_session_snapshots "
                    "WHERE session_id LIKE ?",
                    (f"mock::{account_id}::%",),
                ).fetchall()
            }
            stale = existing - seeded_ids
            for sid in stale:
                logger.info("warroom.seed.purge_stale session_id=%s", sid)
                _clear_strategy(conn, sid)
            if stale:
                conn.commit()

        all_cached = True
        for slug, intraday, symbol, weight in seed_strategies:
            session_id = _strategy_session_id(account_id, slug)
            per_start = time.perf_counter()
            if not force and _is_cached(conn, session_id, lookback_days):
                logger.info("warroom.seed.skipped reason=cached slug=%s", slug)
                report["strategies"][slug] = {
                    "cached": True,
                    "fills": 0,
                    "snapshots": 0,
                    "duration_ms": 0,
                }
                continue
            all_cached = False
            params = _resolve_params(slug)
            try:
                # Spread strategies: override META.spread_legs so the seeded
                # bars/fills/positions use the account's actual underlying
                # (e.g. MTX/MTX_R2) instead of the strategy's declared default
                # (TX/TX_R2). Derive legs as (symbol, f"{symbol}_R2") when the
                # strategy is a spread; otherwise leave the facade to use META.
                legs_override: list[str] | None = None
                if _spread_meta_for_slug(slug):
                    legs_override = [symbol, f"{symbol}_R2"]

                # Always backtest at the FULL pool equity so per-strategy
                # results match the MCP reference exactly. Portfolio weighting
                # is applied post-hoc when persisting snapshots, mirroring
                # `run_portfolio_risk_report_for_mcp` semantics: each strategy
                # is sized as if it owned the full account, and aggregation
                # combines weighted returns rather than weighted capital.
                #
                # Pinned execution is intentionally LEFT ENABLED so the seeder
                # uses the same strategy code the MCP run_backtest_realdata
                # tool uses (registry-active candidate). The previous
                # `force_current_file=True` produced playback equity curves
                # that diverged from MCP by tens of percent because the
                # strategy source file had drifted from the pinned candidate.
                # If the pinned code can no longer be loaded (e.g.
                # parameter-signature drift causing TypeError), retry with
                # current source as a fallback so the seeder is still
                # idempotent across refactors.
                try:
                    result = run_backtest_realdata_for_mcp(
                        symbol=symbol,
                        start=start_iso,
                        end=end_iso,
                        strategy=slug,
                        strategy_params=params,
                        initial_equity=_INITIAL_EQUITY_TOTAL,
                        intraday=intraday,
                        spread_legs_override=legs_override,
                    )
                except TypeError as exc:
                    logger.warning(
                        "warroom.seed.pinned_signature_drift slug=%s error=%s; "
                        "falling back to current source file",
                        slug,
                        exc,
                    )
                    result = run_backtest_realdata_for_mcp(
                        symbol=symbol,
                        start=start_iso,
                        end=end_iso,
                        strategy=slug,
                        strategy_params=params,
                        initial_equity=_INITIAL_EQUITY_TOTAL,
                        intraday=intraday,
                        force_current_file=True,
                        spread_legs_override=legs_override,
                    )
            except Exception as exc:
                logger.exception("warroom.seed.backtest_error slug=%s error=%s", slug, exc)
                report["strategies"][slug] = {
                    "error": str(exc),
                    "fills": 0,
                    "snapshots": 0,
                    "duration_ms": int((time.perf_counter() - per_start) * 1000),
                }
                continue
            if not isinstance(result, dict) or result.get("error"):
                logger.warning(
                    "warroom.seed.backtest_empty slug=%s result=%s",
                    slug,
                    (result or {}).get("error") if isinstance(result, dict) else "non-dict",
                )
                report["strategies"][slug] = {
                    "fills": 0,
                    "snapshots": 0,
                    "duration_ms": int((time.perf_counter() - per_start) * 1000),
                    "error": "empty",
                }
                continue

            _clear_strategy(conn, session_id)
            snapshots, fills = _persist_backtest_result(
                conn,
                account_id=account_id,
                slug=slug,
                session_id=session_id,
                symbol=symbol,
                total_equity=_INITIAL_EQUITY_TOTAL,
                weight=weight,
                result=result,
                intraday=intraday,
            )
            conn.commit()
            report["strategies"][slug] = {
                "fills": fills,
                "snapshots": snapshots,
                "duration_ms": int((time.perf_counter() - per_start) * 1000),
                "cached": False,
            }
            logger.info(
                "warroom.seed.strategy_done slug=%s snapshots=%d fills=%d",
                slug,
                snapshots,
                fills,
            )
        report["cached"] = all_cached

        # Synthesize realistic "current" open positions so the dashboard
        # OPEN POSITIONS table is not empty. The user needs to see which
        # strategy owns each position.
        _synthesize_open_positions(conn, account_id, seed_strategies)
        conn.commit()
    finally:
        conn.close()

    report["total_duration_ms"] = int((time.perf_counter() - t_start) * 1000)
    logger.info(
        "warroom.seed.complete account=%s cached=%s duration_ms=%d",
        account_id,
        report["cached"],
        report["total_duration_ms"],
    )
    return report
