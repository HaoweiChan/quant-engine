"""Tests for streaming 5m/1h aggregation inside LiveMinuteBarStore."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from src.broker_gateway.live_bar_store import LiveMinuteBarStore, MinuteBar

TAIPEI = ZoneInfo("Asia/Taipei")


def _init_tables(db_path: Path) -> None:
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


def _fetch(db_path: Path, table: str, symbol: str) -> list[tuple]:
    with sqlite3.connect(str(db_path)) as conn:
        return conn.execute(
            f"SELECT timestamp, open, high, low, close, volume "
            f"FROM {table} WHERE symbol = ? ORDER BY timestamp",
            (symbol,),
        ).fetchall()


def _feed_minute(
    store: LiveMinuteBarStore, symbol: str, ts: datetime,
    open_: float, high: float, low: float, close: float, volume: int,
) -> None:
    """Synthesize a 1m bar by issuing ticks inside the minute."""
    store.ingest_tick(symbol, open_, volume, ts.replace(second=1))
    store.ingest_tick(symbol, high, 0, ts.replace(second=15))
    store.ingest_tick(symbol, low, 0, ts.replace(second=30))
    store.ingest_tick(symbol, close, 0, ts.replace(second=45))


@pytest.fixture
def store(tmp_path: Path) -> LiveMinuteBarStore:
    db = tmp_path / "live-bars.db"
    _init_tables(db)
    return LiveMinuteBarStore(db_path=db)


def test_5m_bar_forms_on_each_1m_close(store: LiveMinuteBarStore, tmp_path: Path) -> None:
    """Five 1m bars at 15:00-15:04 yield one 5m bar at 15:00 with correct OHLCV."""
    base = datetime(2026, 4, 23, 15, 0, 0, tzinfo=TAIPEI)
    prices = [(100, 105, 99, 102), (102, 108, 101, 107),
              (107, 110, 105, 106), (106, 107, 100, 103), (103, 104, 98, 99)]
    for i, (o, h, l, c) in enumerate(prices):
        _feed_minute(store, "TX", base + timedelta(minutes=i), o, h, l, c, 10 + i)
    # Roll the 1m bar to force the 15:04 -> next-minute close fold
    store.ingest_tick("TX", 99.0, 1, base + timedelta(minutes=5, seconds=5))

    rows = _fetch(tmp_path / "live-bars.db", "ohlcv_5m", "TX")
    assert len(rows) >= 1, "expected at least one 5m row"
    first = rows[0]
    assert first[0] == "2026-04-23 15:00:00.000000"
    assert first[1] == 100.0                                 # open = first minute's open
    assert first[2] == 110.0                                 # high = max of the window
    assert first[3] == 98.0                                  # low = min of the window
    assert first[4] == 99.0                                  # close = last folded minute's close
    assert first[5] == 10 + 11 + 12 + 13 + 14                # volume sums 10..14


def test_5m_callback_fires_once_on_bucket_rollover(store: LiveMinuteBarStore) -> None:
    """Callback fires for the 15:00 5m bar exactly when the first 15:05 tick lands."""
    seen: list[tuple[str, MinuteBar]] = []
    store.register_tf_callback(5, lambda s, b: seen.append((s, b)))
    base = datetime(2026, 4, 23, 15, 0, 0, tzinfo=TAIPEI)
    for i in range(5):
        _feed_minute(store, "TX", base + timedelta(minutes=i), 100, 100, 100, 100, 1)
    assert seen == []                                        # window still open
    # First 15:05 tick opens the 15:05 1m but the 15:04 1m folds into
    # bucket 0 on close, not bucket 1 — so the callback must NOT fire yet.
    store.ingest_tick("TX", 101.0, 1, base + timedelta(minutes=5, seconds=1))
    assert seen == []
    # First 15:06 tick closes the 15:05 1m; its fold lands in bucket 1,
    # which triggers emission of the completed 15:00 5m bar.
    store.ingest_tick("TX", 102.0, 1, base + timedelta(minutes=6, seconds=1))
    assert len(seen) == 1
    sym, bar = seen[0]
    assert sym == "TX"
    assert bar.timestamp == datetime(2026, 4, 23, 15, 0, 0)
    assert bar.volume == 5
    # Another tick inside the 15:05 bucket must not fire a second callback
    store.ingest_tick("TX", 102.0, 1, base + timedelta(minutes=6, seconds=30))
    assert len(seen) == 1


def test_1h_bar_accumulates_12_five_min_windows(store: LiveMinuteBarStore, tmp_path: Path) -> None:
    """60 one-minute bars in the night session yield one 1h bar at 15:00."""
    base = datetime(2026, 4, 23, 15, 0, 0, tzinfo=TAIPEI)
    for i in range(60):
        _feed_minute(store, "TX", base + timedelta(minutes=i), 100 + i, 100 + i + 1, 100 + i - 1, 100 + i, 1)
    # Roll to 16:00 so the 15:00 1h bar is finalized and also upserted
    store.ingest_tick("TX", 100.0, 1, base + timedelta(minutes=60, seconds=5))

    rows_1h = _fetch(tmp_path / "live-bars.db", "ohlcv_1h", "TX")
    assert rows_1h and rows_1h[0][0] == "2026-04-23 15:00:00.000000"
    assert rows_1h[0][1] == 100.0                            # opened at 100
    assert rows_1h[0][5] == 60                               # one unit per 1m * 60


def test_day_to_night_session_gap_never_spans_bar(
    store: LiveMinuteBarStore, tmp_path: Path
) -> None:
    """Bars straddling 13:45 day-close and 15:00 night-open must not merge."""
    # Last 5m block of the day session: 13:40-13:44
    day_close_block = datetime(2026, 4, 23, 13, 40, 0, tzinfo=TAIPEI)
    for i in range(5):
        _feed_minute(store, "TX", day_close_block + timedelta(minutes=i), 200, 200, 200, 200, 1)
    # First 5m block of the night session: 15:00-15:04
    night_open_block = datetime(2026, 4, 23, 15, 0, 0, tzinfo=TAIPEI)
    for i in range(5):
        _feed_minute(store, "TX", night_open_block + timedelta(minutes=i), 300, 300, 300, 300, 1)
    # Roll into the next 5m bucket to finalize 15:00 window
    store.ingest_tick("TX", 301.0, 1, night_open_block + timedelta(minutes=5, seconds=5))

    rows = _fetch(tmp_path / "live-bars.db", "ohlcv_5m", "TX")
    ts_set = {r[0] for r in rows}
    assert "2026-04-23 13:40:00.000000" in ts_set
    assert "2026-04-23 15:00:00.000000" in ts_set
    # No bar may carry prices from both sessions
    day_row = next(r for r in rows if r[0] == "2026-04-23 13:40:00.000000")
    night_row = next(r for r in rows if r[0] == "2026-04-23 15:00:00.000000")
    assert day_row[1] == day_row[4] == 200.0
    assert night_row[1] == night_row[4] == 300.0


def test_night_to_day_session_gap_never_spans_bar(
    store: LiveMinuteBarStore, tmp_path: Path
) -> None:
    """Bars straddling 05:00 night-close and 08:45 day-open must not merge."""
    night_end_block = datetime(2026, 4, 24, 4, 55, 0, tzinfo=TAIPEI)
    for i in range(5):
        _feed_minute(store, "TX", night_end_block + timedelta(minutes=i), 400, 400, 400, 400, 1)
    day_open_block = datetime(2026, 4, 24, 8, 45, 0, tzinfo=TAIPEI)
    for i in range(5):
        _feed_minute(store, "TX", day_open_block + timedelta(minutes=i), 500, 500, 500, 500, 1)
    store.ingest_tick("TX", 501.0, 1, day_open_block + timedelta(minutes=5, seconds=5))

    rows = _fetch(tmp_path / "live-bars.db", "ohlcv_5m", "TX")
    # Night bar at 04:55 (session opened 15:00 previous day)
    assert any(r[0] == "2026-04-24 04:55:00.000000" and r[1] == 400.0 for r in rows)
    assert any(r[0] == "2026-04-24 08:45:00.000000" and r[1] == 500.0 for r in rows)


def test_inter_session_tick_is_dropped(
    store: LiveMinuteBarStore, tmp_path: Path
) -> None:
    """Tick at 14:00 (CLOSED) must produce no 1m/5m/1h rows."""
    store.ingest_tick("TX", 100.0, 1, datetime(2026, 4, 23, 14, 0, 0, tzinfo=TAIPEI))
    assert _fetch(tmp_path / "live-bars.db", "ohlcv_bars", "TX") == []
    assert _fetch(tmp_path / "live-bars.db", "ohlcv_5m", "TX") == []
    assert _fetch(tmp_path / "live-bars.db", "ohlcv_1h", "TX") == []


def test_symbols_do_not_cross_contaminate(
    store: LiveMinuteBarStore, tmp_path: Path
) -> None:
    """Two symbols stream independently — builders and DB rows stay separated."""
    base = datetime(2026, 4, 23, 15, 0, 0, tzinfo=TAIPEI)
    for i in range(5):
        _feed_minute(store, "TX", base + timedelta(minutes=i), 100, 100, 100, 100, 1)
        _feed_minute(store, "TMF", base + timedelta(minutes=i), 200, 200, 200, 200, 2)
    # Close the 15:04 1m bar on both symbols so its fold lands in the 5m builder
    store.ingest_tick("TX", 100.0, 1, base + timedelta(minutes=5, seconds=5))
    store.ingest_tick("TMF", 200.0, 2, base + timedelta(minutes=5, seconds=5))
    tx = _fetch(tmp_path / "live-bars.db", "ohlcv_5m", "TX")
    tmf = _fetch(tmp_path / "live-bars.db", "ohlcv_5m", "TMF")
    assert tx and tx[0][1] == 100.0 and tx[0][5] == 5
    assert tmf and tmf[0][1] == 200.0 and tmf[0][5] == 10


def test_forming_bar_visible_in_db_before_bucket_closes(
    store: LiveMinuteBarStore, tmp_path: Path
) -> None:
    """War-room charts need the partial 5m bar to be visible after each 1m close."""
    base = datetime(2026, 4, 23, 15, 0, 0, tzinfo=TAIPEI)
    _feed_minute(store, "TX", base, 100, 105, 95, 103, 7)
    # Force the 15:00 1m to close by sending a tick in the 15:01 minute
    store.ingest_tick("TX", 104.0, 1, base + timedelta(minutes=1, seconds=5))
    rows = _fetch(tmp_path / "live-bars.db", "ohlcv_5m", "TX")
    assert rows, "5m bar must be upserted while the window is still forming"
    assert rows[0][0] == "2026-04-23 15:00:00.000000"
    assert rows[0][1] == 100.0
    assert rows[0][5] == 7
