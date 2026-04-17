"""Portfolio-level kill-switch triggered by correlation-drift events.

Sits alongside ``DisasterStopMonitor`` (which watches per-position disaster
levels). When a portfolio-scale regime shift is detected (correlations
drift beyond tolerance, or trailing Sharpe collapses below backtest
expectations), this kill-switch flattens EVERY open position across ALL
runners in the live pipeline — not just one position.

Designed to consume ``CorrelationDriftEvent`` instances from
``src.monitoring.correlation_monitor.CorrelationMonitor``. The
``trigger()`` coroutine iterates each active runner, emits market exit
orders for every open position, and records the event for post-mortem.
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import structlog

from src.core.types import Order

if TYPE_CHECKING:
    from src.execution.live_pipeline import LivePipelineManager
    from src.monitoring.correlation_monitor import (
        CorrelationDriftEvent,
        CorrelationMonitor,
    )

logger = structlog.get_logger(__name__)


@dataclass
class KillSwitchTrigger:
    """Audit record for a single kill-switch firing."""

    triggered_at: str
    reason: str
    orders_issued: int
    runners_affected: list[str] = field(default_factory=list)
    event_details: dict[str, Any] = field(default_factory=dict)


class PortfolioKillSwitch:
    """Flattens every open position across every live runner on a single trigger.

    Usage:
        kill = PortfolioKillSwitch(pipeline_manager, execute_fn)
        kill.attach_monitor(correlation_monitor)

        # Periodically (e.g. on bar-complete or alert callback):
        event = correlation_monitor.check_drift(baseline_corr, ...)
        if event.triggered:
            await kill.trigger(reason="correlation_drift", event=event)

    ``execute_fn`` is an awaitable taking ``list[Order]``; the same shape
    used by ``DisasterStopMonitor``. Typically supplied by the live or
    paper executor.
    """

    def __init__(
        self,
        pipeline_manager: LivePipelineManager,
        execute_fn: Callable[[list[Order]], Awaitable[None]],
    ) -> None:
        self._pipeline = pipeline_manager
        self._execute_fn = execute_fn
        self._monitor: CorrelationMonitor | None = None
        self._triggers: list[KillSwitchTrigger] = []
        self._armed: bool = True

    # --------------------------------------------------------------- wiring
    def attach_monitor(self, monitor: CorrelationMonitor) -> None:
        self._monitor = monitor

    @property
    def triggers(self) -> list[KillSwitchTrigger]:
        return list(self._triggers)

    @property
    def armed(self) -> bool:
        return self._armed

    def arm(self) -> None:
        """Re-enable the kill-switch after a trigger (manual reset).

        Also resets the attached CorrelationMonitor's rolling buffers so
        the drift condition has to re-accumulate fresh observations before
        the switch can fire again. Prevents instant re-fire on lingering
        drift.
        """
        self._armed = True
        if self._monitor is not None:
            try:
                self._monitor.reset()
            except Exception:
                logger.exception("portfolio_kill_switch_monitor_reset_failed")
        logger.info("portfolio_kill_switch_armed")

    def disarm(self) -> None:
        """Prevent further triggers (e.g. during maintenance)."""
        self._armed = False
        logger.info("portfolio_kill_switch_disarmed")

    # ---------------------------------------------------- drift auto-check
    async def check_correlation_drift(
        self,
        baseline_correlation: Any,
        trailing_sharpe: float | None = None,
        backtest_sharpe: float | None = None,
    ) -> CorrelationDriftEvent | None:
        """Call the attached monitor's check_drift; trigger if positive."""
        if self._monitor is None:
            return None
        event = self._monitor.check_drift(
            baseline_correlation=baseline_correlation,
            trailing_sharpe=trailing_sharpe,
            backtest_sharpe=backtest_sharpe,
        )
        if event.triggered and self._armed:
            reason = (
                "sharpe_drift"
                if event.sharpe_triggered and not event.pairs_drifted
                else "correlation_drift"
            )
            await self.trigger(reason=reason, event=event)
        return event

    # ----------------------------------------------------------- trigger
    async def trigger(
        self,
        reason: str,
        event: Any = None,
    ) -> KillSwitchTrigger:
        """Flatten every open position across every active runner."""
        if not self._armed:
            logger.warning(
                "portfolio_kill_switch_trigger_ignored",
                reason="disarmed",
                requested_reason=reason,
            )
            return KillSwitchTrigger(
                triggered_at=datetime.now(UTC).astimezone().isoformat(),
                reason=f"ignored:{reason}",
                orders_issued=0,
                event_details=_event_to_dict(event),
            )

        orders: list[Order] = []
        runners_affected: list[str] = []
        # iter_runners returns a lock-safe snapshot so concurrent
        # _sync_runners activity cannot mutate the dict during flatten.
        if hasattr(self._pipeline, "iter_runners"):
            runners_iter = self._pipeline.iter_runners()
        else:
            # Back-compat: older managers without iter_runners
            runners_iter = list(self._pipeline._runners.items())
        for session_id, runner in runners_iter:
            runner_orders = _flatten_orders_for_runner(runner)
            if runner_orders:
                orders.extend(runner_orders)
                runners_affected.append(session_id)

        trigger_record = KillSwitchTrigger(
            triggered_at=datetime.now(UTC).astimezone().isoformat(),
            reason=reason,
            orders_issued=len(orders),
            runners_affected=runners_affected,
            event_details=_event_to_dict(event),
        )

        logger.warning(
            "PORTFOLIO_KILL_SWITCH_FIRED",
            reason=reason,
            orders=len(orders),
            runners=runners_affected,
            drift_event=trigger_record.event_details,
        )

        if orders:
            try:
                await self._execute_fn(orders)
            except Exception:
                logger.exception(
                    "portfolio_kill_switch_execute_failed",
                    reason=reason,
                )
        # Disarm until manually re-armed to avoid repeated fire on lingering drift
        self._armed = False
        self._triggers.append(trigger_record)
        return trigger_record


def _flatten_orders_for_runner(runner: Any) -> list[Order]:
    """Build market-exit orders for every open position on a runner.

    Gracefully tolerates runners without ``positions`` or ``symbol`` — they
    contribute zero orders.
    """
    positions = getattr(runner, "positions", None)
    if not positions:
        return []
    symbol = getattr(runner, "symbol", None)
    orders: list[Order] = []
    for pos in positions:
        direction = getattr(pos, "direction", None)
        lots = float(getattr(pos, "lots", 0.0) or 0.0)
        if lots <= 0 or direction not in ("long", "short"):
            continue
        close_side = "sell" if direction == "long" else "buy"
        orders.append(Order(
            order_type="market",
            side=close_side,
            symbol=symbol or getattr(pos, "symbol", ""),
            contract_type=getattr(pos, "contract_type", "large"),
            lots=lots,
            price=None,
            stop_price=None,
            reason="portfolio_kill_switch",
            metadata={
                "position_id": getattr(pos, "position_id", None),
                "session_id": getattr(runner, "session_id", None),
                "strategy_slug": getattr(runner, "strategy_slug", None),
            },
            parent_position_id=getattr(pos, "position_id", None),
            order_class="disaster_stop",
        ))
    return orders


def _event_to_dict(event: Any) -> dict[str, Any]:
    if event is None:
        return {}
    return {
        "triggered": getattr(event, "triggered", None),
        "max_delta": getattr(event, "max_delta", None),
        "n_pairs_drifted": len(getattr(event, "pairs_drifted", []) or []),
        "sharpe_ratio": getattr(event, "sharpe_ratio", None),
        "sharpe_triggered": getattr(event, "sharpe_triggered", None),
        "detected_at": getattr(event, "detected_at", None),
    }
