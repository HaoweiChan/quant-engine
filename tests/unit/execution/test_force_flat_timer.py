"""Unit tests for the LivePipelineManager session-close fallback timer
(Phase B3).

LiveStrategyRunner.on_bar_complete calls _force_flat only when a bar
arrives at exactly 04:59 / 13:44 Taipei. If the broker tick stream gaps
near session close, no bar arrives, no force_flat fires, and positions
silently carry into the next session — violating the intraday flat
rule. The timer in LivePipelineManager fires unconditionally 30s after
each session-close minute as a safety net.
"""
from __future__ import annotations

from datetime import datetime, time as dt_time, timedelta, timezone

from src.execution.live_pipeline import (
    LivePipelineManager,
    _DAY_FORCE_FLAT_TIME,
    _NIGHT_FORCE_FLAT_TIME,
)


_TAIPEI_TZ = timezone(timedelta(hours=8))


def _at(hour: int, minute: int, second: int = 0) -> datetime:
    return datetime(2026, 4, 18, hour, minute, second, tzinfo=_TAIPEI_TZ)


def test_constants_align_with_session_close_minutes() -> None:
    """The fallback fires 30s AFTER the last tradeable bar of each session.

    Night session: last bar 04:59 -> fallback 04:59:30.
    Day   session: last bar 13:44 -> fallback 13:44:30.
    """
    assert _NIGHT_FORCE_FLAT_TIME == dt_time(4, 59, 30)
    assert _DAY_FORCE_FLAT_TIME == dt_time(13, 44, 30)


def test_next_force_flat_at_picks_day_close_when_after_night() -> None:
    """Mid-morning -> next wake is the day session close at 13:44:30."""
    next_at = LivePipelineManager._next_force_flat_at(_at(10, 0))
    assert next_at.time() == dt_time(13, 44, 30)
    assert next_at.date() == _at(10, 0).date()


def test_next_force_flat_at_picks_night_close_when_before_night() -> None:
    """Pre-dawn -> next wake is night session close at 04:59:30 same day."""
    next_at = LivePipelineManager._next_force_flat_at(_at(2, 30))
    assert next_at.time() == dt_time(4, 59, 30)
    assert next_at.date() == _at(2, 30).date()


def test_next_force_flat_at_rolls_into_tomorrow_after_last_close() -> None:
    """After 13:44:30 with no other slot today -> wake at 04:59:30 tomorrow."""
    now = _at(14, 0)
    next_at = LivePipelineManager._next_force_flat_at(now)
    assert next_at.time() == dt_time(4, 59, 30)
    assert next_at.date() == (now + timedelta(days=1)).date()


def test_next_force_flat_at_handles_evening_window() -> None:
    """During TAIFEX night session (e.g. 22:00) -> wake at next morning 04:59:30."""
    now = _at(22, 0)
    next_at = LivePipelineManager._next_force_flat_at(now)
    assert next_at.time() == dt_time(4, 59, 30)
    # 22:00 today -> 04:59:30 tomorrow.
    assert next_at.date() == (now + timedelta(days=1)).date()


def test_next_force_flat_at_at_exact_boundary_picks_next_slot() -> None:
    """If `now` equals a wake time exactly, pick the NEXT slot (not the
    current one — we don't want a double-fire).
    """
    now = _at(4, 59, 30)
    next_at = LivePipelineManager._next_force_flat_at(now)
    assert next_at.time() == dt_time(13, 44, 30)
    assert next_at.date() == now.date()
