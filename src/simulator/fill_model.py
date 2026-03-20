"""Fill model abstraction for backtest order simulation."""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

from src.core.types import Order
from src.simulator.types import Fill


class FillModel(ABC):
    @abstractmethod
    def simulate(self, order: Order, bar: dict[str, float], timestamp: datetime) -> Fill: ...


class ClosePriceFillModel(FillModel):
    def __init__(self, slippage_points: float = 0.0) -> None:
        self._slippage = slippage_points

    def simulate(self, order: Order, bar: dict[str, float], timestamp: datetime) -> Fill:
        close = bar["close"]
        slip = self._slippage if order.side == "buy" else -self._slippage
        return Fill(
            order_type=order.order_type,
            side=order.side,
            symbol=order.symbol,
            lots=order.lots,
            fill_price=close + slip,
            slippage=self._slippage,
            timestamp=timestamp,
            reason=order.reason,
        )


class OpenPriceFillModel(FillModel):
    def __init__(self, slippage_points: float = 0.0) -> None:
        self._slippage = slippage_points

    def simulate(self, order: Order, bar: dict[str, float], timestamp: datetime) -> Fill:
        open_price = bar["open"]
        slip = self._slippage if order.side == "buy" else -self._slippage
        return Fill(
            order_type=order.order_type,
            side=order.side,
            symbol=order.symbol,
            lots=order.lots,
            fill_price=open_price + slip,
            slippage=self._slippage,
            timestamp=timestamp,
            reason=order.reason,
        )
