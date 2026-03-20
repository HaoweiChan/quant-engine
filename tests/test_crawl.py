"""Tests for the historical data crawl pipeline."""
from __future__ import annotations

from datetime import date, datetime
from unittest.mock import MagicMock

import polars as pl
import pytest

from src.data.connector import ValidationReport
from src.data.crawl import _date_chunks, crawl_historical
from src.data.db import Database


@pytest.fixture()
def db() -> Database:
    return Database(url="sqlite:///:memory:")


def _make_connector(n_bars: int = 5) -> MagicMock:
    mock = MagicMock()
    mock.ensure_session.return_value = None
    ts = [datetime(2024, 1, 2, 9, 0, i) for i in range(n_bars)]
    df = pl.DataFrame({
        "timestamp": ts,
        "open": [100.0 + i for i in range(n_bars)],
        "high": [101.0 + i for i in range(n_bars)],
        "low": [99.0 + i for i in range(n_bars)],
        "close": [100.5 + i for i in range(n_bars)],
        "volume": [1000 + i for i in range(n_bars)],
    })
    mock.fetch_minute.return_value = df
    mock.validate.return_value = ValidationReport()
    return mock


class TestDateChunks:
    def test_single_chunk(self) -> None:
        chunks = _date_chunks(date(2024, 1, 1), date(2024, 2, 1), 60)
        assert len(chunks) == 1
        assert chunks[0] == (date(2024, 1, 1), date(2024, 2, 1))

    def test_multiple_chunks(self) -> None:
        chunks = _date_chunks(date(2024, 1, 1), date(2024, 6, 30), 60)
        assert len(chunks) >= 3
        assert chunks[0][0] == date(2024, 1, 1)
        assert chunks[-1][1] == date(2024, 6, 30)
        for i in range(len(chunks) - 1):
            gap = (chunks[i + 1][0] - chunks[i][1]).days
            assert gap == 1

    def test_exact_boundary(self) -> None:
        chunks = _date_chunks(date(2024, 1, 1), date(2024, 2, 29), 60)
        assert len(chunks) == 1


class TestCrawlHistorical:
    def test_stores_bars_in_db(self, db: Database) -> None:
        connector = _make_connector(5)
        total = crawl_historical("TX", date(2024, 1, 1), date(2024, 1, 31), db, connector, delay=0)
        assert total == 5
        bars = db.get_ohlcv("TX", datetime(2024, 1, 1), datetime(2024, 12, 31))
        assert len(bars) == 5

    def test_multiple_chunks_accumulate(self, db: Database) -> None:
        connector = _make_connector(3)
        total = crawl_historical("TX", date(2024, 1, 1), date(2024, 6, 30), db, connector, delay=0)
        assert connector.fetch_minute.call_count >= 3
        assert total == 3 * connector.fetch_minute.call_count

    def test_empty_fetch_no_error(self, db: Database) -> None:
        connector = _make_connector(0)
        connector.fetch_minute.return_value = pl.DataFrame({
            "timestamp": [], "open": [], "high": [], "low": [], "close": [], "volume": [],
        })
        total = crawl_historical("TX", date(2024, 1, 1), date(2024, 1, 31), db, connector, delay=0)
        assert total == 0

    def test_validation_warnings_dont_block(self, db: Database) -> None:
        connector = _make_connector(5)
        report = ValidationReport(gaps=["Gap at index 3"])
        connector.validate.return_value = report
        total = crawl_historical("TX", date(2024, 1, 1), date(2024, 1, 31), db, connector, delay=0)
        assert total == 5
