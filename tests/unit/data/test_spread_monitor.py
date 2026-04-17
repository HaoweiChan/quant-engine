"""Unit tests for LiveSpreadBuffer tick pairing logic."""
import pytest
from src.data.spread_monitor import LiveSpreadBuffer, LiveSpreadTick, get_live_buffer


class TestLiveSpreadBuffer:
    """Tests for LiveSpreadBuffer tick pairing and offset computation."""

    def test_basic_pairing(self):
        """R1 and R2 ticks in same bucket should produce a spread tick."""
        buffer = LiveSpreadBuffer(symbol="TX", bucket_ms=200)

        # R1 tick at t=1000
        result = buffer.on_tick("TXF1R1", 22150.0, 1000)
        assert result is None  # No pair yet

        # R2 tick in same bucket (t=1050, same 200ms bucket)
        result = buffer.on_tick("TXF1R2", 22180.0, 1050)
        assert result is not None
        assert isinstance(result, LiveSpreadTick)
        assert result.r1_price == 22150.0
        assert result.r2_price == 22180.0
        assert result.spread == 22150.0 - 22180.0  # R1 - R2
        assert result.symbol == "TX"

    def test_no_pairing_different_buckets(self):
        """R1 and R2 in different buckets should not pair."""
        buffer = LiveSpreadBuffer(symbol="TX", bucket_ms=200)

        # R1 at t=100 (bucket 0)
        result = buffer.on_tick("TXF1R1", 22150.0, 100)
        assert result is None

        # R2 at t=300 (bucket 200, different bucket)
        result = buffer.on_tick("TXF1R2", 22180.0, 300)
        assert result is None

    def test_warmup_offset_computation(self):
        """Offset should be computed after warmup_bars spreads."""
        buffer = LiveSpreadBuffer(symbol="TX", bucket_ms=200, warmup_bars=5)

        # Generate 5 paired spreads
        for i in range(5):
            ts = i * 1000
            buffer.on_tick("TXF1R1", 22100.0 + i * 10, ts)
            result = buffer.on_tick("TXF1R2", 22130.0 + i * 10, ts + 50)

        assert buffer.warmup_complete
        offset = buffer.get_session_offset()
        # Spread = R1 - R2 = 22100 - 22130 = -30 (all spreads are -30)
        # Offset = max(0, -min_spread + 100) = max(0, -(-30) + 100) = 130
        assert offset == 130.0

    def test_stale_detection(self):
        """is_stale should detect missing legs."""
        buffer = LiveSpreadBuffer(symbol="TX", stale_threshold_ms=5000)

        # No ticks yet - both legs missing
        is_stale, missing = buffer.is_stale(now_ms=10000)
        assert is_stale
        assert missing == "BOTH"

        # Add R1 tick
        buffer.on_tick("TXF1R1", 22150.0, 5000)

        # Check stale with R2 missing
        is_stale, missing = buffer.is_stale(now_ms=12000)
        assert is_stale
        assert missing == "R2"

    def test_reset_session(self):
        """reset_session should clear all state."""
        buffer = LiveSpreadBuffer(symbol="TX", bucket_ms=200, warmup_bars=2)

        # Generate some state
        buffer.on_tick("TXF1R1", 22150.0, 1000)
        buffer.on_tick("TXF1R2", 22180.0, 1050)
        buffer.on_tick("TXF1R1", 22160.0, 2000)
        buffer.on_tick("TXF1R2", 22190.0, 2050)

        assert buffer.warmup_complete

        # Reset
        buffer.reset_session()

        assert not buffer.warmup_complete
        assert buffer.get_session_offset() == 100.0  # Default

    def test_singleton_accessor(self):
        """get_live_buffer should return singleton instance."""
        buffer1 = get_live_buffer("TX")
        buffer2 = get_live_buffer("TX")
        assert buffer1 is buffer2

        # Different symbol should create new instance
        buffer3 = get_live_buffer("MTX")
        assert buffer3 is not buffer1

    def test_prune_stale_entries(self):
        """Old unpaired entries should be pruned."""
        buffer = LiveSpreadBuffer(symbol="TX", bucket_ms=200, max_lag_ms=1000)

        # Add R1 tick
        buffer.on_tick("TXF1R1", 22150.0, 1000)

        # Add another R1 much later (triggers prune)
        buffer.on_tick("TXF1R1", 22160.0, 5000)

        # Old R1 should be pruned, try to pair with R2 at old bucket
        result = buffer.on_tick("TXF1R2", 22180.0, 1050)
        assert result is None  # Old R1 was pruned


class TestOffsetFormula:
    """Verify offset computation matches facade formula."""

    def test_offset_matches_facade(self):
        """Offset = max(0, -min(spreads) + 100) should match facade.py:382."""
        buffer = LiveSpreadBuffer(symbol="TX", warmup_bars=3)

        # Create spreads: -30, -25, -35 (R1 - R2 values)
        spreads = [(-30, 22100, 22130), (-25, 22110, 22135), (-35, 22105, 22140)]

        for i, (_, r1, r2) in enumerate(spreads):
            ts = i * 1000
            buffer.on_tick("TXF1R1", r1, ts)
            buffer.on_tick("TXF1R2", r2, ts + 50)

        # min_spread = -35
        # offset = max(0, -(-35) + 100) = max(0, 135) = 135
        assert buffer.get_session_offset() == 135.0

    def test_positive_spreads_offset(self):
        """Positive spreads should result in offset = 0 or 100."""
        buffer = LiveSpreadBuffer(symbol="TX", warmup_bars=2)

        # Create positive spreads: R1 > R2
        buffer.on_tick("TXF1R1", 22200.0, 1000)
        buffer.on_tick("TXF1R2", 22150.0, 1050)  # spread = 50

        buffer.on_tick("TXF1R1", 22210.0, 2000)
        buffer.on_tick("TXF1R2", 22170.0, 2050)  # spread = 40

        # min_spread = 40
        # offset = max(0, -(40) + 100) = max(0, 60) = 60
        assert buffer.get_session_offset() == 60.0
