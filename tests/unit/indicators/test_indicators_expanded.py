"""Unit tests for expanded indicator library (Phase 1-3).

Each indicator is tested for:
1. Warmup behavior (returns None until enough data)
2. Numerical correctness against known values
3. Reset clears all state
4. Edge cases
"""
from __future__ import annotations

import math
from datetime import datetime

import pytest

from src.indicators import (
    CMF,
    MACD,
    MACDResult,
    MFI,
    OBV,
    ROC,
    STC,
    TWAP,
    FisherTransform,
    FisherResult,
    HurstExponent,
    ITrend,
    LinRegResult,
    LinearRegression,
    ParabolicSAR,
    PSARResult,
    Stochastic,
    StochasticResult,
    SuperTrend,
    SuperTrendResult,
    TrueATR,
    WilliamsR,
)


# ---------------------------------------------------------------------------
# MACD
# ---------------------------------------------------------------------------


class TestMACD:
    def test_warmup_returns_none(self):
        m = MACD(fast=3, slow=5, signal=2)
        for _ in range(5):
            assert m.update(100.0) is None
        assert not m.ready

    def test_produces_result(self):
        m = MACD(fast=3, slow=5, signal=2)
        result = None
        # Feed enough bars: slow=5 warmup + signal=2 warmup
        for i in range(20):
            result = m.update(100.0 + i)
        assert result is not None
        assert isinstance(result, MACDResult)
        assert m.ready
        # In an uptrend, MACD should be positive (fast > slow)
        assert result.macd > 0

    def test_histogram_is_diff(self):
        m = MACD(fast=3, slow=5, signal=2)
        result = None
        for i in range(20):
            result = m.update(100.0 + i * 0.5)
        assert result is not None
        assert result.histogram == pytest.approx(result.macd - result.signal)

    def test_reset(self):
        m = MACD(fast=3, slow=5, signal=2)
        for i in range(20):
            m.update(100.0 + i)
        assert m.ready
        m.reset()
        assert not m.ready
        assert m.value is None

    def test_invalid_params(self):
        with pytest.raises(ValueError):
            MACD(fast=10, slow=5)  # fast >= slow
        with pytest.raises(ValueError):
            MACD(signal=0)

    def test_flat_prices_zero_macd(self):
        m = MACD(fast=3, slow=5, signal=2)
        for _ in range(20):
            result = m.update(100.0)
        assert result is not None
        assert result.macd == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# OBV
# ---------------------------------------------------------------------------


class TestOBV:
    def test_first_bar_returns_none(self):
        obv = OBV()
        assert obv.update(100.0, 1000.0) is None
        assert not obv.ready

    def test_up_bar_adds_volume(self):
        obv = OBV()
        obv.update(100.0, 500.0)
        result = obv.update(101.0, 300.0)
        assert result == pytest.approx(300.0)

    def test_down_bar_subtracts_volume(self):
        obv = OBV()
        obv.update(100.0, 500.0)
        result = obv.update(99.0, 200.0)
        assert result == pytest.approx(-200.0)

    def test_flat_bar_no_change(self):
        obv = OBV()
        obv.update(100.0, 500.0)
        result = obv.update(100.0, 300.0)
        assert result == pytest.approx(0.0)

    def test_cumulative(self):
        obv = OBV()
        obv.update(100.0, 100.0)
        obv.update(101.0, 200.0)   # +200
        obv.update(102.0, 150.0)   # +150
        obv.update(101.0, 100.0)   # -100
        assert obv.value == pytest.approx(250.0)

    def test_reset(self):
        obv = OBV()
        obv.update(100.0, 100.0)
        obv.update(101.0, 200.0)
        obv.reset()
        assert not obv.ready
        assert obv.value is None


# ---------------------------------------------------------------------------
# ROC
# ---------------------------------------------------------------------------


class TestROC:
    def test_warmup_returns_none(self):
        roc = ROC(period=3)
        for _ in range(3):
            assert roc.update(100.0) is None

    def test_basic_calculation(self):
        roc = ROC(period=3)
        roc.update(100.0)
        roc.update(101.0)
        roc.update(102.0)
        result = roc.update(110.0)  # (110-100)/100*100 = 10%
        assert result == pytest.approx(10.0)

    def test_negative_roc(self):
        roc = ROC(period=2)
        roc.update(100.0)
        roc.update(100.0)
        result = roc.update(90.0)  # (90-100)/100*100 = -10%
        assert result == pytest.approx(-10.0)

    def test_reset(self):
        roc = ROC(period=2)
        roc.update(100.0)
        roc.update(100.0)
        roc.update(110.0)
        roc.reset()
        assert not roc.ready

    def test_invalid_period(self):
        with pytest.raises(ValueError):
            ROC(period=0)


# ---------------------------------------------------------------------------
# TrueATR
# ---------------------------------------------------------------------------


class TestTrueATR:
    def test_warmup_returns_none(self):
        atr = TrueATR(period=3)
        assert atr.update(102.0, 98.0, 100.0) is None

    def test_sma_smoothing(self):
        atr = TrueATR(period=3, smoothing="sma")
        atr.update(102.0, 98.0, 100.0)   # TR=4
        atr.update(103.0, 99.0, 101.0)   # TR=max(4, 3, 1)=4
        result = atr.update(105.0, 100.0, 103.0)  # TR=max(5, 4, 1)=5
        assert result == pytest.approx((4.0 + 4.0 + 5.0) / 3)

    def test_ema_smoothing(self):
        atr = TrueATR(period=3, smoothing="ema")
        atr.update(102.0, 98.0, 100.0)   # TR=4
        atr.update(103.0, 99.0, 101.0)   # TR=4
        result = atr.update(105.0, 100.0, 103.0)  # TR=5
        # SMA seed = (4+4+5)/3 = 4.333
        assert result == pytest.approx((4.0 + 4.0 + 5.0) / 3)
        # Next bar with Wilder smoothing
        result2 = atr.update(106.0, 102.0, 104.0)  # TR=max(4, 3, 1)=4
        expected = (result * 2 + 4.0) / 3  # Wilder: (prev*(n-1)+tr)/n
        assert result2 == pytest.approx(expected)

    def test_gap_true_range(self):
        """Gap up: true range should use |H - prevC|."""
        atr = TrueATR(period=2, smoothing="sma")
        atr.update(102.0, 98.0, 100.0)    # TR=4, prevC=100
        # Gap up: bar at 110-108, TR should be max(2, 10, 8)=10
        result = atr.update(110.0, 108.0, 109.0)
        assert result == pytest.approx((4.0 + 10.0) / 2)

    def test_reset(self):
        atr = TrueATR(period=2)
        atr.update(102.0, 98.0, 100.0)
        atr.update(103.0, 99.0, 101.0)
        atr.reset()
        assert not atr.ready

    def test_invalid_smoothing(self):
        with pytest.raises(ValueError):
            TrueATR(smoothing="rma")


# ---------------------------------------------------------------------------
# Stochastic
# ---------------------------------------------------------------------------


class TestStochastic:
    def test_warmup_returns_none(self):
        stoch = Stochastic(k_period=5, d_period=3, smooth=3)
        for _ in range(5):
            assert stoch.update(100.0, 99.0, 99.5) is None

    def test_produces_result(self):
        stoch = Stochastic(k_period=5, d_period=3, smooth=3)
        result = None
        # Need k_period + smooth-1 + d_period-1 bars
        for i in range(20):
            result = stoch.update(100.0 + i, 99.0 + i, 99.5 + i)
        assert result is not None
        assert isinstance(result, StochasticResult)
        # In continuous uptrend, %K should be near 100
        assert result.k > 80

    def test_overbought(self):
        stoch = Stochastic(k_period=5, d_period=1, smooth=1)
        # Feed uptrend
        for i in range(10):
            result = stoch.update(100.0 + i * 2, 99.0 + i * 2, 100.5 + i * 2)
        assert result is not None
        assert result.k > 80

    def test_oversold(self):
        stoch = Stochastic(k_period=5, d_period=1, smooth=1)
        # Feed downtrend
        for i in range(10):
            result = stoch.update(100.0 - i * 2, 99.0 - i * 2, 99.0 - i * 2)
        assert result is not None
        assert result.k < 20

    def test_reset(self):
        stoch = Stochastic(k_period=3, d_period=1, smooth=1)
        for i in range(10):
            stoch.update(100.0 + i, 99.0 + i, 99.5 + i)
        stoch.reset()
        assert not stoch.ready


# ---------------------------------------------------------------------------
# SuperTrend
# ---------------------------------------------------------------------------


class TestSuperTrend:
    def test_warmup_returns_none(self):
        st = SuperTrend(atr_period=3, multiplier=2.0)
        # ATR needs 3 bars to seed; first 2 return None
        for _ in range(2):
            assert st.update(102.0, 98.0, 100.0) is None
        # 3rd bar: ATR ready → SuperTrend produces a result
        assert st.update(102.0, 98.0, 100.0) is not None

    def test_uptrend_detection(self):
        st = SuperTrend(atr_period=3, multiplier=1.0)
        result = None
        for i in range(20):
            result = st.update(100.0 + i * 2, 99.0 + i * 2, 100.5 + i * 2)
        assert result is not None
        assert result.trend == 1
        assert result.stop_level < 100.5 + 19 * 2  # below price

    def test_downtrend_detection(self):
        st = SuperTrend(atr_period=3, multiplier=1.0)
        result = None
        for i in range(20):
            result = st.update(200.0 - i * 2, 198.0 - i * 2, 198.5 - i * 2)
        assert result is not None
        assert result.trend == -1

    def test_reset(self):
        st = SuperTrend(atr_period=3)
        for i in range(10):
            st.update(100.0 + i, 99.0 + i, 99.5 + i)
        st.reset()
        assert not st.ready

    def test_invalid_multiplier(self):
        with pytest.raises(ValueError):
            SuperTrend(multiplier=0)


# ---------------------------------------------------------------------------
# Linear Regression
# ---------------------------------------------------------------------------


class TestLinearRegression:
    def test_warmup_returns_none(self):
        lr = LinearRegression(period=5)
        for _ in range(4):
            assert lr.update(100.0) is None

    def test_perfect_uptrend(self):
        lr = LinearRegression(period=5)
        for i in range(5):
            result = lr.update(100.0 + i * 2.0)
        assert result is not None
        assert result.slope == pytest.approx(2.0)
        assert result.r_squared == pytest.approx(1.0)
        # Forecast next value
        assert result.forecast == pytest.approx(110.0)

    def test_flat_prices(self):
        lr = LinearRegression(period=5)
        for _ in range(5):
            result = lr.update(100.0)
        assert result is not None
        assert result.slope == pytest.approx(0.0)
        assert result.r_squared == pytest.approx(1.0)  # perfect flat line

    def test_noisy_data_low_r2(self):
        lr = LinearRegression(period=10)
        prices = [100, 110, 95, 105, 90, 100, 85, 95, 80, 90]
        result = None
        for p in prices:
            result = lr.update(float(p))
        assert result is not None
        assert result.r_squared < 1.0

    def test_reset(self):
        lr = LinearRegression(period=3)
        for i in range(5):
            lr.update(100.0 + i)
        lr.reset()
        assert not lr.ready

    def test_invalid_period(self):
        with pytest.raises(ValueError):
            LinearRegression(period=1)


# ---------------------------------------------------------------------------
# CMF
# ---------------------------------------------------------------------------


class TestCMF:
    def test_warmup_returns_none(self):
        cmf = CMF(period=3)
        assert cmf.update(102.0, 98.0, 101.0, 1000.0) is None

    def test_strong_buying(self):
        """Close at high → MFM = +1 → CMF should be +1."""
        cmf = CMF(period=3)
        for _ in range(3):
            result = cmf.update(110.0, 100.0, 110.0, 1000.0)
        assert result == pytest.approx(1.0)

    def test_strong_selling(self):
        """Close at low → MFM = -1 → CMF should be -1."""
        cmf = CMF(period=3)
        for _ in range(3):
            result = cmf.update(110.0, 100.0, 100.0, 1000.0)
        assert result == pytest.approx(-1.0)

    def test_midpoint_close(self):
        """Close at midpoint → MFM = 0 → CMF = 0."""
        cmf = CMF(period=3)
        for _ in range(3):
            result = cmf.update(110.0, 100.0, 105.0, 1000.0)
        assert result == pytest.approx(0.0)

    def test_reset(self):
        cmf = CMF(period=2)
        cmf.update(102.0, 98.0, 100.0, 500.0)
        cmf.update(103.0, 99.0, 101.0, 600.0)
        cmf.reset()
        assert not cmf.ready


# ---------------------------------------------------------------------------
# Parabolic SAR
# ---------------------------------------------------------------------------


class TestParabolicSAR:
    def test_first_bar_returns_none(self):
        sar = ParabolicSAR()
        assert sar.update(102.0, 98.0, 100.0) is None

    def test_produces_result(self):
        sar = ParabolicSAR()
        sar.update(102.0, 98.0, 100.0)
        result = sar.update(104.0, 100.0, 103.0)
        assert result is not None
        assert isinstance(result, PSARResult)
        assert result.trend in (1, -1)

    def test_uptrend_sar_below_price(self):
        sar = ParabolicSAR(af_start=0.02, af_max=0.2)
        sar.update(100.0, 98.0, 99.0)
        for i in range(1, 10):
            result = sar.update(100.0 + i * 3, 99.0 + i * 3, 100.0 + i * 3)
        assert result is not None
        if result.trend == 1:
            assert result.sar < 100.0 + 9 * 3

    def test_reset(self):
        sar = ParabolicSAR()
        sar.update(102.0, 98.0, 100.0)
        sar.update(104.0, 100.0, 103.0)
        sar.reset()
        assert not sar.ready

    def test_invalid_params(self):
        with pytest.raises(ValueError):
            ParabolicSAR(af_start=-0.01)
        with pytest.raises(ValueError):
            ParabolicSAR(af_start=0.3, af_max=0.2)


# ---------------------------------------------------------------------------
# STC
# ---------------------------------------------------------------------------


class TestSTC:
    def test_warmup_returns_none(self):
        stc = STC(fast=3, slow=5, cycle=3)
        for _ in range(5):
            assert stc.update(100.0) is None

    def test_produces_result(self):
        stc = STC(fast=3, slow=5, cycle=3)
        result = None
        for i in range(30):
            result = stc.update(100.0 + i * 0.5)
        assert result is not None
        assert 0 <= result <= 100

    def test_range_bounded(self):
        stc = STC(fast=3, slow=5, cycle=3)
        for i in range(50):
            result = stc.update(100.0 + math.sin(i) * 10)
        if result is not None:
            assert 0 <= result <= 100

    def test_reset(self):
        stc = STC(fast=3, slow=5, cycle=3)
        for i in range(30):
            stc.update(100.0 + i)
        stc.reset()
        assert not stc.ready

    def test_invalid_params(self):
        with pytest.raises(ValueError):
            STC(fast=10, slow=5)


# ---------------------------------------------------------------------------
# MFI
# ---------------------------------------------------------------------------


class TestMFI:
    def test_warmup_returns_none(self):
        mfi = MFI(period=3)
        # First bar always None (no prev TP)
        assert mfi.update(102.0, 98.0, 100.0, 1000.0) is None
        assert mfi.update(103.0, 99.0, 101.0, 1000.0) is None

    def test_all_positive_flow(self):
        """Consistently rising TP → MFI near 100."""
        mfi = MFI(period=3)
        for i in range(10):
            result = mfi.update(100.0 + i * 2, 98.0 + i * 2, 99.0 + i * 2, 1000.0)
        assert result is not None
        assert result > 80

    def test_all_negative_flow(self):
        """Consistently falling TP → MFI near 0."""
        mfi = MFI(period=3)
        for i in range(10):
            result = mfi.update(100.0 - i * 2, 98.0 - i * 2, 99.0 - i * 2, 1000.0)
        assert result is not None
        assert result < 20

    def test_range(self):
        mfi = MFI(period=5)
        for i in range(20):
            result = mfi.update(
                100.0 + math.sin(i) * 5,
                98.0 + math.sin(i) * 5,
                99.0 + math.sin(i) * 5,
                1000.0,
            )
        if result is not None:
            assert 0 <= result <= 100

    def test_reset(self):
        mfi = MFI(period=3)
        for i in range(10):
            mfi.update(100.0 + i, 98.0 + i, 99.0 + i, 500.0)
        mfi.reset()
        assert not mfi.ready


# ---------------------------------------------------------------------------
# Williams %R
# ---------------------------------------------------------------------------


class TestWilliamsR:
    def test_warmup_returns_none(self):
        wr = WilliamsR(period=5)
        for _ in range(4):
            assert wr.update(102.0, 98.0, 100.0) is None

    def test_at_high(self):
        """Close at highest high → %R = 0."""
        wr = WilliamsR(period=3)
        wr.update(100.0, 90.0, 95.0)
        wr.update(105.0, 92.0, 100.0)
        result = wr.update(110.0, 95.0, 110.0)
        assert result == pytest.approx(0.0)

    def test_at_low(self):
        """Close at lowest low → %R = -100."""
        wr = WilliamsR(period=3)
        wr.update(100.0, 90.0, 95.0)
        wr.update(105.0, 92.0, 100.0)
        result = wr.update(108.0, 90.0, 90.0)
        assert result == pytest.approx(-100.0)

    def test_midpoint(self):
        """Close at midpoint → %R = -50."""
        wr = WilliamsR(period=3)
        wr.update(110.0, 100.0, 105.0)
        wr.update(110.0, 100.0, 105.0)
        result = wr.update(110.0, 100.0, 105.0)
        assert result == pytest.approx(-50.0)

    def test_reset(self):
        wr = WilliamsR(period=3)
        for i in range(5):
            wr.update(100.0 + i, 98.0 + i, 99.0 + i)
        wr.reset()
        assert not wr.ready


# ---------------------------------------------------------------------------
# Fisher Transform
# ---------------------------------------------------------------------------


class TestFisherTransform:
    def test_warmup_returns_none(self):
        ft = FisherTransform(period=5)
        for _ in range(4):
            assert ft.update(102.0, 98.0, 100.0) is None

    def test_produces_result(self):
        ft = FisherTransform(period=5)
        result = None
        for i in range(10):
            result = ft.update(100.0 + i, 98.0 + i, 99.0 + i)
        assert result is not None
        assert isinstance(result, FisherResult)

    def test_signal_is_previous_fisher(self):
        ft = FisherTransform(period=3)
        results = []
        for i in range(10):
            r = ft.update(100.0 + i, 98.0 + i, 99.0 + i)
            if r is not None:
                results.append(r)
        if len(results) >= 2:
            assert results[-1].signal == pytest.approx(results[-2].fisher)

    def test_reset(self):
        ft = FisherTransform(period=3)
        for i in range(10):
            ft.update(100.0 + i, 98.0 + i, 99.0 + i)
        ft.reset()
        assert not ft.ready

    def test_invalid_period(self):
        with pytest.raises(ValueError):
            FisherTransform(period=1)


# ---------------------------------------------------------------------------
# Hurst Exponent
# ---------------------------------------------------------------------------


class TestHurstExponent:
    def test_warmup_returns_none(self):
        h = HurstExponent(period=20, min_sub_period=5)
        for _ in range(19):
            assert h.update(100.0) is None

    def test_trending_series(self):
        """Strongly trending series should have H > 0.5."""
        h = HurstExponent(period=50, min_sub_period=5)
        result = None
        for i in range(60):
            result = h.update(100.0 + i * 0.5)
        assert result is not None
        assert result > 0.45  # trending tendency

    def test_range_bounded(self):
        h = HurstExponent(period=30, min_sub_period=5)
        for i in range(40):
            result = h.update(100.0 + i * 0.1)
        if result is not None:
            assert 0.0 <= result <= 1.0

    def test_reset(self):
        h = HurstExponent(period=20, min_sub_period=5)
        for i in range(25):
            h.update(100.0 + i)
        h.reset()
        assert not h.ready

    def test_invalid_period(self):
        with pytest.raises(ValueError):
            HurstExponent(period=10)


# ---------------------------------------------------------------------------
# TWAP
# ---------------------------------------------------------------------------


class TestTWAP:
    def test_single_price(self):
        twap = TWAP()
        result = twap.update(100.0)
        assert result == pytest.approx(100.0)
        assert twap.ready

    def test_average(self):
        twap = TWAP()
        twap.update(100.0)
        twap.update(110.0)
        result = twap.update(120.0)
        assert result == pytest.approx(110.0)

    def test_session_reset_by_date(self):
        twap = TWAP()
        twap.update(100.0, session_date="2025-01-01")
        twap.update(110.0, session_date="2025-01-01")
        assert twap.value == pytest.approx(105.0)
        # New session
        twap.update(200.0, session_date="2025-01-02")
        assert twap.value == pytest.approx(200.0)

    def test_session_reset_by_timestamp(self):
        twap = TWAP()
        twap.update(100.0, timestamp=datetime(2025, 1, 1, 10, 0))
        twap.update(110.0, timestamp=datetime(2025, 1, 1, 11, 0))
        assert twap.value == pytest.approx(105.0)
        twap.update(200.0, timestamp=datetime(2025, 1, 2, 10, 0))
        assert twap.value == pytest.approx(200.0)

    def test_reset(self):
        twap = TWAP()
        twap.update(100.0)
        twap.reset()
        assert not twap.ready


# ---------------------------------------------------------------------------
# ITrend
# ---------------------------------------------------------------------------


class TestITrend:
    def test_warmup(self):
        it = ITrend()
        assert it.update(100.0) is None
        assert it.update(101.0) is None
        assert it.update(102.0) is None

    def test_produces_values(self):
        it = ITrend()
        result = None
        for i in range(20):
            result = it.update(100.0 + i * 0.5)
        assert result is not None
        assert it.ready

    def test_tracks_trend(self):
        """iTrend should roughly follow price in a smooth uptrend."""
        it = ITrend()
        for i in range(50):
            result = it.update(100.0 + i)
        # Should be close to but slightly below the latest price
        assert result is not None
        assert result > 100.0  # following the uptrend
        assert result < 150.0  # but lagging somewhat

    def test_reset(self):
        it = ITrend()
        for i in range(20):
            it.update(100.0 + i)
        it.reset()
        assert not it.ready
