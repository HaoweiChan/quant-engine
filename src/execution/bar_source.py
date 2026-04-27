"""Unified bar-source interface for live and playback execution.

Today's two code paths — live (``LiveMinuteBarStore`` →
``LivePipelineManager`` → ``LiveStrategyRunner``) and chart playback
(``api/routes/playback_engine.py`` reading cached MCP backtest
results) — share no driver. The gap analysis in
``docs/live-trading-gap-analysis.md`` traces "playback function takes
a long time to tune" directly to that divergence: anything fixed on
the live path has to be re-fixed on the playback path.

This module defines a ``BarSource`` Protocol that both modes can
implement. ``LiveStrategyRunner`` already accepts a router-like object
on its ``bar_router`` parameter (Phase 2); the same runner can drive
playback when fed by a ``PlaybackBarSource``. The clock is injected so
playback uses ``SimulatedClock`` and live uses ``WallClock``.

This is the structural foundation for Phase 6 of
``.claude/plans/based-on-the-above-mellow-lemur.md``. The follow-up
work to migrate the war-room playback API onto this abstraction is
deliberately scoped out of this commit — the existing
``api/routes/playback_engine.py`` keeps serving the UI until the
migration ships separately.
"""
from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterable
from typing import Protocol, runtime_checkable

import structlog

from src.broker_gateway.live_bar_store import LiveMinuteBarStore, MinuteBar
from src.core.clock import Clock, SimulatedClock, default_clock
from src.data.multi_timeframe_router import MultiTimeframeRouter

logger = structlog.get_logger(__name__)

BarCallback = Callable[[str, MinuteBar], None]


@runtime_checkable
class BarSource(Protocol):
    """Common interface for live and playback bar streams.

    A ``BarSource`` fans bars into per-(symbol, tf) callbacks. Live
    sources push as ticks arrive; playback sources push at a controlled
    cadence governed by a ``SimulatedClock``.
    """

    def subscribe(self, symbol: str, tf_minutes: int, callback: BarCallback) -> None: ...
    def unsubscribe(self, callback: BarCallback) -> None: ...
    async def start(self) -> None: ...
    async def stop(self) -> None: ...


class LiveBarSource:
    """Wraps ``LiveMinuteBarStore`` + ``MultiTimeframeRouter`` as a ``BarSource``.

    Live ticks arrive on the broker callback thread, get aggregated into
    1m bars by the store, then routed through the resampling router so
    subscribers receive bars at any registered timeframe (1, 3, 5, 15,
    30, 60 minutes). ``start()`` / ``stop()`` are no-ops because the
    store is tick-driven from the gateway, not pulled by the source.
    """

    def __init__(
        self,
        bar_store: LiveMinuteBarStore,
        router: MultiTimeframeRouter | None = None,
        clock: Clock | None = None,
    ) -> None:
        self._bar_store = bar_store
        self._router = router or MultiTimeframeRouter()
        self._clock = clock or default_clock()
        self._attached = False

    def _attach(self) -> None:
        if self._attached:
            return
        self._bar_store.register_bar_callback(self._router.on_minute_bar)
        self._attached = True

    def subscribe(self, symbol: str, tf_minutes: int, callback: BarCallback) -> None:
        self._attach()
        self._router.subscribe(symbol, tf_minutes, callback)

    def unsubscribe(self, callback: BarCallback) -> None:
        self._router.unsubscribe(callback)

    async def start(self) -> None:
        # Tick-driven from the gateway; nothing to schedule here.
        self._attach()

    async def stop(self) -> None:
        # Detach is a no-op: the bar store callback list isn't expected
        # to remove individual subscribers in this version.
        return


class PlaybackBarSource:
    """Replays a finite iterable of 1m bars at a controlled cadence.

    Bars flow through a ``MultiTimeframeRouter`` so subscribers see the
    same resampled stream they'd see in live mode. ``speed_x`` accelerates
    or decelerates real-time playback (1.0 = real time, 60.0 = 1 minute
    of bars per real second). The injected ``SimulatedClock`` advances
    by the bar interval as each bar is emitted, so consumers that read
    the clock (force-flat timer, watchdog) stay in sync with the bar
    stream rather than wall time.
    """

    def __init__(
        self,
        bars: Iterable[tuple[str, MinuteBar]],
        clock: SimulatedClock,
        router: MultiTimeframeRouter | None = None,
        speed_x: float = 1.0,
        bar_interval_secs: float = 60.0,
    ) -> None:
        if speed_x <= 0:
            raise ValueError(f"speed_x must be positive, got {speed_x}")
        if bar_interval_secs <= 0:
            raise ValueError(f"bar_interval_secs must be positive, got {bar_interval_secs}")
        self._bars: list[tuple[str, MinuteBar]] = list(bars)
        self._router = router or MultiTimeframeRouter()
        self._clock = clock
        self._speed_x = speed_x
        self._bar_interval_secs = bar_interval_secs
        self._task: asyncio.Task | None = None
        self._stopped: asyncio.Event | None = None

    @property
    def clock(self) -> SimulatedClock:
        return self._clock

    @property
    def bars_remaining(self) -> int:
        return len(self._bars)

    def subscribe(self, symbol: str, tf_minutes: int, callback: BarCallback) -> None:
        self._router.subscribe(symbol, tf_minutes, callback)

    def unsubscribe(self, callback: BarCallback) -> None:
        self._router.unsubscribe(callback)

    async def start(self) -> None:
        """Begin replaying bars. Returns immediately; bars stream on background task."""
        if self._task is not None and not self._task.done():
            return
        self._stopped = asyncio.Event()
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._stopped is not None:
            self._stopped.set()
        if self._task is not None:
            try:
                await asyncio.wait_for(self._task, timeout=2.0)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                self._task.cancel()
        self._task = None
        self._stopped = None

    async def replay_all(self) -> int:
        """Synchronously emit every bar; useful for tests where ``speed_x`` is irrelevant."""
        count = 0
        for symbol, bar in self._bars:
            self._router.on_minute_bar(symbol, bar)
            self._clock.advance(self._bar_interval_secs)
            count += 1
        self._bars.clear()
        return count

    async def _run(self) -> None:
        sleep_secs = self._bar_interval_secs / self._speed_x
        try:
            for symbol, bar in self._bars:
                if self._stopped is not None and self._stopped.is_set():
                    return
                self._router.on_minute_bar(symbol, bar)
                self._clock.advance(self._bar_interval_secs)
                if sleep_secs > 0:
                    try:
                        if self._stopped is not None:
                            await asyncio.wait_for(
                                self._stopped.wait(), timeout=sleep_secs,
                            )
                            return
                        else:
                            await asyncio.sleep(sleep_secs)
                    except asyncio.TimeoutError:
                        continue
            self._bars.clear()
        except asyncio.CancelledError:
            pass
