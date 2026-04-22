"""Startup and live gap detection + auto-repair for OHLCV bar data.

Two safeguards:
1. `startup_gap_repair()` - called at app boot, checks last N days for gaps
   and backfills from Shioaji historical API.
2. `check_live_continuity()` - called from LiveMinuteBarStore when a bar
   completes, detects inter-bar gaps and schedules async backfill.
"""
from __future__ import annotations

import sqlite3
import threading
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import structlog

from src.data.contracts import CONTRACTS_BY_SYMBOL
from src.data.db import DEFAULT_DB_PATH

logger = structlog.get_logger(__name__)
TAIPEI_TZ = ZoneInfo("Asia/Taipei")
LOOKBACK_DAYS = 3
SESSION_GAP_MINUTES = 80
_repair_lock = threading.Lock()


def _detect_recent_gaps(
    symbol: str,
    lookback_days: int = LOOKBACK_DAYS,
    db_path: Path = DEFAULT_DB_PATH,
) -> list[tuple[str, str, int]]:
    """Return (gap_start, gap_end, gap_minutes) for missing intraday bars.

    Detects gaps that are within the same trading session (intra-session data
    outages). Skips gaps that span session boundaries (expected inter-session
    gaps where trading is closed).
    """
    from src.data.session_utils import session_id as _session_id

    if not db_path.exists():
        return []
    start = (datetime.now(TAIPEI_TZ) - timedelta(days=lookback_days)).strftime("%Y-%m-%d 00:00:00")
    end = datetime.now(TAIPEI_TZ).strftime("%Y-%m-%d %H:%M:%S")
    conn = sqlite3.connect(str(db_path))
    try:
        rows = conn.execute(
            "SELECT timestamp FROM ohlcv_bars "
            "WHERE symbol = ? AND timestamp >= ? AND timestamp <= ? "
            "ORDER BY timestamp",
            (symbol, start, end),
        ).fetchall()
    finally:
        conn.close()
    if len(rows) < 2:
        return []
    gaps = []
    for i in range(1, len(rows)):
        t1 = datetime.strptime(rows[i - 1][0][:19], "%Y-%m-%d %H:%M:%S")
        t2 = datetime.strptime(rows[i][0][:19], "%Y-%m-%d %H:%M:%S")
        diff_min = int((t2 - t1).total_seconds() / 60)

        # Skip trivially small gaps (< 2 min are fine, likely rounding)
        if diff_min <= 2:
            continue

        # Check if both timestamps are in the same session
        # Add timezone info for session_id function
        t1_tz = t1.replace(tzinfo=TAIPEI_TZ)
        t2_tz = t2.replace(tzinfo=TAIPEI_TZ)
        sid1 = _session_id(t1_tz)
        sid2 = _session_id(t2_tz)

        # If both bars are in the same trading session, it's an intra-session gap
        # that should be repaired (regardless of size)
        if sid1 == sid2 and sid1 != "CLOSED":
            gaps.append((rows[i - 1][0][:19], rows[i][0][:19], diff_min))
    return gaps


def startup_gap_repair(
    symbols: list[str] | None = None,
    lookback_days: int = LOOKBACK_DAYS,
    db_path: Path = DEFAULT_DB_PATH,
) -> dict[str, int]:
    """Check recent bars for gaps and backfill from Shioaji.

    Returns {symbol: bars_recovered}.
    """
    if symbols is None:
        symbols = ["TMF", "TX", "MTX"]
    results: dict[str, int] = {}
    for symbol in symbols:
        contract = CONTRACTS_BY_SYMBOL.get(symbol)
        if not contract:
            continue
        gaps = _detect_recent_gaps(symbol, lookback_days, db_path)
        if not gaps:
            logger.info("startup_gap_check_clean", symbol=symbol, lookback_days=lookback_days)
            continue
        total_missing = sum(g[2] for g in gaps)
        logger.warning(
            "startup_gap_detected",
            symbol=symbol,
            gap_count=len(gaps),
            total_missing_minutes=total_missing,
        )
        try:
            recovered = _backfill_gaps(symbol, contract.shioaji_path, gaps, db_path)
            results[symbol] = recovered
            logger.info("startup_gap_repaired", symbol=symbol, bars_recovered=recovered)
        except Exception:
            logger.exception("startup_gap_repair_failed", symbol=symbol)
    return results


def _backfill_gaps(
    db_symbol: str,
    shioaji_path: str,
    gaps: list[tuple[str, str, int]],
    db_path: Path,
) -> int:
    """Backfill specific gaps from Shioaji historical API."""
    from src.data.crawl import crawl_historical, create_crawl_pipeline
    from src.data.db import Database

    db = Database(f"sqlite:///{db_path}")
    connector, _ = create_crawl_pipeline(db)
    dates_to_fetch: set[date] = set()
    for gap_start, gap_end, _ in gaps:
        d1 = datetime.strptime(gap_start[:10], "%Y-%m-%d").date()
        d2 = datetime.strptime(gap_end[:10], "%Y-%m-%d").date()
        dates_to_fetch.add(d1)
        if d2 != d1:
            dates_to_fetch.add(d2)
    total = 0
    for d in sorted(dates_to_fetch):
        try:
            n = crawl_historical(
                symbol=shioaji_path,
                start=d,
                end=d,
                db=db,
                connector=connector,
                delay=0.5,
                db_symbol=db_symbol,
            )
            total += n
        except Exception:
            logger.exception("gap_backfill_date_failed", symbol=db_symbol, date=str(d))
    return total


def check_live_continuity(
    symbol: str,
    prev_ts: datetime,
    new_ts: datetime,
) -> int | None:
    """Called when a bar completes. Returns gap_minutes if a gap is detected, else None."""
    diff = (new_ts - prev_ts).total_seconds() / 60
    if diff <= 2:
        return None
    if diff >= SESSION_GAP_MINUTES:
        return None
    gap_min = int(diff)
    logger.critical(
        "live_bar_gap_detected",
        symbol=symbol,
        prev=prev_ts.strftime("%Y-%m-%d %H:%M"),
        new=new_ts.strftime("%Y-%m-%d %H:%M"),
        gap_minutes=gap_min,
    )
    return gap_min


def async_repair_gap(symbol: str, gap_start: datetime, gap_end: datetime) -> None:
    """Background thread to repair a detected live gap."""
    if not _repair_lock.acquire(blocking=False):
        logger.warning("gap_repair_skipped_already_running", symbol=symbol)
        return
    try:
        contract = CONTRACTS_BY_SYMBOL.get(symbol)
        if not contract:
            return
        d1 = gap_start.date()
        d2 = gap_end.date()
        dates_to_fetch = {d1}
        if d2 != d1:
            dates_to_fetch.add(d2)
        gaps = [(gap_start.strftime("%Y-%m-%d %H:%M:%S"), gap_end.strftime("%Y-%m-%d %H:%M:%S"), 0)]
        recovered = _backfill_gaps(symbol, contract.shioaji_path, gaps, DEFAULT_DB_PATH)
        logger.info("live_gap_repaired", symbol=symbol, bars_recovered=recovered)
    except Exception:
        logger.exception("live_gap_repair_failed", symbol=symbol)
    finally:
        _repair_lock.release()
