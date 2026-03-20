"""Example stop policy: Chandelier trailing stop using ATR.

Customize this file to change HOW stop-loss levels are set and trailed.
The engine calls `initial_stop()` when opening a position and
`update_stop()` on every subsequent bar.
"""
from collections import deque

from src.core.policies import StopPolicy
from src.core.types import MarketSnapshot, Position, PyramidConfig


class MyStopPolicy(StopPolicy):
    """Chandelier stop: trail at N * ATR below the highest high."""

    def __init__(self, config: PyramidConfig) -> None:
        self._config = config

    def initial_stop(
        self, entry_price: float, direction: str, snapshot: MarketSnapshot,
    ) -> float:
        daily_atr = snapshot.atr["daily"]
        distance = self._config.stop_atr_mult * daily_atr
        if direction == "short":
            return entry_price + distance
        return entry_price - distance

    def update_stop(
        self,
        position: Position,
        snapshot: MarketSnapshot,
        high_history: deque[float],
    ) -> float:
        daily_atr = snapshot.atr["daily"]
        new_stop = position.stop_level

        if position.direction == "long":
            # Move to breakeven once profit exceeds 1 ATR
            floating_profit = snapshot.price - position.entry_price
            if floating_profit > daily_atr and position.stop_level < position.entry_price:
                new_stop = position.entry_price
            # Chandelier trail: highest high minus trail_atr_mult * ATR
            if high_history:
                chandelier = max(high_history) - self._config.trail_atr_mult * daily_atr
                new_stop = max(new_stop, chandelier)
        else:
            floating_profit = position.entry_price - snapshot.price
            if floating_profit > daily_atr and position.stop_level > position.entry_price:
                new_stop = position.entry_price
            if high_history:
                chandelier = min(high_history) + self._config.trail_atr_mult * daily_atr
                new_stop = min(new_stop, chandelier)

        return new_stop
