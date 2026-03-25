"""Disaster Stop Monitor: independent asyncio task watching per-position disaster levels."""

from __future__ import annotations

import asyncio
import structlog
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Literal

from src.core.types import Order

logger = structlog.get_logger(__name__)


@dataclass
class DisasterStopEntry:
    position_id: str
    direction: Literal["long", "short"]
    disaster_level: float
    lots: float
    contract_type: str
    symbol: str
    closed: bool = False


class DisasterStopMonitor:
    def __init__(self, execute_fn: Callable[[list[Order]], Awaitable[None]]) -> None:
        self._execute_fn = execute_fn
        self._entries: dict[str, DisasterStopEntry] = {}

    def register(self, entry: DisasterStopEntry) -> None:
        self._entries[entry.position_id] = entry
        logger.debug(
            "disaster_stop_registered",
            position_id=entry.position_id,
            symbol=entry.symbol,
            disaster_level=entry.disaster_level,
        )

    def deregister(self, position_id: str) -> None:
        self._entries.pop(position_id, None)
        logger.debug("disaster_stop_deregistered", position_id=position_id)

    def active_count(self) -> int:
        return len(self._entries)

    async def on_tick(self, price: float, symbol: str) -> None:
        for entry in list(self._entries.values()):
            if entry.closed or entry.symbol != symbol:
                continue

            breached = (
                price <= entry.disaster_level
                if entry.direction == "long"
                else price >= entry.disaster_level
            )

            if not breached:
                continue

            entry.closed = True
            close_side = "sell" if entry.direction == "long" else "buy"
            disaster_order = Order(
                order_type="market",
                side=close_side,
                symbol=entry.symbol,
                contract_type=entry.contract_type,
                lots=entry.lots,
                price=None,
                stop_price=None,
                reason="disaster_stop",
                metadata={
                    "position_id": entry.position_id,
                    "disaster_level": entry.disaster_level,
                    "trigger_price": price,
                },
                parent_position_id=entry.position_id,
                order_class="disaster_stop",
            )

            logger.warning(
                "DISASTER_STOP_FIRED",
                position_id=entry.position_id,
                symbol=entry.symbol,
                price=price,
                disaster_level=entry.disaster_level,
            )

            try:
                await self._execute_fn([disaster_order])
            except Exception:
                logger.exception(
                    "disaster_stop_execute_failed",
                    position_id=entry.position_id,
                )


def compute_disaster_level(
    entry_price: float,
    direction: Literal["long", "short"],
    daily_atr: float,
    disaster_atr_mult: float,
) -> float:
    if direction == "long":
        return entry_price - disaster_atr_mult * daily_atr
    return entry_price + disaster_atr_mult * daily_atr


class PaperDisasterStopMonitor(DisasterStopMonitor):
    def __init__(self, execute_fn: Callable[[list[Order]], Awaitable[None]]) -> None:
        super().__init__(execute_fn)
        self._last_bar_open: dict[str, float] = {}

    async def on_bar_open(self, symbol: str, open_price: float) -> None:
        self._last_bar_open[symbol] = open_price
        for entry in list(self._entries.values()):
            if entry.closed or entry.symbol != symbol:
                continue

            gap_breached = (
                open_price <= entry.disaster_level
                if entry.direction == "long"
                else open_price >= entry.disaster_level
            )

            if not gap_breached:
                continue

            entry.closed = True
            close_side = "sell" if entry.direction == "long" else "buy"
            disaster_order = Order(
                order_type="market",
                side=close_side,
                symbol=entry.symbol,
                contract_type=entry.contract_type,
                lots=entry.lots,
                price=None,
                stop_price=None,
                reason="disaster_stop",
                metadata={
                    "position_id": entry.position_id,
                    "disaster_level": entry.disaster_level,
                    "trigger_price": open_price,
                    "paper": True,
                    "gap_fill": True,
                },
                parent_position_id=entry.position_id,
                order_class="disaster_stop",
            )

            logger.warning(
                "PAPER_DISASTER_STOP_GAP_FIRED",
                position_id=entry.position_id,
                symbol=entry.symbol,
                open_price=open_price,
                disaster_level=entry.disaster_level,
            )

            try:
                await self._execute_fn([disaster_order])
            except Exception:
                logger.exception(
                    "paper_disaster_stop_gap_execute_failed",
                    position_id=entry.position_id,
                )
            finally:
                self._entries.pop(entry.position_id, None)
