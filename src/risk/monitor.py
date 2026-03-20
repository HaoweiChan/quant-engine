"""Risk Monitor: independent watchdog with circuit breaker and safety checks."""
from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import structlog

from src.core.types import AccountState, RiskAction
from src.pipeline.config import RiskConfig

logger = structlog.get_logger(__name__)


@dataclass
class RiskEvent:
    timestamp: datetime
    action: RiskAction
    trigger: str
    details: dict[str, Any]


class RiskMonitor:
    """Independent risk watchdog with configurable thresholds."""

    def __init__(
        self,
        config: RiskConfig,
        on_mode_change: Callable[[str], None] | None = None,
        on_force_close: Callable[[], list[Any]] | None = None,
    ) -> None:
        self._config = config
        self._on_mode_change = on_mode_change
        self._on_force_close = on_force_close
        self._last_signal_time: datetime | None = None
        self._last_feed_time: datetime | None = None
        self._current_spread: float = 0.0
        self._normal_spread: float = 1.0
        self._events: list[RiskEvent] = []
        self._task: asyncio.Task[None] | None = None

    def check(self, account: AccountState) -> RiskAction:
        """Evaluate all risk conditions and return the highest priority action."""
        now = account.timestamp

        # Priority 1: Drawdown circuit breaker
        if account.equity > 0:
            drawdown_amount = account.drawdown_pct * account.equity
            if drawdown_amount >= self._config.max_loss:
                self._emit_event(now, RiskAction.CLOSE_ALL, "drawdown_circuit_breaker", {
                    "drawdown_pct": account.drawdown_pct,
                    "drawdown_amount": drawdown_amount,
                    "max_loss": self._config.max_loss,
                })
                if self._on_force_close is not None:
                    self._on_force_close()
                if self._on_mode_change is not None:
                    self._on_mode_change("halted")
                return RiskAction.CLOSE_ALL

        # Priority 2: Feed staleness
        if self._last_feed_time is not None:
            feed_age = now - self._last_feed_time
            limit = timedelta(minutes=self._config.feed_staleness_minutes)
            if feed_age > limit:
                self._emit_event(now, RiskAction.HALT_NEW_ENTRIES, "feed_staleness", {
                    "feed_age_seconds": feed_age.total_seconds(),
                    "limit_minutes": self._config.feed_staleness_minutes,
                })
                return RiskAction.HALT_NEW_ENTRIES

        # Priority 3: Spread spike anomaly
        if self._normal_spread > 0 and self._current_spread > 0:
            ratio = self._current_spread / self._normal_spread
            if ratio > self._config.spread_spike_multiplier:
                self._emit_event(now, RiskAction.HALT_NEW_ENTRIES, "spread_spike", {
                    "current_spread": self._current_spread,
                    "normal_spread": self._normal_spread,
                    "ratio": ratio,
                })
                return RiskAction.HALT_NEW_ENTRIES

        # Priority 4: Signal staleness
        if self._last_signal_time is not None:
            signal_age = now - self._last_signal_time
            limit = timedelta(hours=self._config.signal_staleness_hours)
            if signal_age > limit:
                self._emit_event(now, RiskAction.HALT_NEW_ENTRIES, "signal_staleness", {
                    "signal_age_seconds": signal_age.total_seconds(),
                    "limit_hours": self._config.signal_staleness_hours,
                })
                if self._on_mode_change is not None:
                    self._on_mode_change("rule_only")
                return RiskAction.HALT_NEW_ENTRIES

        # Priority 5: Margin ratio
        if account.margin_ratio < self._config.margin_ratio_threshold and account.positions:
            self._emit_event(now, RiskAction.REDUCE_HALF, "low_margin", {
                "margin_ratio": account.margin_ratio,
                "threshold": self._config.margin_ratio_threshold,
            })
            return RiskAction.REDUCE_HALF

        return RiskAction.NORMAL

    def update_signal_time(self, ts: datetime) -> None:
        self._last_signal_time = ts

    def update_feed_time(self, ts: datetime) -> None:
        self._last_feed_time = ts

    def update_spread(self, current: float, normal: float) -> None:
        self._current_spread = current
        self._normal_spread = normal

    def set_position_engine_mode(self, mode: str) -> None:
        if self._on_mode_change is not None:
            self._on_mode_change(mode)
        logger.info("engine_mode_changed", mode=mode)

    def force_close_all(self) -> list[Any]:
        if self._on_force_close is not None:
            return self._on_force_close()
        return []

    @property
    def events(self) -> list[RiskEvent]:
        return list(self._events)

    async def start_async_loop(
        self, get_account: Callable[[], AccountState],
    ) -> None:
        """Run periodic check loop as an asyncio task."""
        interval = self._config.check_interval_seconds
        try:
            while True:
                account = get_account()
                self.check(account)
                await asyncio.sleep(interval)
        except asyncio.CancelledError:
            logger.info("risk_loop_cancelled")

    def start(self, get_account: Callable[[], AccountState]) -> asyncio.Task[None]:
        """Start the async check loop and return the task."""
        self._task = asyncio.create_task(self.start_async_loop(get_account))
        return self._task

    def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            self._task = None

    def _emit_event(
        self, ts: datetime, action: RiskAction, trigger: str, details: dict[str, Any],
    ) -> None:
        event = RiskEvent(timestamp=ts, action=action, trigger=trigger, details=details)
        self._events.append(event)
        logger.warning("risk_event", action=action.value, trigger=trigger, **details)
