"""Tests for ``src/core/clock.py``."""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

import pytest

from src.core.clock import Clock, SimulatedClock, WallClock, default_clock


class TestWallClock:
    def test_now_returns_aware_utc_datetime(self) -> None:
        clk = WallClock()
        ts = clk.now()
        assert ts.tzinfo is not None
        assert ts.utcoffset() == timedelta(0)

    def test_now_close_to_actual_now(self) -> None:
        clk = WallClock()
        before = datetime.now(timezone.utc)
        ts = clk.now()
        after = datetime.now(timezone.utc)
        assert before <= ts <= after

    def test_monotonic_increases(self) -> None:
        clk = WallClock()
        a = clk.monotonic()
        time.sleep(0.005)
        b = clk.monotonic()
        assert b > a

    def test_satisfies_protocol(self) -> None:
        assert isinstance(WallClock(), Clock)


class TestSimulatedClock:
    def test_initial_time_defaults_to_2026(self) -> None:
        clk = SimulatedClock()
        assert clk.now() == datetime(2026, 1, 1, tzinfo=timezone.utc)

    def test_advance_with_seconds(self) -> None:
        clk = SimulatedClock(datetime(2026, 4, 25, 12, 0, tzinfo=timezone.utc))
        clk.advance(60)
        assert clk.now() == datetime(2026, 4, 25, 12, 1, tzinfo=timezone.utc)
        assert clk.monotonic() == 60.0

    def test_advance_with_timedelta(self) -> None:
        clk = SimulatedClock(datetime(2026, 4, 25, 12, 0, tzinfo=timezone.utc))
        clk.advance(timedelta(minutes=5))
        assert clk.now() == datetime(2026, 4, 25, 12, 5, tzinfo=timezone.utc)
        assert clk.monotonic() == 300.0

    def test_set_jumps_forward(self) -> None:
        clk = SimulatedClock(datetime(2026, 4, 25, 12, 0, tzinfo=timezone.utc))
        clk.set(datetime(2026, 4, 25, 13, 0, tzinfo=timezone.utc))
        assert clk.now() == datetime(2026, 4, 25, 13, 0, tzinfo=timezone.utc)
        assert clk.monotonic() == 3600.0

    def test_naive_initial_promoted_to_utc(self) -> None:
        clk = SimulatedClock(datetime(2026, 4, 25, 12, 0))
        assert clk.now().tzinfo is not None

    def test_cannot_move_backwards_via_advance(self) -> None:
        clk = SimulatedClock()
        with pytest.raises(ValueError, match="cannot move backwards"):
            clk.advance(-1)

    def test_cannot_move_backwards_via_set(self) -> None:
        clk = SimulatedClock(datetime(2026, 4, 25, 12, 0, tzinfo=timezone.utc))
        with pytest.raises(ValueError, match="cannot move backwards"):
            clk.set(datetime(2026, 4, 25, 11, 0, tzinfo=timezone.utc))

    def test_satisfies_protocol(self) -> None:
        assert isinstance(SimulatedClock(), Clock)


class TestDefaultClock:
    def test_default_clock_is_singleton_wallclock(self) -> None:
        a = default_clock()
        b = default_clock()
        assert a is b
        assert isinstance(a, WallClock)
