"""Tests for ``src/risk/feed_watchdog.py`` and bar-store staleness helpers."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from src.broker_gateway.live_bar_store import LiveMinuteBarStore
from src.core.clock import SimulatedClock
from src.risk.feed_watchdog import FeedWatchdog


def _init_ohlcv_schema(db_path: Path) -> None:
    """Create the minimal OHLCV tables LiveMinuteBarStore upserts into."""
    cols = (
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
                f"CREATE TABLE {table} ({cols}, "
                f"CONSTRAINT {uq} UNIQUE (symbol, timestamp))"
            )
        conn.commit()


@pytest.fixture
def bar_store(tmp_path) -> LiveMinuteBarStore:
    """Fresh bar store backed by a tmp SQLite file (no DB pollution)."""
    db_path = tmp_path / "market.db"
    _init_ohlcv_schema(db_path)
    return LiveMinuteBarStore(db_path=db_path)


# -- LiveMinuteBarStore staleness helpers --------------------------------


class TestBarStoreStaleness:
    def test_no_ticks_means_not_stale(self, bar_store):
        # Fresh store with no ticks should report not-stale to avoid
        # halting on startup before the first tick lands.
        assert bar_store.is_stale("TXFR1", now_epoch=1_000_000.0) is False
        assert bar_store.last_tick_epoch("TXFR1") is None

    def test_ingest_tick_records_epoch(self, bar_store):
        # Use a TAIFEX trading-minute (15:00 night session start)
        bar_store.ingest_tick(
            "TXFR1", price=20000.0, volume=1,
            tick_ts=datetime(2026, 4, 25, 15, 0, 5),
        )
        assert bar_store.last_tick_epoch("TXFR1") is not None
        assert "TXFR1" in bar_store.tracked_symbols()

    def test_is_stale_after_threshold(self, bar_store):
        ts = datetime(2026, 4, 25, 15, 0, 5)
        bar_store.ingest_tick("TXFR1", price=20000.0, volume=1, tick_ts=ts)
        last = bar_store.last_tick_epoch("TXFR1")
        # 4 seconds past last tick → stale at 3s threshold
        assert bar_store.is_stale("TXFR1", now_epoch=last + 4, max_silence_secs=3.0)
        # 1 second past last tick → still fresh
        assert not bar_store.is_stale("TXFR1", now_epoch=last + 1, max_silence_secs=3.0)


# -- FeedWatchdog --------------------------------------------------------


class TestFeedWatchdogPolling:
    def test_no_ticks_no_halt(self, bar_store):
        sm = MagicMock()
        wd = FeedWatchdog(
            bar_store=bar_store,
            session_manager=sm,
            clock=SimulatedClock(datetime(2026, 4, 25, 15, 0, 5, tzinfo=timezone.utc)),
        )
        wd.poll_once()
        sm.halt.assert_not_called()
        assert wd.halted_symbols == set()

    def test_halts_on_silence(self, bar_store):
        sm = MagicMock()
        notifier = MagicMock()
        # Tick at T0
        ts = datetime(2026, 4, 25, 15, 0, 5)
        bar_store.ingest_tick("TXFR1", price=20000.0, volume=1, tick_ts=ts)
        last = bar_store.last_tick_epoch("TXFR1")
        # Move clock 5 seconds past the tick → over the 3s threshold
        clock = SimulatedClock(datetime.fromtimestamp(last + 5, tz=timezone.utc))
        wd = FeedWatchdog(
            bar_store=bar_store, session_manager=sm, notifier=notifier,
            clock=clock, max_silence_secs=3.0,
        )
        wd.poll_once()
        sm.halt.assert_called_once()
        notifier.send.assert_called_once()
        assert "TXFR1" in wd.halted_symbols

    def test_idempotent_halt(self, bar_store):
        sm = MagicMock()
        ts = datetime(2026, 4, 25, 15, 0, 5)
        bar_store.ingest_tick("TXFR1", price=20000.0, volume=1, tick_ts=ts)
        last = bar_store.last_tick_epoch("TXFR1")
        clock = SimulatedClock(datetime.fromtimestamp(last + 5, tz=timezone.utc))
        wd = FeedWatchdog(bar_store=bar_store, session_manager=sm, clock=clock)
        wd.poll_once()
        wd.poll_once()
        # Halt should fire exactly once even though the symbol stays stale
        sm.halt.assert_called_once()

    def test_recovery_logs_but_does_not_resume(self, bar_store):
        sm = MagicMock()
        ts1 = datetime(2026, 4, 25, 15, 0, 5)  # naive Taipei
        bar_store.ingest_tick("TXFR1", price=20000.0, volume=1, tick_ts=ts1)
        last = bar_store.last_tick_epoch("TXFR1")
        clock = SimulatedClock(datetime.fromtimestamp(last + 5, tz=timezone.utc))
        wd = FeedWatchdog(bar_store=bar_store, session_manager=sm, clock=clock)
        wd.poll_once()
        assert "TXFR1" in wd.halted_symbols
        # New tick arrives 7s after the first → freshness restored
        ts2 = datetime(2026, 4, 25, 15, 0, 12)  # naive Taipei, +7s
        bar_store.ingest_tick("TXFR1", price=20000.0, volume=1, tick_ts=ts2)
        new_last = bar_store.last_tick_epoch("TXFR1")
        # Move the wall clock to 1s after the new tick — well within threshold
        clock.set(datetime.fromtimestamp(new_last + 1, tz=timezone.utc))
        wd.poll_once()
        # Recovery clears the symbol from halted set, but does NOT
        # re-call SessionManager.resume — operator confirmation is
        # required per OpenSpec risk-monitor recovery scenario.
        assert "TXFR1" not in wd.halted_symbols
        sm.resume.assert_not_called()

    def test_pushes_feed_time_into_risk_monitor(self, bar_store):
        sm = MagicMock()
        rm = MagicMock()
        ts = datetime(2026, 4, 25, 15, 0, 5)
        bar_store.ingest_tick("TXFR1", price=20000.0, volume=1, tick_ts=ts)
        last = bar_store.last_tick_epoch("TXFR1")
        clock = SimulatedClock(datetime.fromtimestamp(last + 0.5, tz=timezone.utc))
        wd = FeedWatchdog(
            bar_store=bar_store, session_manager=sm, risk_monitor=rm, clock=clock,
        )
        wd.poll_once()
        rm.update_feed_time.assert_called_once()
        # The arg is a datetime — verify it came from the bar store.
        call_arg = rm.update_feed_time.call_args.args[0]
        assert isinstance(call_arg, datetime)
        assert call_arg.timestamp() == pytest.approx(last)

    def test_invalid_intervals_rejected(self, bar_store):
        sm = MagicMock()
        with pytest.raises(ValueError):
            FeedWatchdog(bar_store=bar_store, session_manager=sm, max_silence_secs=0)
        with pytest.raises(ValueError):
            FeedWatchdog(bar_store=bar_store, session_manager=sm, poll_interval_secs=-1)
