"""Tests for R1-R2 spread monitor."""
from __future__ import annotations

from datetime import UTC, datetime

import pytest

from src.data.spread_monitor import (
    SpreadMonitor,
    SpreadSnapshot,
    ensure_schema,
    load_spread_history,
    persist_batch,
    persist_snapshot,
)


@pytest.fixture
def monitor() -> SpreadMonitor:
    return SpreadMonitor(window_size=10)


class TestSpreadRecording:
    def test_record_creates_snapshot(self, monitor: SpreadMonitor) -> None:
        snap = monitor.record("TX", r1_price=20000, r2_price=20050)
        assert snap.spread == 50
        assert snap.spread_pct == pytest.approx(0.25, rel=1e-3)

    def test_record_negative_spread(self, monitor: SpreadMonitor) -> None:
        snap = monitor.record("TX", r1_price=20000, r2_price=19950)
        assert snap.spread == -50

    def test_latest(self, monitor: SpreadMonitor) -> None:
        monitor.record("TX", r1_price=20000, r2_price=20050)
        monitor.record("TX", r1_price=20010, r2_price=20040)
        assert monitor.latest("TX") is not None
        assert monitor.latest("TX").spread == 30

    def test_no_data(self, monitor: SpreadMonitor) -> None:
        assert monitor.latest("MTX") is None
        assert monitor.get_stats("MTX") is None


class TestSpreadStats:
    def test_stats_computed(self, monitor: SpreadMonitor) -> None:
        ts = datetime(2024, 3, 15, 10, 0, tzinfo=UTC)
        for i in range(10):
            monitor.record("TX", r1_price=20000, r2_price=20000 + (i + 1) * 10, timestamp=ts)
        stats = monitor.get_stats("TX")
        assert stats is not None
        assert stats.n_obs == 10
        assert stats.min == 10
        assert stats.max == 100
        assert stats.current == 100

    def test_favorable_when_low_spread(self, monitor: SpreadMonitor) -> None:
        ts = datetime(2024, 3, 15, 10, 0, tzinfo=UTC)
        # Record 10 high spreads, then one low
        for i in range(10):
            monitor.record("TX", r1_price=20000, r2_price=20100, timestamp=ts)
        monitor.record("TX", r1_price=20000, r2_price=20010, timestamp=ts)
        assert monitor.is_favorable("TX") is True

    def test_unfavorable_when_high_spread(self, monitor: SpreadMonitor) -> None:
        ts = datetime(2024, 3, 15, 10, 0, tzinfo=UTC)
        for i in range(10):
            monitor.record("TX", r1_price=20000, r2_price=20010, timestamp=ts)
        monitor.record("TX", r1_price=20000, r2_price=20200, timestamp=ts)
        assert monitor.is_favorable("TX") is False

    def test_insufficient_data(self, monitor: SpreadMonitor) -> None:
        monitor.record("TX", r1_price=20000, r2_price=20050)
        assert monitor.get_stats("TX") is None


class TestMultiSymbol:
    def test_independent_tracking(self, monitor: SpreadMonitor) -> None:
        monitor.record("TX", r1_price=20000, r2_price=20050)
        monitor.record("MTX", r1_price=20000, r2_price=20030)
        assert monitor.latest("TX").spread == 50
        assert monitor.latest("MTX").spread == 30


class TestPersistence:
    def test_persist_and_load(self, tmp_path) -> None:
        db = tmp_path / "test.db"
        ensure_schema(db)
        snap = SpreadSnapshot(
            timestamp=datetime(2024, 3, 15, 10, 0, tzinfo=UTC),
            symbol="TX",
            r1_price=20000,
            r2_price=20050,
            spread=50,
            spread_pct=0.25,
        )
        persist_snapshot(snap, db)
        loaded = load_spread_history("TX", db_path=db)
        assert len(loaded) == 1
        assert loaded[0].spread == 50

    def test_persist_batch(self, tmp_path) -> None:
        db = tmp_path / "test.db"
        snaps = [
            SpreadSnapshot(
                timestamp=datetime(2024, 3, 15, 10, i, tzinfo=UTC),
                symbol="TX",
                r1_price=20000,
                r2_price=20000 + i * 10,
                spread=i * 10,
                spread_pct=i * 10 / 20000 * 100,
            )
            for i in range(5)
        ]
        count = persist_batch(snaps, db)
        assert count == 5
        loaded = load_spread_history("TX", db_path=db)
        assert len(loaded) == 5

    def test_load_empty(self, tmp_path) -> None:
        loaded = load_spread_history("TX", db_path=tmp_path / "nonexistent.db")
        assert loaded == []
