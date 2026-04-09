"""Streaming Rate of Change (ROC).

ROC = (price - price_n_ago) / price_n_ago * 100
"""
from __future__ import annotations

from collections import deque


class ROC:
    """Streaming ROC over a fixed lookback.

    Parameters
    ----------
    period : int
        Number of bars to look back. Default 12.
    """

    __slots__ = ("_period", "_buf", "_value")

    def __init__(self, period: int = 12) -> None:
        if period < 1:
            raise ValueError(f"period must be >= 1, got {period}")
        self._period = period
        self._buf: deque[float] = deque(maxlen=period + 1)
        self._value: float | None = None

    def update(self, price: float) -> float | None:
        """Feed one price, return ROC % (None during warmup)."""
        self._buf.append(price)
        if len(self._buf) <= self._period:
            return None
        old = self._buf[0]
        if old == 0.0:
            self._value = 0.0
        else:
            self._value = (price - old) / old * 100.0
        return self._value

    @property
    def value(self) -> float | None:
        return self._value

    @property
    def ready(self) -> bool:
        return self._value is not None

    def reset(self) -> None:
        self._buf.clear()
        self._value = None
