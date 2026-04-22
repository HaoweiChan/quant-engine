"""TAIFEX session topology — the single source of truth for session boundaries.

All session logic in the codebase should import from this module.
No other file should hardcode session times.

Day session:   08:45 - 13:45  (Taiwan local time)
Night session: 15:00 - 05:00+1d (spans midnight)
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta

# ── Session boundary constants ────────────────────────────────────────────────
NIGHT_OPEN = time(15, 0)   # 15:00 Taiwan time
NIGHT_CLOSE = time(5, 0)   # 05:00 Taiwan time (next calendar day)
DAY_OPEN = time(8, 45)
DAY_CLOSE = time(13, 45)


def session_id(ts: datetime) -> str:
    """Return the canonical session identifier for a bar timestamp.

    Night session is keyed to the calendar date it OPENED, not the bar's date.

    Examples:
        2024-01-15 16:00 -> "N20240115"
        2024-01-16 04:55 -> "N20240115"  (same session, crosses midnight)
        2024-01-16 09:30 -> "D20240116"
        2024-01-16 14:00 -> "CLOSED"     (inter-session gap)
    """
    t = ts.time()
    if t >= NIGHT_OPEN:
        return f"N{ts.strftime('%Y%m%d')}"
    elif t < NIGHT_CLOSE:
        prev = (ts - timedelta(days=1)).strftime("%Y%m%d")
        return f"N{prev}"
    elif DAY_OPEN <= t < DAY_CLOSE:
        return f"D{ts.strftime('%Y%m%d')}"
    return "CLOSED"


def is_new_session(prev_ts: datetime, curr_ts: datetime) -> bool:
    """Return True when *curr_ts* belongs to a different session than *prev_ts*."""
    return session_id(prev_ts) != session_id(curr_ts)


def is_trading(ts: datetime) -> bool:
    """Return True if *ts* falls within a trading session."""
    return session_id(ts) != "CLOSED"


def generate_trading_minutes(day: date) -> list[datetime]:
    """Generate all expected 1-minute bar timestamps for a calendar day.

    Covers the after-midnight portion of the previous night session (00:00-04:59),
    the day session (08:45-13:44), and the pre-midnight portion of the night
    session opening on this day (15:00-23:59).
    """
    minutes: list[datetime] = []
    # Night session after-midnight: 00:00 → last minute before NIGHT_CLOSE
    last_night_min = (datetime.combine(day, NIGHT_CLOSE) - timedelta(minutes=1)).time()
    t = datetime.combine(day, time(0, 0))
    end = datetime.combine(day, last_night_min)
    while t <= end:
        minutes.append(t)
        t += timedelta(minutes=1)
    # Day session: DAY_OPEN → last minute before DAY_CLOSE
    last_day_min = (datetime.combine(day, DAY_CLOSE) - timedelta(minutes=1)).time()
    t = datetime.combine(day, DAY_OPEN)
    end = datetime.combine(day, last_day_min)
    while t <= end:
        minutes.append(t)
        t += timedelta(minutes=1)
    # Night session pre-midnight: NIGHT_OPEN → 23:59
    t = datetime.combine(day, NIGHT_OPEN)
    end = datetime.combine(day, time(23, 59))
    while t <= end:
        minutes.append(t)
        t += timedelta(minutes=1)
    return minutes


def trading_day(ts: datetime) -> date:
    """Map a TAIFEX timestamp to its trading day.

    TAIFEX trading day definition:
      - Night session (15:00 -> 05:00+1d) belongs to the NEXT calendar day's
        trading day.  Mon 16:00 -> Tuesday.  Fri 16:00 -> Monday (weekend skip
        is handled by the calendar, not here -- the raw +1 day gives Saturday,
        which the exchange treats as Monday's trading day since no trading
        happens on weekends).
      - Day session (08:45 -> 13:45) belongs to the CURRENT calendar day.
      - Inter-session gaps map to the current calendar day (these bars should
        not normally exist, but we return a sensible value).

    A complete trading day = previous calendar day's night session + current
    calendar day's day session.
    """
    t = ts.time()
    if t >= time(15, 0):
        # Night session opened today -> belongs to tomorrow's trading day
        return (ts + timedelta(days=1)).date()
    elif t < time(5, 0):
        # Night session after midnight -> already the correct calendar day
        return ts.date()
    elif time(8, 45) <= t <= time(13, 45):
        # Day session -> current calendar day
        return ts.date()
    else:
        # Inter-session gap (05:00-08:45 or 13:45-15:00)
        return ts.date()
