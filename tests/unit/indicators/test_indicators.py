"""Unit tests for src/indicators streaming indicators.

Each indicator is tested for:
1. Warmup behavior (returns None until enough data)
2. Numerical correctness against known values
3. Reset clears all state
4. Edge cases
"""
from __future__ import annotations

import math
from datetime import date, datetime

import pytest

from src.indicators import (
    ADX,
    ATR,
    EMA,
    RSI,
    SMA,
    VWAP,
    ATRPercentile,
    BollingerBands,
    Donchian,
    KeltnerChannel,
    SmoothedATR,
    ema_step,
)

# ---------------------------------------------------------------------------
# EMA
# ---------------------------------------------------------------------------


class TestEMA:
    def test_warmup_returns_none(self):
        ema = EMA(period=3)
        assert ema.update(10.0) is None
        assert ema.update(11.0) is None
        assert not ema.ready

    def test_seed_is_sma(self):
        ema = EMA(period=3)
        ema.update(10.0)
        ema.update(11.0)
        result = ema.update(12.0)
        assert result == pytest.approx(11.0)  # SMA of [10, 11, 12]

    def test_subsequent_updates(self):
        ema = EMA(period=3)
        for p in [10.0, 11.0, 12.0]:
            ema.update(p)
        # EMA after seed: k=2/4=0.5, EMA = 13*0.5 + 11*0.5 = 12.0
        result = ema.update(13.0)
        assert result == pytest.approx(12.0)

    def test_reset(self):
        ema = EMA(period=2)
        ema.update(10.0)
        ema.update(20.0)
        assert ema.ready
        ema.reset()
        assert not ema.ready
        assert ema.value is None
        assert ema.count == 0

    def test_period_1(self):
        ema = EMA(period=1)
        assert ema.update(5.0) == pytest.approx(5.0)
        # k=2/2=1.0, so EMA = price always
        assert ema.update(10.0) == pytest.approx(10.0)

    def test_invalid_period(self):
        with pytest.raises(ValueError):
            EMA(period=0)


class TestEmaStep:
    def test_seed_from_buffer(self):
        closes = [10.0, 11.0, 12.0]
        result = ema_step(None, 12.0, 3, closes)
        assert result == pytest.approx(11.0)

    def test_not_enough_seed(self):
        result = ema_step(None, 5.0, 10, [1.0, 2.0])
        assert result == pytest.approx(5.0)

    def test_incremental(self):
        # k = 2/4 = 0.5
        result = ema_step(10.0, 14.0, 3, [])
        assert result == pytest.approx(12.0)


# ---------------------------------------------------------------------------
# SMA
# ---------------------------------------------------------------------------


class TestSMA:
    def test_warmup(self):
        sma = SMA(period=3)
        assert sma.update(10.0) is None
        assert sma.update(20.0) is None

    def test_value(self):
        sma = SMA(period=3)
        sma.update(10.0)
        sma.update(20.0)
        result = sma.update(30.0)
        assert result == pytest.approx(20.0)

    def test_rolling(self):
        sma = SMA(period=2)
        sma.update(10.0)
        sma.update(20.0)  # -> 15
        result = sma.update(30.0)  # -> 25
        assert result == pytest.approx(25.0)

    def test_reset(self):
        sma = SMA(period=2)
        sma.update(10.0)
        sma.update(20.0)
        sma.reset()
        assert not sma.ready
        assert sma.value is None


# ---------------------------------------------------------------------------
# VWAP
# ---------------------------------------------------------------------------


class TestVWAP:
    def test_single_bar(self):
        vwap = VWAP()
        result = vwap.update(100.0, 10.0)
        assert result == pytest.approx(100.0)

    def test_cumulative(self):
        vwap = VWAP()
        vwap.update(100.0, 10.0, timestamp=datetime(2025, 1, 1, 9, 0))
        result = vwap.update(110.0, 20.0, timestamp=datetime(2025, 1, 1, 9, 5))
        # (100*10 + 110*20) / 30 = 3200/30 = 106.667
        assert result == pytest.approx(3200.0 / 30.0)

    def test_session_reset_on_date_change(self):
        vwap = VWAP()
        vwap.update(100.0, 10.0, timestamp=datetime(2025, 1, 1, 9, 0))
        result = vwap.update(200.0, 5.0, timestamp=datetime(2025, 1, 2, 9, 0))
        # New session, so only second bar counts
        assert result == pytest.approx(200.0)

    def test_explicit_session_date(self):
        vwap = VWAP()
        vwap.update(100.0, 10.0, session_date=date(2025, 1, 1))
        vwap.update(110.0, 20.0, session_date=date(2025, 1, 1))
        result = vwap.update(50.0, 5.0, session_date=date(2025, 1, 2))
        assert result == pytest.approx(50.0)  # reset

    def test_zero_volume(self):
        vwap = VWAP()
        result = vwap.update(100.0, 0.0)
        assert result is None

    def test_reset(self):
        vwap = VWAP()
        vwap.update(100.0, 10.0)
        vwap.reset()
        assert not vwap.ready
        assert vwap.value is None


# ---------------------------------------------------------------------------
# ADX
# ---------------------------------------------------------------------------


class TestADX:
    def test_warmup_first_bar_none(self):
        adx = ADX(period=14)
        assert adx.update(100.0) is None

    def test_produces_value_after_warmup(self):
        adx = ADX(period=5)
        prices = [100, 102, 101, 104, 103, 106, 105, 108, 107, 110]
        results = [adx.update(float(p)) for p in prices]
        # Should produce some non-None values after initial bars
        non_none = [r for r in results if r is not None]
        assert len(non_none) > 0
        # ADX should be positive for trending data
        assert adx.value is not None
        assert adx.value > 0

    def test_flat_prices_no_adx(self):
        adx = ADX(period=5)
        for _ in range(30):
            adx.update(100.0)
        # All identical prices -> TR=0, DI undefined -> ADX stays None
        assert adx.value is None

    def test_near_flat_prices_low_adx(self):
        adx = ADX(period=5)
        for i in range(30):
            # Tiny oscillation around 100
            adx.update(100.0 + 0.01 * ((-1) ** i))
        assert adx.value is not None
        assert adx.value < 30.0

    def test_trending_prices_high_adx(self):
        adx = ADX(period=5)
        for i in range(50):
            adx.update(100.0 + i * 2.0)
        assert adx.value is not None
        assert adx.value > 50.0

    def test_reset(self):
        adx = ADX(period=5)
        for i in range(20):
            adx.update(100.0 + i)
        adx.reset()
        assert not adx.ready
        assert adx.value is None


# ---------------------------------------------------------------------------
# RSI
# ---------------------------------------------------------------------------


class TestRSI:
    def test_warmup(self):
        rsi = RSI(period=3)
        assert rsi.update(100.0) is None  # need prev_price first
        assert rsi.update(101.0) is None
        assert rsi.update(102.0) is None

    def test_all_gains(self):
        rsi = RSI(period=3)
        for p in [100.0, 101.0, 102.0, 103.0]:
            rsi.update(p)
        assert rsi.value == pytest.approx(100.0)

    def test_all_losses(self):
        rsi = RSI(period=3)
        for p in [103.0, 102.0, 101.0, 100.0]:
            rsi.update(p)
        assert rsi.value == pytest.approx(0.0)

    def test_mixed(self):
        rsi = RSI(period=3)
        # gains: [1, 0, 1], losses: [0, 1, 0]
        for p in [100.0, 101.0, 100.0, 101.0]:
            rsi.update(p)
        # avg_gain = 2/3, avg_loss = 1/3, rs = 2, rsi = 100 - 100/3 = 66.67
        assert rsi.value == pytest.approx(100.0 - 100.0 / 3.0)

    def test_reset(self):
        rsi = RSI(period=3)
        for p in [100.0, 101.0, 102.0, 103.0]:
            rsi.update(p)
        rsi.reset()
        assert not rsi.ready
        assert rsi.value is None


# ---------------------------------------------------------------------------
# Donchian
# ---------------------------------------------------------------------------


class TestDonchian:
    def test_warmup(self):
        dc = Donchian(period=3)
        assert not dc.update(10.0)
        assert not dc.update(20.0)

    def test_values(self):
        dc = Donchian(period=3)
        dc.update(10.0)
        dc.update(20.0)
        assert dc.update(15.0)
        assert dc.upper == 20.0
        assert dc.lower == 10.0
        assert dc.mid == pytest.approx(15.0)
        assert dc.width == pytest.approx(10.0)

    def test_rolling(self):
        dc = Donchian(period=2)
        dc.update(10.0)
        dc.update(20.0)  # window: [10, 20]
        dc.update(15.0)  # window: [20, 15]
        assert dc.upper == 20.0
        assert dc.lower == 15.0

    def test_reset(self):
        dc = Donchian(period=2)
        dc.update(10.0)
        dc.update(20.0)
        dc.reset()
        assert not dc.ready
        assert dc.upper is None


# ---------------------------------------------------------------------------
# ATR
# ---------------------------------------------------------------------------


class TestATR:
    def test_warmup(self):
        atr = ATR(period=3)
        assert atr.update(100.0) is None
        assert atr.update(102.0) is None
        assert atr.update(101.0) is None

    def test_value(self):
        atr = ATR(period=3)
        # Need period+1 = 4 prices
        atr.update(100.0)
        atr.update(102.0)  # delta=2
        atr.update(101.0)  # delta=1
        result = atr.update(104.0)  # delta=3, ATR = mean(2,1,3) = 2.0
        assert result == pytest.approx(2.0)

    def test_scale(self):
        atr = ATR(period=2, scale=2.0)
        atr.update(100.0)
        atr.update(102.0)  # delta=2
        result = atr.update(104.0)  # delta=2, ATR = mean(2,2)*2 = 4.0
        assert result == pytest.approx(4.0)

    def test_reset(self):
        atr = ATR(period=2)
        atr.update(100.0)
        atr.update(102.0)
        atr.update(104.0)
        atr.reset()
        assert not atr.ready


class TestSmoothedATR:
    def test_warmup(self):
        sa = SmoothedATR(period=3)
        assert sa.update(2.0) is None
        assert sa.update(3.0) is None

    def test_value(self):
        sa = SmoothedATR(period=3)
        sa.update(2.0)
        sa.update(3.0)
        result = sa.update(4.0)
        assert result == pytest.approx(3.0)

    def test_reset(self):
        sa = SmoothedATR(period=2)
        sa.update(1.0)
        sa.update(2.0)
        sa.reset()
        assert not sa.ready


class TestATRPercentile:
    def test_warmup(self):
        ap = ATRPercentile(history_len=50, min_samples=5)
        for i in range(4):
            assert ap.update(float(i)) is None

    def test_percentile_computation(self):
        ap = ATRPercentile(history_len=100, min_samples=5)
        # Feed 10 values: 1..10
        for i in range(1, 11):
            ap.update(float(i))
        # Last value is 10, all 10 values <= 10, so percentile = 100
        assert ap.value == pytest.approx(100.0)

    def test_low_percentile(self):
        ap = ATRPercentile(history_len=100, min_samples=5)
        for i in range(1, 11):
            ap.update(float(i))
        # Feed a very low value
        result = ap.update(0.5)
        # Only 0.5 itself is <= 0.5 out of 11 values
        # Actually 0.5 is the lowest, so 1 out of 11
        assert result == pytest.approx(100.0 / 11.0, abs=0.1)

    def test_reset(self):
        ap = ATRPercentile(min_samples=2)
        ap.update(1.0)
        ap.update(2.0)
        ap.reset()
        assert not ap.ready


# ---------------------------------------------------------------------------
# Bollinger Bands
# ---------------------------------------------------------------------------


class TestBollingerBands:
    def test_warmup(self):
        bb = BollingerBands(period=3)
        assert not bb.update(10.0)
        assert not bb.update(20.0)

    def test_values(self):
        bb = BollingerBands(period=3, upper_mult=2.0)
        bb.update(10.0)
        bb.update(10.0)
        bb.update(10.0)
        # All same -> stdev=0
        assert bb.mid == pytest.approx(10.0)
        assert bb.upper == pytest.approx(10.0)
        assert bb.lower == pytest.approx(10.0)

    def test_nonzero_stdev(self):
        bb = BollingerBands(period=3, upper_mult=1.0)
        bb.update(10.0)
        bb.update(20.0)
        bb.update(30.0)
        # mid = 20, population stdev = sqrt(((10-20)^2+(20-20)^2+(30-20)^2)/3) = sqrt(200/3)
        expected_sd = math.sqrt(200.0 / 3.0)
        assert bb.mid == pytest.approx(20.0)
        assert bb.upper == pytest.approx(20.0 + expected_sd)
        assert bb.lower == pytest.approx(20.0 - expected_sd)

    def test_asymmetric_mult(self):
        bb = BollingerBands(period=3, upper_mult=2.0, lower_mult=1.0)
        bb.update(10.0)
        bb.update(20.0)
        bb.update(30.0)
        expected_sd = math.sqrt(200.0 / 3.0)
        assert bb.upper == pytest.approx(20.0 + 2.0 * expected_sd)
        assert bb.lower == pytest.approx(20.0 - 1.0 * expected_sd)

    def test_reset(self):
        bb = BollingerBands(period=2)
        bb.update(10.0)
        bb.update(20.0)
        bb.reset()
        assert not bb.ready


# ---------------------------------------------------------------------------
# Keltner Channel
# ---------------------------------------------------------------------------


class TestKeltnerChannel:
    def test_warmup(self):
        kc = KeltnerChannel(period=3)
        assert not kc.update(10.0)
        assert not kc.update(20.0)
        assert not kc.update(30.0)

    def test_produces_values(self):
        kc = KeltnerChannel(period=3, multiplier=1.5)
        prices = [100, 102, 101, 103, 102, 104, 103, 105]
        ready_count = 0
        for p in prices:
            if kc.update(float(p)):
                ready_count += 1
        assert ready_count > 0
        assert kc.mid is not None
        assert kc.upper is not None
        assert kc.lower is not None
        assert kc.upper > kc.mid > kc.lower

    def test_flat_prices_narrow_channel(self):
        kc = KeltnerChannel(period=3, multiplier=1.5)
        for _ in range(10):
            kc.update(100.0)
        # All same price -> ATR=0 -> channel collapses
        assert kc.upper == pytest.approx(kc.mid)
        assert kc.lower == pytest.approx(kc.mid)

    def test_reset(self):
        kc = KeltnerChannel(period=2)
        for i in range(5):
            kc.update(100.0 + i)
        kc.reset()
        assert not kc.ready
        assert kc.mid is None


# ---------------------------------------------------------------------------
# Cross-indicator: verify consistency with strategy implementations
# ---------------------------------------------------------------------------


class TestCrossConsistency:
    """Verify that indicator module produces same results as inline strategy code."""

    def test_adx_matches_strategy_pattern(self):
        """Compare ADX class against the inline pattern from volatility_squeeze."""
        prices = [100 + i * 0.5 + ((-1) ** i) * 0.3 for i in range(30)]

        # --- Inline implementation (from volatility_squeeze) ---
        adx_alpha = 2.0 / (14 + 1)
        prev_price = None
        atr_ema = None
        plus_dm_ema = None
        minus_dm_ema = None
        adx_ema_val = None
        inline_adx = None

        for p in prices:
            if prev_price is None:
                prev_price = p
                continue
            tr = abs(p - prev_price)
            delta = p - prev_price
            pdm = max(delta, 0.0)
            mdm = max(-delta, 0.0)
            a = adx_alpha
            if atr_ema is None:
                atr_ema = tr
                plus_dm_ema = pdm
                minus_dm_ema = mdm
            else:
                atr_ema = a * tr + (1 - a) * atr_ema
                plus_dm_ema = a * pdm + (1 - a) * plus_dm_ema
                minus_dm_ema = a * mdm + (1 - a) * minus_dm_ema
            if atr_ema and atr_ema > 1e-9:
                pdi = 100.0 * (plus_dm_ema / atr_ema)
                mdi = 100.0 * (minus_dm_ema / atr_ema)
                denom = pdi + mdi
                if denom > 1e-9:
                    dx = 100.0 * abs(pdi - mdi) / denom
                    if adx_ema_val is None:
                        adx_ema_val = dx
                    else:
                        adx_ema_val = a * dx + (1 - a) * adx_ema_val
                    inline_adx = adx_ema_val
            prev_price = p

        # --- Indicator class ---
        adx = ADX(period=14)
        for p in prices:
            adx.update(p)

        assert adx.value == pytest.approx(inline_adx, rel=1e-10)

    def test_ema_matches_strategy_pattern(self):
        """Compare EMA class against _ema_step from ta_orb."""
        prices = [100, 102, 101, 103, 105, 104, 106, 108, 107, 109]
        period = 3

        # _ema_step pattern
        prev = None
        closes: list[float] = []
        for p in prices:
            closes.append(float(p))
            prev = ema_step(prev, float(p), period, closes)

        # EMA class
        ema = EMA(period=period)
        for p in prices:
            ema.update(float(p))

        assert ema.value == pytest.approx(prev, rel=1e-10)

    def test_rsi_matches_strategy_pattern(self):
        """Compare RSI class against donchian_trend_strength._update_rsi."""
        prices = [100, 102, 101, 103, 100, 105, 103, 107, 104, 108]
        rsi_len = 5

        # Inline from donchian_trend_strength
        from collections import deque as dq
        gains: dq[float] = dq(maxlen=rsi_len)
        losses: dq[float] = dq(maxlen=rsi_len)
        inline_rsi = None
        for i in range(1, len(prices)):
            delta = prices[i] - prices[i - 1]
            gains.append(max(delta, 0.0))
            losses.append(max(-delta, 0.0))
            if len(gains) >= rsi_len:
                avg_gain = sum(gains) / rsi_len
                avg_loss = sum(losses) / rsi_len
                if avg_loss < 1e-9:
                    inline_rsi = 100.0
                else:
                    rs = avg_gain / avg_loss
                    inline_rsi = 100.0 - 100.0 / (1.0 + rs)

        # RSI class
        rsi = RSI(period=rsi_len)
        for p in prices:
            rsi.update(float(p))

        assert rsi.value == pytest.approx(inline_rsi, rel=1e-10)
