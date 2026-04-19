"""Unit tests for LiveSpreadBarBuilder (Phase C1).

Pins the contract: paired leg bars at the same minute_ts produce a
single synthetic spread MinuteBar; orphan leg bars buffer until the
opposite leg arrives; the offset locks after the warmup window.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.broker_gateway.live_bar_store import MinuteBar
from src.broker_gateway.live_spread_buffer import LiveSpreadBarBuilder


_TZ = timezone(timedelta(hours=8))


def _bar(minute: int, *, o: float, h: float, l: float, c: float, v: int = 100) -> MinuteBar:
    """Construct a 1m bar at 2026-04-18 10:00:`minute` Taipei."""
    return MinuteBar(
        timestamp=datetime(2026, 4, 18, 10, minute, tzinfo=_TZ),
        open=o, high=h, low=l, close=c, volume=v,
    )


def test_paired_legs_emit_one_synthetic_bar() -> None:
    builder = LiveSpreadBarBuilder("MTX", "MTX", "MTX_R2", warmup_bars=2)
    received: list[MinuteBar] = []
    builder.register_callback(lambda sym, b: received.append(b))

    # Leg 1 first — no emit until leg 2 arrives at the same minute.
    builder._on_leg_bar("MTX", _bar(0, o=20000, h=20010, l=19990, c=20005))
    assert received == []
    builder._on_leg_bar("MTX_R2", _bar(0, o=19990, h=20000, l=19980, c=19995))
    assert len(received) == 1
    bar = received[0]
    # close = 20005 - 19995 + offset; offset starts None (warmup not done) so
    # uses running min(spread_history) = max(0, -(20005-19995)+100)=90
    assert bar.close == pytest.approx(20005 - 19995 + 90.0)


def test_orphan_leg_does_not_emit() -> None:
    """A bar from one leg without a matching opposite-leg bar must NOT
    fire the callback (would corrupt downstream timestamps)."""
    builder = LiveSpreadBarBuilder("MTX", "MTX", "MTX_R2")
    received: list[MinuteBar] = []
    builder.register_callback(lambda sym, b: received.append(b))

    builder._on_leg_bar("MTX", _bar(0, o=1, h=1, l=1, c=1))
    builder._on_leg_bar("MTX", _bar(1, o=1, h=1, l=1, c=1))  # newer, replaces
    assert received == []  # leg 2 never arrived for either minute


def test_unknown_symbol_is_ignored() -> None:
    """Bars from symbols outside the configured leg pair must be dropped."""
    builder = LiveSpreadBarBuilder("MTX", "MTX", "MTX_R2")
    received: list[MinuteBar] = []
    builder.register_callback(lambda sym, b: received.append(b))
    builder._on_leg_bar("TX", _bar(0, o=1, h=1, l=1, c=1))
    builder._on_leg_bar("TX_R2", _bar(0, o=1, h=1, l=1, c=1))
    assert received == []


def test_offset_locks_after_warmup() -> None:
    """After ``warmup_bars`` paired bars the offset becomes a stable
    value used for every subsequent bar — matching the backtest
    convention so live z-scores stay comparable to the backtest's."""
    builder = LiveSpreadBarBuilder("MTX", "MTX", "MTX_R2", warmup_bars=3)
    for i in range(5):
        builder._on_leg_bar("MTX", _bar(i, o=20000, h=20000, l=20000, c=20000 + i))
        builder._on_leg_bar("MTX_R2", _bar(i, o=19990, h=19990, l=19990, c=19990 + (i // 2)))
    # offset locks after 3 paired bars.
    assert builder.offset is not None
    locked = builder.offset
    # Subsequent paired bars must reuse the same offset.
    builder._on_leg_bar("MTX", _bar(6, o=1, h=1, l=1, c=1))
    builder._on_leg_bar("MTX_R2", _bar(6, o=1, h=1, l=1, c=1))
    assert builder.offset == pytest.approx(locked)


def test_legs_must_be_distinct() -> None:
    with pytest.raises(ValueError, match="distinct legs"):
        LiveSpreadBarBuilder("MTX", "MTX", "MTX")


def test_pair_consumes_both_buffers() -> None:
    """After a paired emit, the next bar from leg 1 must NOT immediately
    pair with the previous (already-consumed) leg-2 bar.
    """
    builder = LiveSpreadBarBuilder("MTX", "MTX", "MTX_R2")
    received: list[MinuteBar] = []
    builder.register_callback(lambda sym, b: received.append(b))

    builder._on_leg_bar("MTX", _bar(0, o=1, h=1, l=1, c=1))
    builder._on_leg_bar("MTX_R2", _bar(0, o=1, h=1, l=1, c=1))
    assert len(received) == 1
    # New leg-1 bar at minute 1 — must not pair with the consumed minute-0 leg2.
    builder._on_leg_bar("MTX", _bar(1, o=1, h=1, l=1, c=1))
    assert len(received) == 1
