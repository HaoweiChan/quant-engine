"""Tests for database layer CRUD operations."""
from __future__ import annotations

from datetime import UTC, datetime

import pytest

from src.data.db import (
    AccountSnapshot,
    Database,
    PositionRecord,
    SignalRecord,
    TradeRecord,
)


@pytest.fixture
def db() -> Database:
    return Database(url="sqlite:///:memory:")


class TestTradeRecord:
    def test_add_and_retrieve(self, db: Database) -> None:
        record = TradeRecord(
            timestamp=datetime(2024, 1, 2, 9, 0, tzinfo=UTC),
            symbol="TX", side="buy", order_type="market",
            lots=3.0, price=None, reason="entry",
        )
        db.add_trade(record)
        trades = db.get_trades()
        assert len(trades) == 1
        assert trades[0].symbol == "TX"
        assert trades[0].lots == 3.0


class TestSignalRecord:
    def test_add_and_retrieve(self, db: Database) -> None:
        record = SignalRecord(
            timestamp=datetime(2024, 1, 2, 9, 0, tzinfo=UTC),
            direction=0.8, direction_conf=0.7,
            regime="trending", trend_strength=0.6,
            model_version="v1",
        )
        db.add_signal(record)
        signals = db.get_signals()
        assert len(signals) == 1
        assert signals[0].direction == 0.8


class TestPositionRecord:
    def test_add_and_retrieve(self, db: Database) -> None:
        record = PositionRecord(
            entry_timestamp=datetime(2024, 1, 2, 9, 0, tzinfo=UTC),
            symbol="TX", entry_price=20000.0, lots=3.0,
            contract_type="large", stop_level=19850.0, pyramid_level=0,
        )
        db.add_position(record)
        positions = db.get_positions()
        assert len(positions) == 1
        assert positions[0].entry_price == 20000.0

    def test_filter_open_only(self, db: Database) -> None:
        open_pos = PositionRecord(
            entry_timestamp=datetime(2024, 1, 2, 9, 0, tzinfo=UTC),
            symbol="TX", entry_price=20000.0, lots=3.0,
            contract_type="large", stop_level=19850.0, pyramid_level=0,
        )
        closed_pos = PositionRecord(
            entry_timestamp=datetime(2024, 1, 2, 9, 0, tzinfo=UTC),
            symbol="TX", entry_price=19500.0, lots=2.0,
            contract_type="large", stop_level=19350.0, pyramid_level=0,
            closed_at=datetime(2024, 1, 3, 10, 0, tzinfo=UTC),
            close_price=19600.0, close_reason="stop_loss",
        )
        db.add_position(open_pos)
        db.add_position(closed_pos)
        all_pos = db.get_positions()
        assert len(all_pos) == 2
        open_only = db.get_positions(open_only=True)
        assert len(open_only) == 1


class TestAccountSnapshot:
    def test_add_and_retrieve(self, db: Database) -> None:
        record = AccountSnapshot(
            timestamp=datetime(2024, 1, 2, 9, 0, tzinfo=UTC),
            equity=2_000_000.0, unrealized_pnl=50000.0,
            realized_pnl=10000.0, margin_used=400000.0,
            margin_ratio=0.2, drawdown_pct=0.05,
        )
        db.add_account_snapshot(record)
        snapshots = db.get_account_snapshots()
        assert len(snapshots) == 1
        assert snapshots[0].equity == 2_000_000.0
