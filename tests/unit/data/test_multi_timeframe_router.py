"""Tests for ``src/data/multi_timeframe_router.py``."""
from __future__ import annotations

from datetime import datetime, timedelta

from src.broker_gateway.live_bar_store import MinuteBar
from src.data.multi_timeframe_router import MultiTimeframeRouter


def _bar(ts: datetime, base: float = 100.0) -> MinuteBar:
    return MinuteBar(
        timestamp=ts,
        open=base,
        high=base + 1,
        low=base - 1,
        close=base + 0.5,
        volume=10,
    )


class TestMultiTimeframeRouter:
    def test_emits_resampled_bars_at_tf_boundary(self) -> None:
        router = MultiTimeframeRouter()
        captured: list[MinuteBar] = []
        router.subscribe(
            "TXF", 5, lambda _sym, bar: captured.append(bar),
        )
        # Start of day session: 08:45 onward. Feed 6 1m bars.
        start = datetime(2026, 4, 25, 8, 45)
        for i in range(6):
            router.on_minute_bar("TXF", _bar(start + timedelta(minutes=i), 100 + i))
        # Window 08:45-08:49 (bucket 0) closes when the 08:50 bar (bucket 1)
        # arrives → 1 emit. Folds first 5 bars (100..104) but emits BEFORE
        # the 6th bar's data is included.
        assert len(captured) == 1
        assert captured[0].timestamp == start
        assert captured[0].open == 100.0
        assert captured[0].close == 104.5
        assert captured[0].high == 105.0
        assert captured[0].low == 99.0
        assert captured[0].volume == 50

    def test_emits_per_tf_independently(self) -> None:
        router = MultiTimeframeRouter()
        three: list[MinuteBar] = []
        five: list[MinuteBar] = []
        router.subscribe("TXF", 3, lambda _sym, bar: three.append(bar))
        router.subscribe("TXF", 5, lambda _sym, bar: five.append(bar))
        start = datetime(2026, 4, 25, 8, 45)
        for i in range(15):
            router.on_minute_bar("TXF", _bar(start + timedelta(minutes=i), 100 + i))
        # Windows close on the *next* boundary-crossing bar (matches
        # LiveMinuteBarStore semantics). 15 bars produces 4 fully-closed
        # 3-min windows and 2 fully-closed 5-min windows; the trailing
        # window in each TF stays open until the next bar arrives.
        assert len(three) == 4
        assert len(five) == 2

    def test_session_boundary_flushes_partial_window(self) -> None:
        router = MultiTimeframeRouter()
        captured: list[MinuteBar] = []
        router.subscribe("TXF", 5, lambda _sym, bar: captured.append(bar))
        # Last 2 bars of day session (13:43, 13:44), then first bar of
        # night session (15:00). The day-session 5m window (which the
        # session-relative bucket places at 13:40 — five-minute aligned
        # to session open at 08:45) should flush as a partial 2-bar
        # window when the 15:00 bar arrives in a new session.
        router.on_minute_bar("TXF", _bar(datetime(2026, 4, 25, 13, 43)))
        router.on_minute_bar("TXF", _bar(datetime(2026, 4, 25, 13, 44)))
        router.on_minute_bar("TXF", _bar(datetime(2026, 4, 25, 15, 0)))
        # Partial-day window is emitted on session change.
        assert len(captured) == 1
        # Bucket 0 of day session: 08:45 + 59 * 5min = 13:40
        assert captured[0].timestamp == datetime(2026, 4, 25, 13, 40)
        assert captured[0].volume == 20  # two folded bars of 10 each

    def test_one_minute_subscribers_receive_raw_bars(self) -> None:
        router = MultiTimeframeRouter()
        captured: list[MinuteBar] = []
        router.subscribe("TXF", 1, lambda _sym, bar: captured.append(bar))
        start = datetime(2026, 4, 25, 8, 45)
        for i in range(3):
            router.on_minute_bar("TXF", _bar(start + timedelta(minutes=i), 100 + i))
        # 1m subscribers see one bar per tick, no aggregation.
        assert len(captured) == 3

    def test_unsubscribe_stops_callbacks(self) -> None:
        router = MultiTimeframeRouter()
        captured: list[MinuteBar] = []

        def cb(_sym, bar):
            captured.append(bar)

        router.subscribe("TXF", 1, cb)
        router.on_minute_bar("TXF", _bar(datetime(2026, 4, 25, 8, 45)))
        router.unsubscribe(cb)
        router.on_minute_bar("TXF", _bar(datetime(2026, 4, 25, 8, 46)))
        assert len(captured) == 1

    def test_closed_session_minutes_dropped(self) -> None:
        router = MultiTimeframeRouter()
        captured: list[MinuteBar] = []
        router.subscribe("TXF", 1, lambda _sym, bar: captured.append(bar))
        # 14:00 is in the closed window (13:45-15:00) — should be ignored.
        router.on_minute_bar("TXF", _bar(datetime(2026, 4, 25, 14, 0)))
        assert captured == []

    def test_per_symbol_isolation(self) -> None:
        router = MultiTimeframeRouter()
        a: list[MinuteBar] = []
        b: list[MinuteBar] = []
        router.subscribe("TXF", 5, lambda _sym, bar: a.append(bar))
        router.subscribe("MTX", 5, lambda _sym, bar: b.append(bar))
        start = datetime(2026, 4, 25, 8, 45)
        # Feeding bars only for TXF must never trigger MTX subscribers.
        for i in range(6):
            router.on_minute_bar("TXF", _bar(start + timedelta(minutes=i)))
        assert len(a) == 1
        assert b == []

    def test_callback_exceptions_isolated(self) -> None:
        router = MultiTimeframeRouter()
        good: list[MinuteBar] = []

        def bad(_sym, _bar):
            raise RuntimeError("boom")

        router.subscribe("TXF", 1, bad)
        router.subscribe("TXF", 1, lambda _sym, bar: good.append(bar))
        router.on_minute_bar("TXF", _bar(datetime(2026, 4, 25, 8, 45)))
        # Bad subscriber must not block the good one.
        assert len(good) == 1

    def test_reset_clears_windows(self) -> None:
        router = MultiTimeframeRouter()
        captured: list[MinuteBar] = []
        router.subscribe("TXF", 5, lambda _sym, bar: captured.append(bar))
        start = datetime(2026, 4, 25, 8, 45)
        # Fill 3 of 5 bars then reset; after reset, 5 fresh bars complete
        # a window without resurrecting the discarded ones.
        for i in range(3):
            router.on_minute_bar("TXF", _bar(start + timedelta(minutes=i), 100))
        router.reset("TXF")
        for i in range(6):
            router.on_minute_bar("TXF", _bar(start + timedelta(minutes=10 + i), 200))
        assert len(captured) == 1
        assert captured[0].open == 200.0
