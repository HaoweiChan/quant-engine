"""Tests for src.data.session_utils — TAIFEX session topology."""
from __future__ import annotations

from datetime import date, datetime

import pytest

from src.data.session_utils import (
    DAY_CLOSE,
    DAY_OPEN,
    NIGHT_CLOSE,
    NIGHT_OPEN,
    is_new_session,
    session_id,
    trading_day,
)


# ── trading_day() ─────────────────────────────────────────────────────────────

class TestTradingDay:
    """Verify that timestamps map to the correct TAIFEX trading day."""

    def test_night_session_same_evening(self):
        # Monday 16:00 -> Tuesday's trading day
        ts = datetime(2024, 1, 15, 16, 0)  # Monday
        assert trading_day(ts) == date(2024, 1, 16)  # Tuesday

    def test_night_session_after_midnight(self):
        # Tuesday 04:59 -> Tuesday's trading day (night session opened Monday)
        ts = datetime(2024, 1, 16, 4, 59)
        assert trading_day(ts) == date(2024, 1, 16)  # Tuesday

    def test_day_session_open(self):
        # Tuesday 08:45 -> Tuesday's trading day
        ts = datetime(2024, 1, 16, 8, 45)
        assert trading_day(ts) == date(2024, 1, 16)

    def test_day_session_close(self):
        # Tuesday 13:45 -> Tuesday's trading day
        ts = datetime(2024, 1, 16, 13, 45)
        assert trading_day(ts) == date(2024, 1, 16)

    def test_day_session_mid(self):
        # Tuesday 09:30 -> Tuesday's trading day
        ts = datetime(2024, 1, 16, 9, 30)
        assert trading_day(ts) == date(2024, 1, 16)

    def test_inter_session_morning_gap(self):
        # 06:00 is between night close (05:00) and day open (08:45)
        ts = datetime(2024, 1, 16, 6, 0)
        assert trading_day(ts) == date(2024, 1, 16)

    def test_inter_session_afternoon_gap(self):
        # 14:30 is between day close (13:45) and night open (15:00)
        ts = datetime(2024, 1, 16, 14, 30)
        assert trading_day(ts) == date(2024, 1, 16)

    def test_night_open_boundary(self):
        # Exactly 15:00 -> next day's trading day
        ts = datetime(2024, 1, 15, 15, 0)  # Monday 15:00
        assert trading_day(ts) == date(2024, 1, 16)  # Tuesday

    def test_friday_night_session(self):
        # Friday 16:00 -> Saturday (the exchange maps this to Monday's
        # trading day in practice, but the function returns the raw +1 day;
        # weekend handling is a calendar concern, not a timestamp concern)
        ts = datetime(2024, 1, 19, 16, 0)  # Friday
        assert trading_day(ts) == date(2024, 1, 20)  # Saturday

    def test_saturday_early_morning(self):
        # Saturday 04:00 -> Saturday (part of Friday's night session)
        ts = datetime(2024, 1, 20, 4, 0)
        assert trading_day(ts) == date(2024, 1, 20)  # Saturday

    def test_night_and_day_same_trading_day(self):
        # Mon 16:00 night session and Tue 09:00 day session -> same trading day
        night_ts = datetime(2024, 1, 15, 16, 0)
        day_ts = datetime(2024, 1, 16, 9, 0)
        assert trading_day(night_ts) == trading_day(day_ts) == date(2024, 1, 16)


# ── session_id() ──────────────────────────────────────────────────────────────

class TestSessionId:
    def test_night_session_evening(self):
        ts = datetime(2024, 1, 15, 16, 0)
        assert session_id(ts) == "N20240115"

    def test_night_session_after_midnight(self):
        ts = datetime(2024, 1, 16, 4, 55)
        assert session_id(ts) == "N20240115"

    def test_day_session(self):
        ts = datetime(2024, 1, 16, 9, 30)
        assert session_id(ts) == "D20240116"

    def test_closed_inter_session(self):
        ts = datetime(2024, 1, 16, 14, 0)
        assert session_id(ts) == "CLOSED"


# ── is_new_session() ─────────────────────────────────────────────────────────

class TestIsNewSession:
    def test_same_night_session(self):
        a = datetime(2024, 1, 15, 23, 0)
        b = datetime(2024, 1, 16, 1, 0)
        assert is_new_session(a, b) is False

    def test_night_to_day(self):
        a = datetime(2024, 1, 16, 4, 50)
        b = datetime(2024, 1, 16, 8, 45)
        assert is_new_session(a, b) is True
