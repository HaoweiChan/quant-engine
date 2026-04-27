"""Tests for ``src/execution/bar_source.py``."""
from __future__ import annotations

import asyncio
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.broker_gateway.live_bar_store import LiveMinuteBarStore, MinuteBar
from src.core.clock import SimulatedClock
from src.data.multi_timeframe_router import MultiTimeframeRouter
from src.execution.bar_source import BarSource, LiveBarSource, PlaybackBarSource


def _init_ohlcv_schema(db_path: Path) -> None:
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


def _bar(ts: datetime, base: float = 100.0) -> MinuteBar:
    return MinuteBar(
        timestamp=ts, open=base, high=base + 1, low=base - 1,
        close=base + 0.5, volume=10,
    )


# -- Protocol conformance ------------------------------------------------


class TestProtocolConformance:
    def test_live_satisfies_protocol(self, tmp_path) -> None:
        path = tmp_path / "market.db"
        _init_ohlcv_schema(path)
        src = LiveBarSource(LiveMinuteBarStore(db_path=path))
        assert isinstance(src, BarSource)

    def test_playback_satisfies_protocol(self) -> None:
        src = PlaybackBarSource(bars=[], clock=SimulatedClock())
        assert isinstance(src, BarSource)


# -- LiveBarSource -------------------------------------------------------


class TestLiveBarSource:
    def test_subscriber_receives_resampled_bars(self, tmp_path) -> None:
        path = tmp_path / "market.db"
        _init_ohlcv_schema(path)
        store = LiveMinuteBarStore(db_path=path)
        src = LiveBarSource(store)
        captured: list[MinuteBar] = []
        src.subscribe("TXFR1", 5, lambda _sym, bar: captured.append(bar))
        # Need 7 ticks to close 6 1m bars; the 6th 1m bar (15:05) lives
        # in bucket 1, which is what triggers emission of bucket 0.
        base = datetime(2026, 4, 25, 15, 0)
        for i in range(7):
            store.ingest_tick(
                "TXFR1", price=100.0 + i, volume=1,
                tick_ts=base + timedelta(minutes=i),
            )
        assert len(captured) == 1
        assert captured[0].open == 100.0
        # 5 1m bars folded (15:00-15:04), each volume=1
        assert captured[0].volume == 5

    def test_unsubscribe_stops_callbacks(self, tmp_path) -> None:
        path = tmp_path / "market.db"
        _init_ohlcv_schema(path)
        store = LiveMinuteBarStore(db_path=path)
        router = MultiTimeframeRouter()
        src = LiveBarSource(store, router=router)
        captured: list[MinuteBar] = []

        def cb(_sym, bar):
            captured.append(bar)

        src.subscribe("TXFR1", 1, cb)
        store.ingest_tick(
            "TXFR1", price=100.0, volume=1,
            tick_ts=datetime(2026, 4, 25, 15, 0),
        )
        store.ingest_tick(
            "TXFR1", price=101.0, volume=1,
            tick_ts=datetime(2026, 4, 25, 15, 1),
        )
        # First 1m bar emits when minute ts crosses; second tick closes
        # the first bar (1 emit).
        assert len(captured) == 1
        src.unsubscribe(cb)
        store.ingest_tick(
            "TXFR1", price=102.0, volume=1,
            tick_ts=datetime(2026, 4, 25, 15, 2),
        )
        assert len(captured) == 1


# -- PlaybackBarSource ---------------------------------------------------


class TestPlaybackBarSource:
    def test_replay_emits_resampled(self) -> None:
        clock = SimulatedClock(datetime(2026, 4, 25, 15, 0, tzinfo=timezone.utc))
        bars = [
            ("TXFR1", _bar(datetime(2026, 4, 25, 15, 0) + timedelta(minutes=i)))
            for i in range(6)
        ]
        src = PlaybackBarSource(bars=bars, clock=clock)
        captured: list[MinuteBar] = []
        src.subscribe("TXFR1", 5, lambda _sym, bar: captured.append(bar))
        replayed = asyncio.get_event_loop().run_until_complete(src.replay_all())
        assert replayed == 6
        # 5m window closes after 6 1m bars (window 1 closes when bar 6 arrives)
        assert len(captured) == 1

    def test_clock_advances_per_bar(self) -> None:
        clock = SimulatedClock(datetime(2026, 4, 25, 15, 0, tzinfo=timezone.utc))
        bars = [
            ("TXFR1", _bar(datetime(2026, 4, 25, 15, 0) + timedelta(minutes=i)))
            for i in range(3)
        ]
        src = PlaybackBarSource(bars=bars, clock=clock, bar_interval_secs=60.0)
        asyncio.get_event_loop().run_until_complete(src.replay_all())
        # Three bars × 60s each
        assert clock.monotonic() == 180.0

    def test_invalid_speed_rejected(self) -> None:
        with pytest.raises(ValueError):
            PlaybackBarSource(bars=[], clock=SimulatedClock(), speed_x=0.0)
        with pytest.raises(ValueError):
            PlaybackBarSource(
                bars=[], clock=SimulatedClock(), bar_interval_secs=-1.0,
            )

    @pytest.mark.asyncio
    async def test_async_start_emits_bars(self) -> None:
        clock = SimulatedClock(datetime(2026, 4, 25, 15, 0, tzinfo=timezone.utc))
        bars = [
            ("TXFR1", _bar(datetime(2026, 4, 25, 15, 0) + timedelta(minutes=i)))
            for i in range(3)
        ]
        # speed_x very high so the test doesn't actually wait 3 minutes.
        src = PlaybackBarSource(bars=bars, clock=clock, speed_x=1000.0)
        captured: list[MinuteBar] = []
        src.subscribe("TXFR1", 1, lambda _sym, bar: captured.append(bar))
        await src.start()
        # Wait briefly for the background task to drain.
        await asyncio.sleep(0.5)
        await src.stop()
        # 1m subscribers see one bar per emission with no aggregation.
        assert len(captured) == 3


# -- Equivalence: live vs playback driving same subscriber --------------


class TestEquivalence:
    def test_same_input_same_output(self, tmp_path) -> None:
        """Driving identical CLOSED-bar sequences through Live vs Playback
        emits identical resampled streams. This is the contract Phase 6
        rests on.

        Live ingestion is tick-driven, so closing N 1m bars takes N+1
        ticks (the (N+1)th tick lives in the next minute and triggers
        the close of bar N). Playback consumes already-closed bars
        directly. To compare apples-to-apples we feed live N+1 ticks
        and playback the resulting N closed bars.
        """
        path = tmp_path / "market.db"
        _init_ohlcv_schema(path)
        store = LiveMinuteBarStore(db_path=path)
        live_src = LiveBarSource(store)
        live_captured: list[MinuteBar] = []
        live_src.subscribe("TXFR1", 5, lambda _sym, bar: live_captured.append(bar))
        base = datetime(2026, 4, 25, 15, 0)
        # 12 ticks → closes 11 1m bars (15:00 through 15:10 inclusive)
        for i in range(12):
            store.ingest_tick(
                "TXFR1", price=100.0 + i, volume=1,
                tick_ts=base + timedelta(minutes=i),
            )

        # Playback: 11 closed bars matching what live actually produced.
        clock = SimulatedClock(datetime(2026, 4, 25, 15, 0, tzinfo=timezone.utc))
        bars = []
        for i in range(11):
            ts = base + timedelta(minutes=i)
            bars.append((
                "TXFR1",
                MinuteBar(
                    timestamp=ts, open=100.0 + i, high=100.0 + i,
                    low=100.0 + i, close=100.0 + i, volume=1,
                ),
            ))
        playback_src = PlaybackBarSource(bars=bars, clock=clock)
        playback_captured: list[MinuteBar] = []
        playback_src.subscribe(
            "TXFR1", 5, lambda _sym, bar: playback_captured.append(bar),
        )
        asyncio.get_event_loop().run_until_complete(playback_src.replay_all())

        assert len(live_captured) == len(playback_captured)
        assert len(live_captured) == 2
        for live_bar, pb_bar in zip(live_captured, playback_captured):
            assert live_bar.open == pb_bar.open
            assert live_bar.close == pb_bar.close
            assert live_bar.high == pb_bar.high
            assert live_bar.low == pb_bar.low
            assert live_bar.volume == pb_bar.volume
            assert live_bar.timestamp == pb_bar.timestamp
