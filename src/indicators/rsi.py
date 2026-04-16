"""Streaming Relative Strength Index (RSI).

Two variants matching existing strategy code:

- RSI: SMA-based (non-smoothed Wilder) over a rolling window.
  Matches donchian_trend_strength._update_rsi and _shared_indicators.RollingRSI.

- RSIWilder: Classic Wilder smoothed RSI using exponential running averages.
  Provided for future use; not yet used in any strategy.
"""
from __future__ import annotations

from collections import deque


PARAM_SPEC: dict[str, dict] = {
    "period": {"type": "int", "default": 14, "min": 2, "max": 30, "description": "RSI lookback period."},
}


class RSI:
    """SMA-based RSI over a rolling window of gains/losses.

    This matches the implementation in donchian_trend_strength and the
    existing _shared_indicators.RollingRSI.
    """

    __slots__ = ("_period", "_gains", "_losses", "_prev_price", "_value")

    def __init__(self, period: int = 14) -> None:
        if period < 1:
            raise ValueError(f"period must be >= 1, got {period}")
        self._period = period
        self._gains: deque[float] = deque(maxlen=period)
        self._losses: deque[float] = deque(maxlen=period)
        self._prev_price: float | None = None
        self._value: float | None = None

    def update(self, price: float) -> float | None:
        """Feed one close price, return current RSI (None during warmup)."""
        if self._prev_price is None:
            self._prev_price = price
            return None

        delta = price - self._prev_price
        self._prev_price = price
        self._gains.append(max(delta, 0.0))
        self._losses.append(max(-delta, 0.0))

        if len(self._gains) < self._period:
            return None

        avg_gain = sum(self._gains) / self._period
        avg_loss = sum(self._losses) / self._period

        if avg_loss < 1e-9:
            self._value = 100.0
        else:
            rs = avg_gain / avg_loss
            self._value = 100.0 - 100.0 / (1.0 + rs)
        return self._value

    @property
    def value(self) -> float | None:
        return self._value

    @property
    def ready(self) -> bool:
        return self._value is not None

    def reset(self) -> None:
        self._gains.clear()
        self._losses.clear()
        self._prev_price = None
        self._value = None
