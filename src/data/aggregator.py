"""Session-aware bar aggregation: 1m → 5m / 1h.

Never aggregates across TAIFEX session boundaries. Uses session_id() as the
grouping key so bars within the 13:45–15:00 and 05:00–08:45 gaps are excluded,
and no bar spans two sessions.

Bars are right-aligned to session-relative boundaries:
- Day session (08:45–13:45): bars labeled 09:45, 10:45, ..., 13:45
- Night session (15:00–05:00+1d): bars labeled 16:00, 17:00, ..., 05:00
"""
from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from src.data.session_utils import session_id, session_open_dt, session_close_dt

if TYPE_CHECKING:
    from src.data.db import Database, OHLCVBar, OHLCVBar1h, OHLCVBar5m

logger = logging.getLogger(__name__)

# Chunk size for batched upserts (avoid holding too many ORM objects in memory)
_BATCH_SIZE = 5000


def _aggregate_1m_to_n(
    bars_1m: list,
    agg_minutes: int,
    symbol: str,
    model_cls: type,
) -> list:
    """Aggregate 1m bars into N-minute bars, respecting session boundaries.

    Bars are grouped by (session_id, time_bucket) so no bar ever crosses
    a session gap. Inter-session bars (session_id == "CLOSED") are dropped.
    """
    # Group by session first
    sessions: dict[str, list] = defaultdict(list)
    for b in bars_1m:
        sid = session_id(b.timestamp)
        if sid == "CLOSED":
            continue
        sessions[sid].append(b)

    bucket_secs = agg_minutes * 60
    result = []

    for sid in sorted(sessions):
        sbars = sessions[sid]
        session_open = session_open_dt(sid)

        # Bucket within the session using session-relative offsets (right-aligned)
        buckets: dict[int, list] = defaultdict(list)
        for b in sbars:
            # Calculate offset from session open
            offset_secs = int((b.timestamp - session_open).total_seconds())
            if offset_secs < 0:
                # Shouldn't happen with correct session_id assignment, but skip if it does
                continue
            bucket_index = offset_secs // bucket_secs
            buckets[bucket_index].append(b)

        session_close = session_close_dt(sid)
        for bucket_index in sorted(buckets):
            group = buckets[bucket_index]
            # Left-aligned: bar timestamp = session_open + bucket_index * bucket_secs (start of period)
            bar_ts = session_open + timedelta(seconds=bucket_index * bucket_secs)
            # Exclude bars that would extend past session close
            # (a left-aligned bar must fully fit within the session)
            bar_end = bar_ts + timedelta(seconds=bucket_secs)
            if bar_end > session_close:
                continue
            result.append(model_cls(
                symbol=symbol,
                timestamp=bar_ts,
                open=group[0].open,
                high=max(b.high for b in group),
                low=min(b.low for b in group),
                close=group[-1].close,
                volume=sum(b.volume for b in group),
            ))

    return result


def build_5m_bars(db: "Database", symbol: str, since: datetime | None = None) -> int:
    """Aggregate 1m → 5m for a symbol. Upsert into ohlcv_5m.

    If `since` is given, only process 1m bars from that timestamp onward
    (incremental update). Returns number of new bars written.
    """
    from src.data.db import OHLCVBar5m
    return _build_bars(db, symbol, 5, OHLCVBar5m, since)


def build_1h_bars(db: "Database", symbol: str, since: datetime | None = None) -> int:
    """Aggregate 1m → 1h for a symbol. Upsert into ohlcv_1h.

    If `since` is given, only process 1m bars from that timestamp onward
    (incremental update). Returns number of new bars written.
    """
    from src.data.db import OHLCVBar1h
    return _build_bars(db, symbol, 60, OHLCVBar1h, since)


def _build_bars(
    db: "Database",
    symbol: str,
    agg_minutes: int,
    model_cls: type,
    since: datetime | None = None,
) -> int:
    """Core aggregation: load 1m bars in chunks, aggregate, upsert."""
    from src.data.db import OHLCVBar

    start = since or datetime(2000, 1, 1)
    end = datetime(2099, 12, 31)

    # Stream 1m bars in date-range chunks to limit memory
    raw = db.get_ohlcv(symbol, start, end)
    logger.info("aggregator: loaded %d 1m bars for %s (since=%s)", len(raw), symbol, since)

    aggregated = _aggregate_1m_to_n(raw, agg_minutes, symbol, model_cls)
    logger.info("aggregator: produced %d %dm bars for %s", len(aggregated), agg_minutes, symbol)

    # Upsert in batches
    total = 0
    for i in range(0, len(aggregated), _BATCH_SIZE):
        batch = aggregated[i : i + _BATCH_SIZE]
        total += db.upsert_aggregated_bars(batch, model_cls)

    logger.info("aggregator: upserted %d new %dm bars for %s", total, agg_minutes, symbol)
    return total


def incremental_update(db: "Database", symbol: str, since: datetime) -> dict[str, int]:
    """Re-aggregate bars added since `since` for both 5m and 1h.

    Called by the crawl pipeline after ingesting new 1m data.
    Returns {"5m": n_new, "1h": n_new}.
    """
    return {
        "5m": build_5m_bars(db, symbol, since=since),
        "1h": build_1h_bars(db, symbol, since=since),
    }
