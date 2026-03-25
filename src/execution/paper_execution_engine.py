"""Paper execution engine with disaster stop simulation."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

import structlog

from src.alerting.dispatcher import NotificationDispatcher
from src.core.position_engine import PositionEngine
from src.core.types import EngineConfig, MarketSnapshot, Order
from src.execution.disaster_stop_monitor import (
    PaperDisasterStopMonitor,
    DisasterStopEntry,
    compute_disaster_level,
)
from src.execution.engine import ExecutionEngine, ExecutionResult

logger = structlog.get_logger(__name__)


class PaperExecutionEngine:
    """Paper execution engine with paper disaster stop simulation."""

    def __init__(
        self,
        executor: ExecutionEngine,
        position_engine: PositionEngine,
        config: EngineConfig,
        dispatcher: NotificationDispatcher | None = None,
    ) -> None:
        self._executor = executor
        self._engine = position_engine
        self._config = config
        self._dispatcher = dispatcher
        self._active_disaster_stops: int = 0

        if config.disaster_stop_enabled:
            self._monitor: PaperDisasterStopMonitor | None = PaperDisasterStopMonitor(
                self._execute_disaster_order
            )
        else:
            self._monitor = None

    async def execute(self, orders: list[Order], snapshot: MarketSnapshot) -> list[ExecutionResult]:
        if not orders:
            return []

        orders_to_execute: list[Order] = []
        for order in orders:
            if order.order_class == "algo_exit":
                if self._monitor is not None and order.parent_position_id:
                    self._monitor.deregister(order.parent_position_id)
                    self._active_disaster_stops = self._monitor.active_count()
                orders_to_execute.append(order)
            else:
                orders_to_execute.append(order)

        results = await self._executor.execute(orders_to_execute)

        for result in results:
            if result.status != "filled":
                continue

            filled_order = result.order

            if filled_order.order_class == "standard" and filled_order.reason == "entry":
                if self._monitor is not None and filled_order.parent_position_id:
                    daily_atr = snapshot.atr.get("daily", 0.0)
                    direction = self._infer_direction_from_fill(filled_order, result)
                    disaster_level = compute_disaster_level(
                        result.fill_price,
                        direction,
                        daily_atr,
                        self._config.disaster_atr_mult,
                    )
                    entry = DisasterStopEntry(
                        position_id=filled_order.parent_position_id,
                        direction=direction,
                        disaster_level=disaster_level,
                        lots=filled_order.lots,
                        contract_type=filled_order.contract_type,
                        symbol=filled_order.symbol,
                    )
                    self._monitor.register(entry)
                    self._active_disaster_stops = self._monitor.active_count()

            elif filled_order.order_class == "disaster_stop":
                await self._handle_disaster_fill(result, snapshot.timestamp)

        return results

    async def on_bar_open(self, symbol: str, open_price: float) -> None:
        if self._monitor is not None:
            await self._monitor.on_bar_open(symbol, open_price)
            self._active_disaster_stops = self._monitor.active_count()

    def get_fill_stats(self) -> dict[str, float]:
        base_stats = self._executor.get_fill_stats()
        base_stats["active_disaster_stops"] = float(self._active_disaster_stops)
        return base_stats

    async def _execute_disaster_order(self, orders: list[Order]) -> None:
        if not orders:
            return
        try:
            await self._executor.execute(orders)
        except Exception:
            logger.exception("paper_disaster_order_execute_failed")

    async def _handle_disaster_fill(self, result: ExecutionResult, timestamp: datetime) -> None:
        position_id = result.order.parent_position_id
        if position_id and hasattr(self._engine, "close_position_by_disaster_stop"):
            self._engine.close_position_by_disaster_stop(
                position_id=position_id,
                fill_price=result.fill_price,
                fill_timestamp=timestamp,
            )

        if self._dispatcher is not None:
            try:
                alert_msg = (
                    f"DISASTER_STOP_FILLED: position_id={position_id}, "
                    f"symbol={result.order.symbol}, "
                    f"fill_price={result.fill_price}, "
                    f"paper=True"
                )
                await self._dispatcher.dispatch(alert_msg)
            except Exception:
                logger.exception("paper_disaster_alert_failed")

    @staticmethod
    def _infer_direction_from_fill(
        order: Order, result: ExecutionResult
    ) -> Literal["long", "short"]:
        return "long" if order.side == "buy" else "short"
