"""End-to-end pipeline runner: Data -> Prediction -> Position -> Execution."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import structlog

from src.alerting.dispatcher import NotificationDispatcher
from src.alerting.formatters import format_risk_alert, format_trade
from src.core.position_engine import PositionEngine
from src.core.types import (
    AccountState,
    MarketSignal,
    MarketSnapshot,
    Position,
    RiskAction,
)
from src.execution.engine import ExecutionEngine, ExecutionResult
from src.execution.paper import PaperExecutor
from src.risk.monitor import RiskMonitor

logger = structlog.get_logger(__name__)


@dataclass
class PipelineState:
    equity: float = 0.0
    unrealized_pnl: float = 0.0
    realized_pnl: float = 0.0
    positions: list[Position] = field(default_factory=list)
    mode: str = "model_assisted"
    last_signal: MarketSignal | None = None
    last_price: float = 0.0
    bar_count: int = 0


@dataclass
class PipelineResult:
    equity_curve: list[float] = field(default_factory=list)
    trade_log: list[ExecutionResult] = field(default_factory=list)
    risk_events: list[Any] = field(default_factory=list)
    final_equity: float = 0.0
    total_trades: int = 0


class PipelineRunner:
    """Orchestrates the full pipeline: snapshot -> signal -> engine -> execution."""

    def __init__(
        self,
        position_engine: PositionEngine,
        executor: ExecutionEngine,
        risk_monitor: RiskMonitor | None = None,
        initial_equity: float = 2_000_000.0,
        dispatcher: NotificationDispatcher | None = None,
    ) -> None:
        self._engine = position_engine
        self._executor = executor
        self._risk_monitor = risk_monitor
        self._dispatcher = dispatcher
        self._state = PipelineState(equity=initial_equity)
        self._equity_curve: list[float] = [initial_equity]
        self._trade_log: list[ExecutionResult] = []

    async def run_step(
        self,
        snapshot: MarketSnapshot,
        signal: MarketSignal | None = None,
    ) -> list[ExecutionResult]:
        """Process a single bar through the full pipeline."""
        self._state.last_price = snapshot.price
        self._state.bar_count += 1

        if isinstance(self._executor, PaperExecutor):
            self._executor.set_market_state(snapshot.price)

        if self._risk_monitor is not None:
            self._risk_monitor.update_feed_time(snapshot.timestamp)
            if signal is not None:
                self._risk_monitor.update_signal_time(signal.timestamp)

        account = self._build_account_state(snapshot)
        if self._risk_monitor is not None:
            action = self._risk_monitor.check(account)
            await self._apply_risk_action(action, snapshot)

        orders = self._engine.on_snapshot(snapshot, signal, account)

        results = await self._executor.execute(orders) if orders else []
        for r in results:
            self._trade_log.append(r)
            if r.status == "filled":
                pnl = self._compute_fill_pnl(r)
                self._state.realized_pnl += pnl
                await self._notify_trade(r)

        engine_state = self._engine.get_state()
        self._state.positions = list(engine_state.positions)
        self._state.mode = engine_state.mode
        self._state.unrealized_pnl = engine_state.total_unrealized_pnl
        self._state.last_signal = signal

        current_equity = self._state.equity + self._state.realized_pnl + self._state.unrealized_pnl
        self._equity_curve.append(current_equity)

        return results

    async def run_historical(
        self,
        snapshots: list[MarketSnapshot],
        signals: list[MarketSignal | None] | None = None,
    ) -> PipelineResult:
        """Run pipeline over a sequence of historical bars."""
        if signals is None:
            signals = [None] * len(snapshots)

        for snap, sig in zip(snapshots, signals, strict=True):
            await self.run_step(snap, sig)

        risk_events = self._risk_monitor.events if self._risk_monitor else []
        return PipelineResult(
            equity_curve=list(self._equity_curve),
            trade_log=list(self._trade_log),
            risk_events=risk_events,
            final_equity=self._equity_curve[-1] if self._equity_curve else 0.0,
            total_trades=len(self._trade_log),
        )

    def get_state_snapshot(self) -> dict[str, Any]:
        return {
            "equity": self._equity_curve[-1] if self._equity_curve else self._state.equity,
            "realized_pnl": self._state.realized_pnl,
            "unrealized_pnl": self._state.unrealized_pnl,
            "positions": len(self._state.positions),
            "mode": self._state.mode,
            "last_price": self._state.last_price,
            "bar_count": self._state.bar_count,
            "total_trades": len(self._trade_log),
        }

    def _build_account_state(self, snapshot: MarketSnapshot) -> AccountState:
        equity = self._state.equity + self._state.realized_pnl
        unrealized = self._state.unrealized_pnl
        margin_used = sum(
            p.lots * snapshot.margin_per_unit for p in self._state.positions
        )
        margin_avail = max(equity - margin_used, 0.0)
        margin_ratio = margin_used / equity if equity > 0 else 0.0
        peak = max(self._equity_curve) if self._equity_curve else equity
        drawdown_pct = (peak - (equity + unrealized)) / peak if peak > 0 else 0.0
        drawdown_pct = max(0.0, min(1.0, drawdown_pct))
        return AccountState(
            equity=equity,
            unrealized_pnl=unrealized,
            realized_pnl=self._state.realized_pnl,
            margin_used=margin_used,
            margin_available=margin_avail,
            margin_ratio=margin_ratio,
            drawdown_pct=drawdown_pct,
            positions=list(self._state.positions),
            timestamp=snapshot.timestamp,
        )

    async def _apply_risk_action(self, action: RiskAction, snapshot: MarketSnapshot) -> None:
        if action == RiskAction.CLOSE_ALL:
            self._engine.set_mode("halted")
            await self._notify_risk(action, "close_all_triggered")
        elif action == RiskAction.HALT_NEW_ENTRIES:
            if self._engine.get_state().mode != "halted":
                self._engine.set_mode("halted")
            await self._notify_risk(action, "halt_new_entries")
        elif action == RiskAction.REDUCE_HALF:
            await self._notify_risk(action, "reduce_half")

    async def _notify_trade(self, result: ExecutionResult) -> None:
        if self._dispatcher is None:
            return
        try:
            msg = format_trade(result)
            await self._dispatcher.dispatch(msg)
        except Exception:
            logger.exception("trade_notification_failed")

    async def _notify_risk(self, action: RiskAction, trigger: str) -> None:
        if self._dispatcher is None or action == RiskAction.NORMAL:
            return
        try:
            msg = format_risk_alert(action, trigger, {})
            await self._dispatcher.dispatch(msg)
        except Exception:
            logger.exception("risk_notification_failed")

    @staticmethod
    def _compute_fill_pnl(result: ExecutionResult) -> float:
        if result.order.side == "sell" and result.order.reason != "entry":
            return 0.0  # PnL tracked by position closing logic
        return 0.0
