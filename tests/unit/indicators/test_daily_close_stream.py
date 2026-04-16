"""Unit tests for DailyCloseStream."""
from __future__ import annotations

from datetime import datetime

from src.indicators.daily_close_stream import DailyCloseStream


def _dt(date_str: str, hour: int = 9) -> datetime:
    """Build a naive datetime for the given date string and hour."""
    return datetime.fromisoformat(f"{date_str}T{hour:02d}:00:00")


class TestDailyCloseStream:
    def test_first_update_returns_none(self) -> None:
        stream = DailyCloseStream()
        result = stream.update(100.0, _dt("2024-01-02"))
        assert result is None
        assert stream.closes == ()

    def test_same_day_updates_return_none(self) -> None:
        stream = DailyCloseStream()
        stream.update(100.0, _dt("2024-01-02", 9))
        assert stream.update(101.0, _dt("2024-01-02", 10)) is None
        assert stream.update(102.0, _dt("2024-01-02", 11)) is None
        assert stream.closes == ()

    def test_date_rollover_emits_last_price(self) -> None:
        stream = DailyCloseStream()
        stream.update(100.0, _dt("2024-01-02", 9))
        stream.update(101.0, _dt("2024-01-02", 10))
        stream.update(102.0, _dt("2024-01-02", 11))
        # First bar of day 2 triggers emission of day 1's last price (102.0)
        emitted = stream.update(200.0, _dt("2024-01-03", 9))
        assert emitted == 102.0
        assert stream.closes == (102.0,)

    def test_multi_day_stream(self) -> None:
        stream = DailyCloseStream()
        # Day 1
        stream.update(10.0, _dt("2024-01-02", 9))
        stream.update(11.0, _dt("2024-01-02", 10))
        # Day 2 — emits day 1 close (11.0)
        r1 = stream.update(20.0, _dt("2024-01-03", 9))
        stream.update(21.0, _dt("2024-01-03", 10))
        # Day 3 — emits day 2 close (21.0)
        r2 = stream.update(30.0, _dt("2024-01-04", 9))

        assert r1 == 11.0
        assert r2 == 21.0
        assert stream.closes == (11.0, 21.0)

    def test_closes_is_tuple_immutable(self) -> None:
        stream = DailyCloseStream()
        stream.update(100.0, _dt("2024-01-02"))
        stream.update(200.0, _dt("2024-01-03"))
        closes = stream.closes
        assert isinstance(closes, tuple)

    def test_reset_clears_state(self) -> None:
        stream = DailyCloseStream()
        stream.update(100.0, _dt("2024-01-02"))
        stream.update(200.0, _dt("2024-01-03"))
        assert stream.closes == (100.0,)

        stream.reset()
        assert stream.closes == ()
        # After reset, first update is treated as a fresh start
        assert stream.update(50.0, _dt("2024-01-10")) is None
        # A rollover after reset should work normally
        emitted = stream.update(60.0, _dt("2024-01-11"))
        assert emitted == 50.0
