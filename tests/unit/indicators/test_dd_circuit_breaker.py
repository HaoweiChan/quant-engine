"""Unit tests for DDCircuitBreaker indicator."""
from __future__ import annotations

import pytest

from src.indicators import DDCircuitBreaker


class TestInitialState:
    def test_initial_state_not_tripped(self) -> None:
        b = DDCircuitBreaker()
        assert not b.tripped
        assert b.current_dd == 0.0
        assert b.peak_price == 0.0


class TestTripConditions:
    def test_trip_requires_dd_and_below_sma(self) -> None:
        """dd >= breaker alone does NOT trip; both conditions required."""
        b = DDCircuitBreaker(breaker_pct=0.15, reentry_pct=0.05)
        # Establish peak
        b.update(100.0, below_sma=False)
        # Price drops 20 % but we are ABOVE SMA — must not trip
        b.update(80.0, below_sma=False)
        assert not b.tripped

        # Same drop but now below SMA — must trip
        b2 = DDCircuitBreaker(breaker_pct=0.15, reentry_pct=0.05)
        b2.update(100.0, below_sma=False)
        b2.update(80.0, below_sma=True)
        assert b2.tripped

    def test_no_trip_when_dd_below_breaker_pct(self) -> None:
        """Small drawdown below breaker_pct never trips even below SMA."""
        b = DDCircuitBreaker(breaker_pct=0.15, reentry_pct=0.05)
        b.update(100.0, below_sma=False)
        b.update(90.0, below_sma=True)  # 10 % dd, breaker is 15 %
        assert not b.tripped


class TestReentryConditions:
    def test_reentry_on_dd_recovery(self) -> None:
        """After trip, reducing dd to <= reentry_pct un-trips the breaker."""
        b = DDCircuitBreaker(breaker_pct=0.15, reentry_pct=0.05)
        b.update(100.0, below_sma=False)
        b.update(80.0, below_sma=True)   # trip: dd=0.20, below_sma
        assert b.tripped

        # Price recovers to dd=0.04 while still below SMA — should un-trip
        b.update(96.0, below_sma=True)   # dd = 1 - 96/100 = 0.04
        assert not b.tripped

    def test_reentry_on_sma_recovery(self) -> None:
        """After trip, price back above SMA un-trips even if DD still deep."""
        b = DDCircuitBreaker(breaker_pct=0.15, reentry_pct=0.05)
        b.update(100.0, below_sma=False)
        b.update(80.0, below_sma=True)   # trip: dd=0.20
        assert b.tripped

        # dd is still 0.20 (> reentry_pct=0.05) but price crosses above SMA
        b.update(80.0, below_sma=False)
        assert not b.tripped


class TestHysteresis:
    def test_hysteresis_no_flip_flop(self) -> None:
        """Oscillating between dd=0.12 and dd=0.08 below SMA stays stable.

        breaker_pct=0.15, reentry_pct=0.05:
        - Neither 0.12 nor 0.08 triggers the breaker (both < 0.15)
        - So state stays ACTIVE throughout; no flip-flop.
        """
        b = DDCircuitBreaker(breaker_pct=0.15, reentry_pct=0.05)
        b.update(100.0, below_sma=False)  # set peak
        for _ in range(5):
            b.update(88.0, below_sma=True)   # dd ~0.12
            assert not b.tripped
            b.update(92.0, below_sma=True)   # dd ~0.08
            assert not b.tripped

    def test_hysteresis_stays_tripped_between_thresholds(self) -> None:
        """Once tripped, dd oscillating between reentry and breaker stays tripped."""
        b = DDCircuitBreaker(breaker_pct=0.15, reentry_pct=0.05)
        b.update(100.0, below_sma=False)
        b.update(80.0, below_sma=True)   # trip: dd=0.20
        assert b.tripped

        # Oscillate between dd=0.10 and dd=0.08 (both > reentry=0.05, below SMA)
        for _ in range(5):
            b.update(90.0, below_sma=True)   # dd=0.10 — above reentry, stays tripped
            assert b.tripped
            b.update(92.0, below_sma=True)   # dd=0.08 — above reentry, stays tripped
            assert b.tripped


class TestPeakTracking:
    def test_peak_price_tracks_high_water_mark(self) -> None:
        b = DDCircuitBreaker()
        b.update(50.0, below_sma=False)
        assert b.peak_price == 50.0
        b.update(80.0, below_sma=False)
        assert b.peak_price == 80.0
        b.update(60.0, below_sma=False)
        assert b.peak_price == 80.0  # peak unchanged after pullback

    def test_current_dd_calculation(self) -> None:
        b = DDCircuitBreaker()
        b.update(100.0, below_sma=False)
        b.update(75.0, below_sma=False)
        assert abs(b.current_dd - 0.25) < 1e-9


class TestReset:
    def test_reset_clears_state(self) -> None:
        b = DDCircuitBreaker(breaker_pct=0.15, reentry_pct=0.05)
        b.update(100.0, below_sma=False)
        b.update(80.0, below_sma=True)
        assert b.tripped
        b.reset()
        assert not b.tripped
        assert b.current_dd == 0.0
        assert b.peak_price == 0.0


class TestValidation:
    def test_reentry_gt_breaker_raises(self) -> None:
        with pytest.raises(ValueError):
            DDCircuitBreaker(breaker_pct=0.05, reentry_pct=0.10)

    def test_reentry_equal_breaker_raises(self) -> None:
        with pytest.raises(ValueError):
            DDCircuitBreaker(breaker_pct=0.10, reentry_pct=0.10)
