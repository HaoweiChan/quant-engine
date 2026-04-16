"""Unit tests for VolumeProfile indicator."""
from __future__ import annotations

import pytest

from src.indicators.volume_profile import (
    VolumeProfile,
    _bin_index,
)


class TestBinIndex:
    def test_bottom(self):
        assert _bin_index(100.0, 100.0, 10.0, 10) == 0

    def test_top(self):
        # price=200, low=100, width=10, rows=10 -> idx=10 -> clamped to 9
        assert _bin_index(200.0, 100.0, 10.0, 10) == 9

    def test_middle(self):
        assert _bin_index(125.0, 100.0, 10.0, 10) == 2

    def test_below_range(self):
        assert _bin_index(90.0, 100.0, 10.0, 10) == 0

    def test_above_range(self):
        assert _bin_index(300.0, 100.0, 10.0, 10) == 9


class TestVolumeProfileBasic:
    def test_no_bars_returns_none(self):
        vp = VolumeProfile(rows=10)
        vp.new_session(session_high=200.0, session_low=100.0)
        assert vp.compute() is None

    def test_no_session_returns_none(self):
        vp = VolumeProfile(rows=10)
        vp.add_bar(150.0, 140.0, 148.0, 141.0, 100.0)
        assert vp.compute() is None

    def test_zero_range_returns_none(self):
        vp = VolumeProfile(rows=10)
        vp.new_session(session_high=100.0, session_low=100.0)
        vp.add_bar(100.0, 100.0, 100.0, 100.0, 50.0)
        assert vp.compute() is None

    def test_single_bar(self):
        vp = VolumeProfile(rows=10)
        vp.new_session(session_high=110.0, session_low=100.0)
        # Bar spans 100-110 (full range), close > open → buy
        vp.add_bar(110.0, 100.0, 108.0, 101.0, 100.0)
        result = vp.compute()
        assert result is not None
        assert result.total_volume == pytest.approx(100.0)
        assert len(result.bins) == 10
        # Volume distributed equally across all 10 bins
        for b in result.bins:
            assert b.total_vol == pytest.approx(10.0)
            assert b.buy_vol == pytest.approx(10.0)
            assert b.sell_vol == pytest.approx(0.0)
            assert b.delta == pytest.approx(10.0)

    def test_single_bin_bar(self):
        """Bar that fits in a single bin concentrates all volume there."""
        vp = VolumeProfile(rows=10)
        vp.new_session(session_high=200.0, session_low=100.0)
        # bin_width = 10, bar at 100-100 -> bin 0
        vp.add_bar(100.0, 100.0, 100.0, 100.0, 50.0)
        result = vp.compute()
        assert result is not None
        assert result.bins[0].total_vol == pytest.approx(50.0)
        assert result.poc_index == 0

    def test_invalid_rows(self):
        with pytest.raises(ValueError):
            VolumeProfile(rows=3)

    def test_invalid_va_threshold(self):
        with pytest.raises(ValueError):
            VolumeProfile(va_threshold=0.0)


class TestPOC:
    def test_poc_is_highest_volume_bin(self):
        vp = VolumeProfile(rows=5)
        vp.new_session(session_high=150.0, session_low=100.0)
        # bin_width = 10
        # Bar 1: spans bin 0-1, 50 vol
        vp.add_bar(120.0, 100.0, 115.0, 105.0, 50.0)
        # Bar 2: sits right in bin 2 (120-130), 200 vol — should be POC
        vp.add_bar(125.0, 121.0, 124.0, 122.0, 200.0)
        # Bar 3: spans bin 3-4, 30 vol
        vp.add_bar(150.0, 130.0, 145.0, 135.0, 30.0)
        result = vp.compute()
        assert result is not None
        assert result.poc_index == 2
        assert result.poc == pytest.approx(120.0)  # level of bin 2

    def test_poc_with_competing_bins(self):
        vp = VolumeProfile(rows=5)
        vp.new_session(session_high=150.0, session_low=100.0)
        # All volume in bin 4 (140-150)
        vp.add_bar(145.0, 141.0, 144.0, 142.0, 300.0)
        result = vp.compute()
        assert result.poc_index == 4


class TestValueArea:
    def test_va_captures_70_pct(self):
        vp = VolumeProfile(rows=10, va_threshold=0.7)
        vp.new_session(session_high=200.0, session_low=100.0)
        # Distribute volume with a clear peak in the middle
        # bin_width=10, bins: 100,110,120,...,190
        for i in range(10):
            mid = 100.0 + i * 10.0 + 5.0
            # Peak volume at bin 5 (150-160)
            vol = 100.0 if i == 5 else 10.0
            vp.add_bar(mid + 1, mid - 1, mid + 0.5, mid - 0.5, vol)
        result = vp.compute()
        assert result is not None
        assert result.va_pct >= 70.0
        assert result.vah >= result.poc >= result.val

    def test_va_custom_threshold(self):
        vp = VolumeProfile(rows=10, va_threshold=0.5)
        vp.new_session(session_high=200.0, session_low=100.0)
        for i in range(10):
            mid = 100.0 + i * 10.0 + 5.0
            vol = 100.0 if i == 5 else 10.0
            vp.add_bar(mid + 1, mid - 1, mid + 0.5, mid - 0.5, vol)
        result = vp.compute()
        assert result.va_pct >= 50.0

    def test_uniform_volume_wide_va(self):
        """Uniform distribution needs many bins to reach 70%."""
        vp = VolumeProfile(rows=10, va_threshold=0.7)
        vp.new_session(session_high=200.0, session_low=100.0)
        for i in range(10):
            lo = 100.0 + i * 10.0
            hi = lo + 10.0
            vp.add_bar(hi, lo, hi - 1, lo + 1, 100.0)
        result = vp.compute()
        assert result is not None
        # With uniform vol, VA must span at least 7 of 10 bins
        assert result.va_pct >= 70.0


class TestDelta:
    def test_buy_bar_positive_delta(self):
        vp = VolumeProfile(rows=5)
        vp.new_session(session_high=150.0, session_low=100.0)
        vp.add_bar(110.0, 100.0, 108.0, 101.0, 100.0)  # close > open
        result = vp.compute()
        assert all(b.delta >= 0 for b in result.bins)

    def test_sell_bar_negative_delta(self):
        vp = VolumeProfile(rows=5)
        vp.new_session(session_high=150.0, session_low=100.0)
        vp.add_bar(110.0, 100.0, 101.0, 108.0, 100.0)  # close < open
        result = vp.compute()
        assert all(b.delta <= 0 for b in result.bins)

    def test_mixed_bars_net_delta(self):
        vp = VolumeProfile(rows=5)
        vp.new_session(session_high=150.0, session_low=100.0)
        # Big buy bar in bin 0
        vp.add_bar(105.0, 100.0, 104.0, 101.0, 200.0)
        # Small sell bar in bin 0
        vp.add_bar(105.0, 100.0, 101.0, 104.0, 50.0)
        result = vp.compute()
        assert result.bins[0].delta == pytest.approx(150.0)  # 200 - 50


class TestDirectionOverride:
    def test_add_bar_with_direction(self):
        vp = VolumeProfile(rows=5)
        vp.new_session(session_high=150.0, session_low=100.0)
        vp.add_bar_with_direction(110.0, 100.0, 100.0, direction=-1.0)
        result = vp.compute()
        assert result.bins[0].sell_vol > 0
        assert result.bins[0].buy_vol == 0


class TestStreamingRange:
    def test_update_range_expands(self):
        vp = VolumeProfile(rows=10)
        vp.new_session()
        vp.update_range(110.0, 100.0)
        vp.add_bar(110.0, 100.0, 108.0, 101.0, 50.0)
        # Range expands
        vp.update_range(120.0, 95.0)
        vp.add_bar(120.0, 115.0, 119.0, 116.0, 30.0)
        result = vp.compute()
        assert result is not None
        assert result.total_volume == pytest.approx(80.0)
        assert result.bin_width == pytest.approx((120.0 - 95.0) / 10)


class TestCaching:
    def test_compute_is_cached(self):
        vp = VolumeProfile(rows=5)
        vp.new_session(session_high=150.0, session_low=100.0)
        vp.add_bar(110.0, 100.0, 108.0, 101.0, 100.0)
        r1 = vp.compute()
        r2 = vp.compute()
        assert r1 is r2  # same object

    def test_add_bar_invalidates_cache(self):
        vp = VolumeProfile(rows=5)
        vp.new_session(session_high=150.0, session_low=100.0)
        vp.add_bar(110.0, 100.0, 108.0, 101.0, 100.0)
        r1 = vp.compute()
        vp.add_bar(120.0, 110.0, 118.0, 111.0, 50.0)
        r2 = vp.compute()
        assert r1 is not r2


class TestReset:
    def test_reset_clears_all(self):
        vp = VolumeProfile(rows=10)
        vp.new_session(session_high=200.0, session_low=100.0)
        vp.add_bar(150.0, 140.0, 148.0, 141.0, 100.0)
        vp.compute()
        assert vp.ready
        vp.reset()
        assert not vp.ready
        assert vp.result is None
        assert vp.compute() is None

    def test_new_session_clears_bars(self):
        vp = VolumeProfile(rows=10)
        vp.new_session(session_high=200.0, session_low=100.0)
        vp.add_bar(150.0, 140.0, 148.0, 141.0, 100.0)
        vp.compute()
        vp.new_session(session_high=300.0, session_low=200.0)
        assert vp.compute() is None  # no bars in new session


class TestVolumeConservation:
    """Total volume in bins must equal total volume of all bars fed."""

    def test_volume_conserved(self):
        vp = VolumeProfile(rows=20)
        vp.new_session(session_high=20500.0, session_low=20000.0)
        total_fed = 0.0
        bars = [
            (20300, 20100, 20250, 20150, 1500),
            (20400, 20200, 20380, 20220, 800),
            (20200, 20050, 20080, 20180, 1200),
            (20450, 20350, 20430, 20360, 600),
            (20150, 20000, 20100, 20050, 2000),
        ]
        for h, l, c, o, v in bars:
            vp.add_bar(float(h), float(l), float(c), float(o), float(v))
            total_fed += v
        result = vp.compute()
        assert result is not None
        bin_total = sum(b.total_vol for b in result.bins)
        assert bin_total == pytest.approx(total_fed, rel=1e-9)
        # Buy + sell per bin = total per bin
        for b in result.bins:
            assert b.buy_vol + b.sell_vol == pytest.approx(b.total_vol, abs=1e-9)
