"""Mock War Room seeder.

Runs real backtests (via run_backtest_realdata_for_mcp) against three
known strategies and persists the results into `mock_session_snapshots`,
`mock_fills`, and `mock_positions`. Gated at startup via the
`QUANT_WARROOM_SEED=1` environment variable.

This module is the single source of truth for mock dashboard state.
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

# Strategy slugs seeded into the mock account. Each is (slug, intraday, symbol, equity_share).
# Symbols reflect the mock-dev account's strategies_json config — 2/3 strategies
# trade MTX as the user correctly asserted.
# equity_share represents the fraction of total account equity allocated to each strategy.
_SEED_STRATEGIES: list[tuple[str, bool, str, float]] = [
    ("medium_term/trend_following/donchian_trend_strength", False, "MTX", 0.49),
    ("short_term/trend_following/night_session_long", True, "MTX", 0.10),
    ("swing/trend_following/vol_managed_bnh", False, "MTX", 0.41),
]

_MOCK_ACCOUNT_DEFAULT = "mock-dev"
_INITIAL_EQUITY_TOTAL = 2_000_000.0
_SYMBOL = "TX"  # Default market-data symbol for availability check
_CONTRACT_MULTIPLIERS = {"TX": 200, "MTX": 50, "TMF": 200}


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


def _resolve_params(slug: str) -> dict[str, Any]:
    """Prefer active registry params, fall back to schema defaults."""
    try:
        from src.strategies.registry import get_active_params

        params = get_active_params(slug)
        if params:
            return params
    except Exception:
        logger.debug("warroom.seed.params_fallback slug=%s", slug, exc_info=True)
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


def _persist_backtest_result(
    conn: sqlite3.Connection,
    *,
    account_id: str,
    slug: str,
    session_id: str,
    symbol: str,
    initial_equity: float,
    result: dict[str, Any],
    intraday: bool,
) -> tuple[int, int]:
    """Insert equity snapshots, fills, and open positions. Returns (snapshots, fills)."""
    equity_curve = result.get("equity_curve") or []
    equity_timestamps = result.get("equity_timestamps") or []
    trade_signals = result.get("trade_signals") or []

    # Snapshots: equity_curve is n+1 long, timestamps match after prepend in facade.
    snap_rows: list[tuple[Any, ...]] = []
    peak = initial_equity
    realized = 0.0
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
        eq = float(equity_curve[i])
        ts_epoch = int(equity_timestamps[i])
        while fill_idx < len(fill_ts_epochs) and fill_ts_epochs[fill_idx] <= ts_epoch:
            running_trade_count += 1
            fill_idx += 1
        if eq > peak:
            peak = eq
        dd_pct = 0.0 if peak <= 0 else (peak - eq) / peak * 100.0
        realized = eq - initial_equity
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

    for idx, f in enumerate(prepared):
        is_close = 1 if (
            intraday and bucket_last_index.get(f["bucket"]) == idx
        ) or ("session_close" in f["reason"].lower() or "force_flat" in f["reason"].lower()) else 0
        # Derive a clean signal_reason label from the raw reason string.
        signal_reason = _normalize_signal_reason(f["reason"], is_close)
        # TX full contract fee ~ NT$100/round-trip → per-leg ~50.
        fee = 50.0
        fill_rows.append(
            (
                f["timestamp"],
                account_id,
                session_id,
                slug,
                symbol,
                "buy" if f["side"].lower().startswith("b") else "sell",
                f["price"],
                max(1, f["lots"]),
                fee,
                0.0,  # per-fill realized pnl not broken out here
                is_close,
                signal_reason,
                1,  # triggered=1: all backtest fills are executed
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
    # non-intraday strategies whose fill count is odd (entry without exit).
    if not intraday and len(prepared) >= 1 and len(prepared) % 2 == 1:
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


def _synthesize_open_positions(conn: sqlite3.Connection, account_id: str) -> None:
    """Ensure OPEN POSITIONS table has realistic rows at end-of-seeding.

    Each strategy gets a canonical current position based on its semantics.
    Donchian → MTX mid-swing long. vol_managed_bnh → MTX base lot from lookback
    start. night_session_long → MTX intraday long mid-session (since night
    session opens 15:00 and we render the dashboard anytime).
    """
    conn.execute("DELETE FROM mock_positions WHERE account_id = ?", (account_id,))

    mtx_latest = _latest_price("MTX")
    # Fall back to TX data for MTX if MTX bars are sparse
    if mtx_latest is None:
        mtx_latest = _latest_price("TX")

    if not mtx_latest:
        logger.warning("warroom.seed.synthesize_skipped reason=no_latest_bar")
        return

    # 1) Donchian — MTX mid-swing long entered ~3 days ago
    donchian_slug = "medium_term/trend_following/donchian_trend_strength"
    donchian_session = _strategy_session_id(account_id, donchian_slug)
    donchian_entry = mtx_latest[1] * 0.982
    donchian_qty = 2
    donchian_mult = _CONTRACT_MULTIPLIERS["MTX"]
    donchian_unrealized = (mtx_latest[1] - donchian_entry) * donchian_qty * donchian_mult
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
    night_session = _strategy_session_id(account_id, night_slug)
    night_entry = mtx_latest[1] * 0.995
    night_qty = 4
    mtx_mult = _CONTRACT_MULTIPLIERS["MTX"]
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

    logger.info("warroom.seed.synthesize_done positions=3 account=%s", account_id)


def _lookback_iso(days_back: int) -> str:
    ts = datetime.now(_TAIPEI_TZ) - timedelta(days=days_back)
    return ts.strftime("%Y-%m-%dT%H:%M:%S")


def _lookback_iso_hours(hours_back: int) -> str:
    ts = datetime.now(_TAIPEI_TZ) - timedelta(hours=hours_back)
    return ts.strftime("%Y-%m-%dT%H:%M:%S")


def seed_mock_warroom(
    account_id: str = _MOCK_ACCOUNT_DEFAULT,
    lookback_days: int = 30,
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

    conn = sqlite3.connect(str(mock_warroom_db_path()))
    try:
        ensure_mock_warroom_schema(conn)
        all_cached = True
        for slug, intraday, symbol, equity_share in _SEED_STRATEGIES:
            per_strategy_initial = _INITIAL_EQUITY_TOTAL * equity_share
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
                result = run_backtest_realdata_for_mcp(
                    symbol=symbol,
                    start=start_iso,
                    end=end_iso,
                    strategy=slug,
                    strategy_params=params,
                    initial_equity=per_strategy_initial,
                    intraday=intraday,
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
                initial_equity=per_strategy_initial,
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
        _synthesize_open_positions(conn, account_id)
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
