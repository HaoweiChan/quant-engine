"""Unit tests for src.indicators.realized_vol.RealizedVol."""
from __future__ import annotations

import math

import pytest

from src.indicators.realized_vol import RealizedVol


class TestWarmup:
    def test_warmup_returns_none(self):
        """First period-1 updates return None; period-th update returns a value."""
        rv = RealizedVol(period=5)
        # Need 5 returns -> 6 close prices, but update() takes pairs directly.
        # Feed 4 returns -> still in warmup.
        closes = [100.0, 101.0, 102.0, 101.5, 103.0, 104.0]
        results = []
        for i in range(1, len(closes)):
            results.append(rv.update(closes[i - 1], closes[i]))
        # First 4 calls (period-1=4) should be None; 5th should be a float.
        assert all(r is None for r in results[:4])
        assert results[4] is not None
        assert isinstance(results[4], float)


class TestConstantReturns:
    def test_constant_returns_zero_vol(self):
        """Feeding a constant price series produces 0 realized volatility."""
        rv = RealizedVol(period=5)
        for _ in range(6):
            val = rv.update(100.0, 100.0)
        # log(100/100) = 0 for every return -> std = 0 -> vol = 0
        assert val == pytest.approx(0.0)


class TestAnnualizationFactor:
    def test_annualization_factor(self):
        """Known std of daily log-returns yields std * sqrt(252)."""
        period = 5
        rv = RealizedVol(period=period)
        # Construct a price series that produces daily log-returns of alternating
        # +r and -r so the mean is 0 and we can compute expected vol analytically.
        # returns: [r, -r, r, -r, r]  with r = 0.01
        r = 0.01
        # Build close prices: start at 100, apply each log-return via exp.
        prices = [100.0]
        returns_sequence = [r, -r, r, -r, r]
        for ret in returns_sequence:
            prices.append(prices[-1] * math.exp(ret))

        val = None
        for i in range(1, len(prices)):
            val = rv.update(prices[i - 1], prices[i])

        # Population std of [r, -r, r, -r, r]: mean = r/5, but let's compute directly.
        mean_r = sum(returns_sequence) / len(returns_sequence)
        var = sum((x - mean_r) ** 2 for x in returns_sequence) / len(returns_sequence)
        expected = math.sqrt(var * 252)
        assert val == pytest.approx(expected, rel=1e-9)


class TestReset:
    def test_reset_clears_state(self):
        """After reset(), update returns None again for the full warmup period."""
        rv = RealizedVol(period=5)
        for i in range(6):
            rv.update(100.0 + i, 101.0 + i)
        assert rv.ready

        rv.reset()
        assert not rv.ready
        assert rv.value is None

        # One more update should still be None (warmup restarted).
        result = rv.update(100.0, 101.0)
        assert result is None


class TestInvalidPeriod:
    def test_invalid_period_raises(self):
        """RealizedVol(1) raises ValueError."""
        with pytest.raises(ValueError, match="period"):
            RealizedVol(1)

    def test_period_zero_raises(self):
        """RealizedVol(0) raises ValueError."""
        with pytest.raises(ValueError, match="period"):
            RealizedVol(0)


class TestPrevCloseZeroGuard:
    def test_prev_close_zero_does_not_crash(self):
        """update(0, 100) does not crash and returns prior value."""
        rv = RealizedVol(period=5)
        # Prime with valid data to get a prior value.
        for i in range(6):
            rv.update(100.0 + i, 101.0 + i)
        prior = rv.value
        assert prior is not None

        # Now feed a zero prev_close — should return the prior value unchanged.
        result = rv.update(0.0, 100.0)
        assert result == prior

    def test_prev_close_zero_during_warmup(self):
        """update(0, 100) during warmup returns None (prior value is None)."""
        rv = RealizedVol(period=5)
        result = rv.update(0.0, 100.0)
        assert result is None
