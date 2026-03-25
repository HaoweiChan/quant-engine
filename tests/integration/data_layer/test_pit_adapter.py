"""Integration test: backtest with PIT-aware adapter uses historical margins."""
from __future__ import annotations

from datetime import datetime

import pytest

from src.adapters.taifex import TaifexAdapter
from src.data.db import Database, MarginSnapshot


@pytest.fixture
def db() -> Database:
    return Database("sqlite:///:memory:")


class TestPITAwareAdapter:
    def test_backtest_uses_past_margins(self, db: Database) -> None:
        db.add_margin_snapshot(MarginSnapshot(
            symbol="TX", scraped_at=datetime(2024, 1, 1),
            margin_initial=150_000.0, margin_maintenance=120_000.0,
            source="test", knowledge_time=datetime(2024, 1, 1),
        ))
        db.add_margin_snapshot(MarginSnapshot(
            symbol="TX", scraped_at=datetime(2024, 6, 1),
            margin_initial=200_000.0, margin_maintenance=160_000.0,
            source="test", knowledge_time=datetime(2024, 6, 1),
        ))
        adapter = TaifexAdapter(db=db, backtest_mode=True)
        snapshot = adapter.to_snapshot({
            "price": 20000.0, "symbol": "TX",
            "timestamp": datetime(2024, 3, 1),
        })
        assert snapshot.margin_per_unit == 150_000.0

    def test_live_uses_current_margins(self, db: Database) -> None:
        db.add_margin_snapshot(MarginSnapshot(
            symbol="TX", scraped_at=datetime(2024, 1, 1),
            margin_initial=150_000.0, margin_maintenance=120_000.0,
            source="test", knowledge_time=datetime(2024, 1, 1),
        ))
        db.add_margin_snapshot(MarginSnapshot(
            symbol="TX", scraped_at=datetime(2024, 6, 1),
            margin_initial=200_000.0, margin_maintenance=160_000.0,
            source="test", knowledge_time=datetime(2024, 6, 1),
        ))
        adapter = TaifexAdapter(db=db, backtest_mode=False)
        snapshot = adapter.to_snapshot({
            "price": 20000.0, "symbol": "TX",
            "timestamp": datetime(2024, 3, 1),
        })
        assert snapshot.margin_per_unit == 200_000.0

    def test_no_db_falls_back_to_toml(self) -> None:
        adapter = TaifexAdapter(backtest_mode=True)
        snapshot = adapter.to_snapshot({
            "price": 20000.0, "symbol": "TX",
            "timestamp": datetime(2024, 3, 1),
        })
        assert snapshot.margin_per_unit > 0
