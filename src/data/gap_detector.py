"""Detect missing 1-minute bars in the OHLCV database for TAIFEX futures.

Compares actual bar timestamps against expected trading minutes derived from
session_utils.py boundaries. Reports gaps with classification (likely holiday
vs data outage).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta

from src.data.db import Database
from src.data.session_utils import generate_trading_minutes


@dataclass
class GapRange:
    start: datetime
    end: datetime
    gap_minutes: int
    likely_holiday: bool


def detect_gaps(
    symbol: str,
    start: date,
    end: date,
    db: Database | None = None,
) -> list[GapRange]:
    """Detect missing 1-minute bars for a symbol in the given date range."""
    if db is None:
        db = Database()

    actual = _load_actual_timestamps(db, symbol, start, end)
    if not actual:
        return []

    missing = _find_missing_minutes(start, end, actual)
    if not missing:
        return []

    return _cluster_gaps(missing)


def gap_summary(gaps: list[GapRange]) -> dict:
    """Summarize gap detection results."""
    data_gaps = [g for g in gaps if not g.likely_holiday]
    holidays = [g for g in gaps if g.likely_holiday]
    return {
        "total_gaps": len(gaps),
        "data_gaps": len(data_gaps),
        "likely_holidays": len(holidays),
        "total_missing_minutes": sum(g.gap_minutes for g in data_gaps),
        "holiday_missing_minutes": sum(g.gap_minutes for g in holidays),
    }


def _load_actual_timestamps(
    db: Database, symbol: str, start: date, end: date,
) -> set[datetime]:
    """Load bar timestamps from DB via the ORM, truncated to minute precision."""
    start_dt = datetime.combine(start, datetime.min.time())
    end_dt = datetime.combine(end, datetime.max.time())
    bars = db.get_ohlcv(symbol, start_dt, end_dt)
    return {b.timestamp.replace(second=0, microsecond=0) for b in bars}


def _find_missing_minutes(
    start: date, end: date, actual: set[datetime],
) -> list[datetime]:
    """Generate expected minutes day-by-day and diff against actual.

    Processes one day at a time to avoid building a massive set in memory.
    """
    missing: list[datetime] = []
    day = start
    while day <= end:
        if day.weekday() < 5:  # Mon-Fri
            for minute in generate_trading_minutes(day):
                if minute not in actual:
                    missing.append(minute)
        day += timedelta(days=1)
    missing.sort()
    return missing


def _cluster_gaps(missing: list[datetime]) -> list[GapRange]:
    """Cluster consecutive missing minutes into GapRange objects.

    A full missing trading day is flagged as likely_holiday.
    """
    if not missing:
        return []

    ranges: list[GapRange] = []
    range_start = missing[0]
    prev = missing[0]

    for ts in missing[1:]:
        # Gap > 4 hours between consecutive missing = new range
        # (inter-session gaps: 13:45→15:00 is 75min, 05:00→08:45 is 225min)
        if (ts - prev) > timedelta(hours=4):
            gap_mins = int((prev - range_start).total_seconds() / 60) + 1
            ranges.append(GapRange(
                start=range_start, end=prev,
                gap_minutes=gap_mins, likely_holiday=False,
            ))
            range_start = ts
        prev = ts

    gap_mins = int((prev - range_start).total_seconds() / 60) + 1
    ranges.append(GapRange(
        start=range_start, end=prev,
        gap_minutes=gap_mins, likely_holiday=False,
    ))

    # Classify: if all trading minutes for a day are missing, likely a holiday
    missing_set = set(missing)
    seen_days: set[date] = set()
    for gap in ranges:
        day = gap.start.date()
        if day in seen_days:
            continue
        seen_days.add(day)
        day_expected = set(generate_trading_minutes(day))
        if day_expected and day_expected.issubset(missing_set):
            gap.likely_holiday = True

    return ranges
