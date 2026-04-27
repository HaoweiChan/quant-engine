"""Wall vs simulated clock abstraction.

Most production code derives time from the bar/snapshot stream; live
infrastructure that polls (feed-staleness watchdog, reconnect loop,
session-close timer) needs an injectable clock so playback/replay
sessions can advance time deterministically without sleeping.

The default ``WallClock`` is a thin wrapper around ``datetime.now`` and
``time.monotonic``. ``SimulatedClock`` lets tests and ``BacktestPlayback``
(Phase 6) drive time forward via :py:meth:`advance` instead of sleeping.

This abstraction is intentionally narrow — only ``now()`` and
``monotonic()`` — so that adopting it in existing code is a one-line
swap. Logging/audit timestamps continue to use ``datetime.now`` directly:
those are operator-facing wall-clock records, not control-flow inputs.
"""
from __future__ import annotations

import time as _time
from datetime import datetime, timedelta, timezone
from typing import Protocol, runtime_checkable


@runtime_checkable
class Clock(Protocol):
    """Minimal time source for control-flow decisions."""

    def now(self) -> datetime:
        """Return the current absolute time, timezone-aware (UTC by default)."""
        ...

    def monotonic(self) -> float:
        """Return a monotonically-increasing seconds value for elapsed measurements."""
        ...


class WallClock:
    """Production clock backed by ``datetime.now`` and ``time.monotonic``."""

    __slots__ = ()

    def now(self) -> datetime:
        return datetime.now(timezone.utc)

    def monotonic(self) -> float:
        return _time.monotonic()


class SimulatedClock:
    """Deterministic clock for tests and playback.

    ``advance(delta)`` moves both ``now()`` and ``monotonic()`` forward by
    the same amount so consumers that mix the two stay consistent.
    """

    __slots__ = ("_now", "_mono")

    def __init__(self, initial: datetime | None = None) -> None:
        if initial is None:
            initial = datetime(2026, 1, 1, tzinfo=timezone.utc)
        if initial.tzinfo is None:
            initial = initial.replace(tzinfo=timezone.utc)
        self._now = initial
        self._mono = 0.0

    def now(self) -> datetime:
        return self._now

    def monotonic(self) -> float:
        return self._mono

    def advance(self, delta: timedelta | float) -> None:
        """Advance the clock by ``delta`` seconds (or a ``timedelta``)."""
        if isinstance(delta, timedelta):
            secs = delta.total_seconds()
        else:
            secs = float(delta)
        if secs < 0:
            raise ValueError(f"clock cannot move backwards (delta={secs}s)")
        self._now = self._now + timedelta(seconds=secs)
        self._mono += secs

    def set(self, ts: datetime) -> None:
        """Jump the wall-clock component to ``ts`` (monotonic still increases by delta)."""
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        delta = (ts - self._now).total_seconds()
        if delta < 0:
            raise ValueError(f"clock cannot move backwards (delta={delta}s)")
        self._now = ts
        self._mono += delta


_DEFAULT_CLOCK: Clock = WallClock()


def default_clock() -> Clock:
    """Return the process-wide default ``Clock`` (a ``WallClock`` singleton)."""
    return _DEFAULT_CLOCK
