"""Tests for live 1m OHLCV persistence from streaming ticks."""
from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from src.broker_gateway.live_bar_store import LiveMinuteBarStore

TAIPEI = ZoneInfo("Asia/Taipei")


def _init_ohlcv_table(db_path: Path) -> None:
    schema_cols = (
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "symbol VARCHAR(32) NOT NULL, "
        "timestamp DATETIME NOT NULL, "
        "open FLOAT NOT NULL, high FLOAT NOT NULL, "
        "low FLOAT NOT NULL, close FLOAT NOT NULL, "
        "volume INTEGER NOT NULL"
    )
    with sqlite3.connect(str(db_path)) as conn:
        for table, uq in (
            ("ohlcv_bars", "uq_ohlcv_symbol_ts"),
            ("ohlcv_5m", "uq_ohlcv5m_symbol_ts"),
            ("ohlcv_1h", "uq_ohlcv1h_symbol_ts"),
        ):
            conn.execute(
                f"CREATE TABLE {table} ({schema_cols}, "
                f"CONSTRAINT {uq} UNIQUE (symbol, timestamp))"
            )
        conn.commit()


def _fetch_rows(db_path: Path, symbol: str) -> list[tuple]:
    with sqlite3.connect(str(db_path)) as conn:
        rows = conn.execute(
            "SELECT symbol, timestamp, open, high, low, close, volume "
            "FROM ohlcv_bars WHERE symbol = ? ORDER BY timestamp",
            (symbol,),
        ).fetchall()
    return rows


def test_ingest_tick_aggregates_and_rolls_bar(tmp_path: Path) -> None:
    db_path = tmp_path / "live-bars.db"
    _init_ohlcv_table(db_path)
    store = LiveMinuteBarStore(db_path=db_path)
    store.ingest_tick("TX", 100.0, 2, datetime(2026, 4, 1, 18, 55, 10, tzinfo=TAIPEI))
    store.ingest_tick("TX", 102.0, 3, datetime(2026, 4, 1, 18, 55, 40, tzinfo=TAIPEI))
    rows = _fetch_rows(db_path, "TX")
    assert len(rows) == 1
    assert rows[0] == ("TX", "2026-04-01 18:55:00.000000", 100.0, 102.0, 100.0, 102.0, 5)
    store.ingest_tick("TX", 101.0, 4, datetime(2026, 4, 1, 18, 56, 5, tzinfo=TAIPEI))
    rows = _fetch_rows(db_path, "TX")
    assert len(rows) == 2
    assert rows[1] == ("TX", "2026-04-01 18:56:00.000000", 101.0, 101.0, 101.0, 101.0, 4)


def test_ingest_tick_merges_with_existing_row_without_regression(tmp_path: Path) -> None:
    db_path = tmp_path / "live-bars.db"
    _init_ohlcv_table(db_path)
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute(
            """
            INSERT INTO ohlcv_bars (symbol, timestamp, open, high, low, close, volume)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            ("TX", "2026-04-01 18:57:00.000000", 99.0, 105.0, 95.0, 100.0, 12),
        )
        conn.commit()
    store = LiveMinuteBarStore(db_path=db_path)
    store.ingest_tick("TX", 104.0, 2, datetime(2026, 4, 1, 18, 57, 8, tzinfo=TAIPEI))
    store.ingest_tick("TX", 106.0, 15, datetime(2026, 4, 1, 18, 57, 50, tzinfo=TAIPEI))
    rows = _fetch_rows(db_path, "TX")
    assert len(rows) == 1
    assert rows[0] == ("TX", "2026-04-01 18:57:00.000000", 99.0, 106.0, 95.0, 106.0, 17)


def test_ingest_tick_ignores_off_session_minutes(tmp_path: Path) -> None:
    db_path = tmp_path / "live-bars.db"
    _init_ohlcv_table(db_path)
    store = LiveMinuteBarStore(db_path=db_path)
    store.ingest_tick("TX", 100.0, 1, datetime(2026, 4, 1, 14, 30, 0, tzinfo=TAIPEI))
    rows = _fetch_rows(db_path, "TX")
    assert rows == []
    store.ingest_tick("TX", 100.0, 1, datetime(2026, 4, 2, 5, 0, 0, tzinfo=TAIPEI))
    rows = _fetch_rows(db_path, "TX")
    assert len(rows) == 1
    assert rows[0][1] == "2026-04-02 05:00:00.000000"
