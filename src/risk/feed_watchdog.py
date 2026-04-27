"""Feed-staleness watchdog: halt sessions when broker ticks go silent.

The OpenSpec contract ``risk-monitor`` (Phase A complete) requires a
3-second feed staleness threshold during active TAIFEX sessions. The
risk monitor's ``_check_feed_state`` already implements the policy, but
its input ``update_feed_time`` is only called by the backtest pipeline
(see ``docs/live-trading-readiness-audit.md``). This watchdog closes
that wiring gap by polling ``LiveMinuteBarStore.is_stale()`` at a fixed
cadence and:

- pushing the most recent tick time into the risk monitor on every poll
  (so its existing breach logic fires deterministically); and
- as a defence in depth, calling ``SessionManager.halt()`` directly when
  the bar store reports staleness past the threshold.

Single-host, asyncio-only design: ``start()`` schedules a background
task on the supplied event loop and ``stop()`` cancels it. The clock is
injected so playback / SimulatedClock tests can advance time without
sleeping.
"""
from __future__ import annotations

import asyncio
from collections.abc import Iterable
from datetime import datetime, timezone
from typing import Any

import structlog

from src.broker_gateway.live_bar_store import LiveMinuteBarStore
from src.core.clock import Clock, default_clock

logger = structlog.get_logger(__name__)


class FeedWatchdog:
    """Polls a bar store for tick freshness and halts on prolonged silence."""

    def __init__(
        self,
        bar_store: LiveMinuteBarStore,
        session_manager: Any,
        risk_monitor: Any | None = None,
        notifier: Any | None = None,
        clock: Clock | None = None,
        max_silence_secs: float = 3.0,
        poll_interval_secs: float = 1.0,
    ) -> None:
        if max_silence_secs <= 0:
            raise ValueError(f"max_silence_secs must be positive, got {max_silence_secs}")
        if poll_interval_secs <= 0:
            raise ValueError(f"poll_interval_secs must be positive, got {poll_interval_secs}")
        self._bar_store = bar_store
        self._sm = session_manager
        self._risk_monitor = risk_monitor
        self._notifier = notifier
        self._clock = clock or default_clock()
        self._max_silence_secs = max_silence_secs
        self._poll_interval_secs = poll_interval_secs
        self._task: asyncio.Task | None = None
        self._halted_symbols: set[str] = set()
        # ``asyncio.Event`` is bound to the loop in which it's
        # constructed; defer creation until ``start()`` so the watchdog
        # can be instantiated outside any running loop (test fixtures,
        # synchronous polling via ``poll_once``).
        self._stopped: asyncio.Event | None = None

    @property
    def halted_symbols(self) -> set[str]:
        return set(self._halted_symbols)

    def start(self, loop: asyncio.AbstractEventLoop | None = None) -> None:
        """Schedule the polling task on ``loop`` (or the running loop)."""
        if self._task is not None and not self._task.done():
            return
        self._stopped = asyncio.Event()
        target_loop = loop or asyncio.get_event_loop()
        self._task = target_loop.create_task(self._run())
        logger.info(
            "feed_watchdog_started",
            max_silence_secs=self._max_silence_secs,
            poll_interval_secs=self._poll_interval_secs,
        )

    def stop(self) -> None:
        if self._task is None:
            return
        if self._stopped is not None:
            self._stopped.set()
        if not self._task.done():
            self._task.cancel()
        self._task = None
        self._stopped = None
        logger.info("feed_watchdog_stopped")

    async def _run(self) -> None:
        stopped = self._stopped
        if stopped is None:
            return
        try:
            while not stopped.is_set():
                self.poll_once()
                try:
                    await asyncio.wait_for(
                        stopped.wait(), timeout=self._poll_interval_secs,
                    )
                except asyncio.TimeoutError:
                    continue
        except asyncio.CancelledError:
            pass

    def poll_once(self, symbols: Iterable[str] | None = None) -> None:
        """Run a single staleness check across ``symbols`` (default: all tracked)."""
        now_epoch = self._clock.now().timestamp()
        check = symbols if symbols is not None else self._bar_store.tracked_symbols()
        for symbol in check:
            self._check_symbol(symbol, now_epoch)

    def _check_symbol(self, symbol: str, now_epoch: float) -> None:
        last = self._bar_store.last_tick_epoch(symbol)
        if last is None:
            return
        # Push freshness into the risk monitor so its existing
        # 3s-staleness breach logic fires through the normal `check()`
        # path. This is the wiring gap the audit identified.
        if self._risk_monitor is not None:
            try:
                self._risk_monitor.update_feed_time(
                    datetime.fromtimestamp(last, tz=timezone.utc),
                )
            except Exception:
                logger.exception(
                    "feed_watchdog_risk_update_failed", symbol=symbol,
                )

        is_stale = self._bar_store.is_stale(symbol, now_epoch, self._max_silence_secs)
        if is_stale and symbol not in self._halted_symbols:
            self._on_stale(symbol, now_epoch - last)
        elif not is_stale and symbol in self._halted_symbols:
            self._on_recovery(symbol)

    def _on_stale(self, symbol: str, silence_secs: float) -> None:
        self._halted_symbols.add(symbol)
        logger.error(
            "feed_watchdog_stale",
            symbol=symbol,
            silence_secs=round(silence_secs, 3),
            threshold_secs=self._max_silence_secs,
        )
        # Defence-in-depth: halt SessionManager directly so even if the
        # risk monitor isn't wired in this deployment, sessions stop
        # accepting new entries. ``halt()`` is global today, which is
        # the right blast radius for a feed loss in a single-broker
        # single-host topology.
        try:
            self._sm.halt()
        except Exception:
            logger.exception("feed_watchdog_halt_failed", symbol=symbol)
        if self._notifier is not None:
            try:
                self._notifier.send(
                    "feed_staleness_critical",
                    {
                        "symbol": symbol,
                        "silence_secs": round(silence_secs, 3),
                        "threshold_secs": self._max_silence_secs,
                    },
                )
            except Exception:
                logger.exception("feed_watchdog_notify_failed", symbol=symbol)

    def _on_recovery(self, symbol: str) -> None:
        self._halted_symbols.discard(symbol)
        logger.info("feed_watchdog_recovered", symbol=symbol)
        # Recovery does NOT auto-resume sessions. Per OpenSpec
        # ``risk-monitor`` Recovery scenario, an operator must
        # manually re-enable trading.
