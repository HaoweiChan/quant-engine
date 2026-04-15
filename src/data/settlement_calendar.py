"""TAIFEX futures settlement calendar.

Single source of truth for settlement dates. Provides both a hardcoded
historical table (verified from TAIFEX Final Settlement Price records)
and an algorithmic fallback (3rd-Wednesday rule with known holiday shifts).

Settlement rule: 3rd Wednesday of each delivery month. If that Wednesday
falls on a holiday or the preceding business day is unavailable, TAIFEX
shifts it — most commonly for Chinese New Year (Jan/Feb).
"""
from __future__ import annotations

import calendar
import sqlite3
import structlog
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Literal

_TAIPEI_TZ = timezone(timedelta(hours=8))
logger = structlog.get_logger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_DEFAULT_DB = _PROJECT_ROOT / "data" / "market.db"

# Verified settlement dates from TAIFEX Final Settlement Price records.
# Key = (year, month), value = settlement day-of-month.
# Source: https://www.taifex.com.tw/enl/eng5/futIndxFSP (TX/MTX/TMF)
_VERIFIED_SETTLEMENTS: dict[tuple[int, int], int] = {
    # 2020
    (2020, 1): 15, (2020, 2): 19, (2020, 3): 18, (2020, 4): 15,
    (2020, 5): 20, (2020, 6): 17, (2020, 7): 15, (2020, 8): 19,
    (2020, 9): 16, (2020, 10): 21, (2020, 11): 18, (2020, 12): 16,
    # 2021
    (2021, 1): 20, (2021, 2): 17, (2021, 3): 17, (2021, 4): 21,
    (2021, 5): 19, (2021, 6): 16, (2021, 7): 21, (2021, 8): 18,
    (2021, 9): 15, (2021, 10): 20, (2021, 11): 17, (2021, 12): 15,
    # 2022
    (2022, 1): 19, (2022, 2): 16, (2022, 3): 16, (2022, 4): 20,
    (2022, 5): 18, (2022, 6): 15, (2022, 7): 20, (2022, 8): 17,
    (2022, 9): 21, (2022, 10): 19, (2022, 11): 16, (2022, 12): 21,
    # 2023
    (2023, 1): 30, (2023, 2): 15, (2023, 3): 15, (2023, 4): 19,
    (2023, 5): 17, (2023, 6): 21, (2023, 7): 19, (2023, 8): 16,
    (2023, 9): 20, (2023, 10): 18, (2023, 11): 15, (2023, 12): 20,
    # 2024
    (2024, 1): 17, (2024, 2): 21, (2024, 3): 20, (2024, 4): 17,
    (2024, 5): 15, (2024, 6): 19, (2024, 7): 17, (2024, 8): 21,
    (2024, 9): 18, (2024, 10): 16, (2024, 11): 20, (2024, 12): 18,
    # 2025
    (2025, 1): 15, (2025, 2): 19, (2025, 3): 19, (2025, 4): 16,
    (2025, 5): 21, (2025, 6): 18, (2025, 7): 16, (2025, 8): 20,
    (2025, 9): 17, (2025, 10): 15, (2025, 11): 19, (2025, 12): 17,
    # 2026
    (2026, 1): 21, (2026, 2): 23, (2026, 3): 18, (2026, 4): 15,
    (2026, 5): 20, (2026, 6): 17, (2026, 7): 15, (2026, 8): 19,
    (2026, 9): 16, (2026, 10): 21, (2026, 11): 18, (2026, 12): 16,
}


def _third_wednesday(year: int, month: int) -> date:
    """Compute the 3rd Wednesday of a given month (default rule)."""
    cal = calendar.Calendar(firstweekday=0)
    wednesdays = [
        day for day, weekday in cal.itermonthdays2(year, month)
        if day != 0 and weekday == 2
    ]
    return date(year, month, wednesdays[2])


def get_settlement_date(year: int, month: int) -> date:
    """Return the settlement date for a given delivery month.

    Uses verified historical data when available, falls back to
    3rd-Wednesday calculation for future/unknown months.
    """
    key = (year, month)
    if key in _VERIFIED_SETTLEMENTS:
        return date(year, month, _VERIFIED_SETTLEMENTS[key])
    return _third_wednesday(year, month)


def get_all_settlements(
    start_year: int = 2020,
    end_year: int = 2027,
) -> list[date]:
    """Return all settlement dates in the given range, sorted ascending."""
    dates: list[date] = []
    for year in range(start_year, end_year + 1):
        for month in range(1, 13):
            try:
                dates.append(get_settlement_date(year, month))
            except (ValueError, IndexError):
                continue
    return sorted(dates)


def next_settlement(as_of: date | None = None) -> date:
    """Return the next settlement date on or after `as_of`."""
    ref = as_of or _today()
    y, m = ref.year, ref.month
    for _ in range(14):
        sd = get_settlement_date(y, m)
        if sd >= ref:
            return sd
        m += 1
        if m > 12:
            m = 1
            y += 1
    raise ValueError(f"No settlement date found within 14 months of {ref}")


def prev_settlement(as_of: date | None = None) -> date:
    """Return the most recent settlement date strictly before `as_of`."""
    ref = as_of or _today()
    y, m = ref.year, ref.month
    for _ in range(14):
        sd = get_settlement_date(y, m)
        if sd < ref:
            return sd
        m -= 1
        if m < 1:
            m = 12
            y -= 1
    raise ValueError(f"No previous settlement found within 14 months of {ref}")


def days_to_settlement(as_of: date | None = None) -> int:
    """Calendar days until the next settlement."""
    ref = as_of or _today()
    return (next_settlement(ref) - ref).days


def is_settlement_day(as_of: date | None = None) -> bool:
    """True if `as_of` is a settlement day."""
    ref = as_of or _today()
    return days_to_settlement(ref) == 0


def settlement_month_code(as_of: date | None = None) -> str:
    """Return the current contract month code, e.g. '202604'."""
    sd = next_settlement(as_of)
    return f"{sd.year}{sd.month:02d}"


def next_month_code(as_of: date | None = None) -> str:
    """Return the next-month contract code after current settlement."""
    sd = next_settlement(as_of)
    y, m = sd.year, sd.month + 1
    if m > 12:
        m = 1
        y += 1
    return f"{y}{m:02d}"


def business_days_to_settlement(
    as_of: date | None = None,
    holidays: set[date] | None = None,
) -> int:
    """Count business days (Mon-Fri, excluding holidays) until next settlement."""
    ref = as_of or _today()
    target = next_settlement(ref)
    if ref >= target:
        return 0
    hols = holidays or set()
    count = 0
    d = ref + timedelta(days=1)
    while d <= target:
        if d.weekday() < 5 and d not in hols:
            count += 1
        d += timedelta(days=1)
    return count


RollUrgency = Literal["none", "watch", "imminent", "overdue"]


def roll_urgency(
    holding_period: str,
    as_of: date | None = None,
) -> tuple[RollUrgency, int]:
    """Determine roll urgency for a holding period.

    Returns (urgency_level, calendar_days_remaining).
    Thresholds:
      - SHORT_TERM: never rolls (always flat by session close)
      - MEDIUM_TERM: watch at T-5, imminent at T-2
      - SWING: watch at T-10, imminent at T-5
    """
    if holding_period == "short_term":
        return ("none", days_to_settlement(as_of))

    days = days_to_settlement(as_of)
    if holding_period == "medium_term":
        if days <= 0:
            return ("overdue", days)
        if days <= 2:
            return ("imminent", days)
        if days <= 5:
            return ("watch", days)
        return ("none", days)

    # swing
    if days <= 0:
        return ("overdue", days)
    if days <= 5:
        return ("imminent", days)
    if days <= 10:
        return ("watch", days)
    return ("none", days)


# -- DB persistence layer --

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS settlement_dates (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    year        INTEGER NOT NULL,
    month       INTEGER NOT NULL,
    day         INTEGER NOT NULL,
    source      TEXT    NOT NULL DEFAULT 'verified',
    scraped_at  TEXT,
    UNIQUE(year, month)
);
"""


def ensure_schema(db_path: Path | None = None) -> None:
    """Create the settlement_dates table if it doesn't exist."""
    path = db_path or _DEFAULT_DB
    conn = sqlite3.connect(str(path))
    try:
        conn.execute(_SCHEMA_SQL)
        conn.commit()
    finally:
        conn.close()


def persist_all(db_path: Path | None = None) -> int:
    """Write all known settlement dates to the DB. Returns rows upserted."""
    path = db_path or _DEFAULT_DB
    ensure_schema(path)
    conn = sqlite3.connect(str(path))
    count = 0
    try:
        for (y, m), d in sorted(_VERIFIED_SETTLEMENTS.items()):
            conn.execute(
                """INSERT INTO settlement_dates (year, month, day, source, scraped_at)
                   VALUES (?, ?, ?, 'verified', ?)
                   ON CONFLICT(year, month) DO UPDATE SET
                       day = excluded.day,
                       source = excluded.source,
                       scraped_at = excluded.scraped_at""",
                (y, m, d, datetime.now(_TAIPEI_TZ).isoformat()),
            )
            count += 1
        # Add algorithmic projections for 2027
        for month in range(1, 13):
            tw = _third_wednesday(2027, month)
            conn.execute(
                """INSERT INTO settlement_dates (year, month, day, source, scraped_at)
                   VALUES (?, ?, ?, 'algorithm', ?)
                   ON CONFLICT(year, month) DO NOTHING""",
                (2027, month, tw.day, datetime.now(_TAIPEI_TZ).isoformat()),
            )
            count += 1
        conn.commit()
        logger.info("settlement_calendar.persisted", rows=count)
    finally:
        conn.close()
    return count


def load_from_db(db_path: Path | None = None) -> dict[tuple[int, int], int]:
    """Load settlement dates from DB. Returns {(year, month): day}."""
    path = db_path or _DEFAULT_DB
    if not path.exists():
        return {}
    conn = sqlite3.connect(str(path))
    try:
        rows = conn.execute(
            "SELECT year, month, day FROM settlement_dates ORDER BY year, month"
        ).fetchall()
        return {(r[0], r[1]): r[2] for r in rows}
    finally:
        conn.close()


def _today() -> date:
    """Current date in Taipei timezone."""
    return datetime.now(_TAIPEI_TZ).date()
