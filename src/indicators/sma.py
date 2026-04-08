"""Streaming Simple Moving Average (SMA).

Matches _shared_indicators.RollingMA.
"""
from __future__ import annotations

from collections import deque
from statistics import mean


class SMA:
    """Rolling SMA over a fixed window of close prices."""

    __slots__ = ("_period", "_buf", "_value")

    def __init__(self, period: int) -> None:
        if period < 1:
            raise ValueError(f"period must be >= 1, got {period}")
        self._period = period
        self._buf: deque[float] = deque(maxlen=period)
        self._value: float | None = None

    def update(self, price: float) -> float | None:
        """Feed one price, return SMA (None during warmup)."""
        self._buf.append(price)
        if len(self._buf) < self._period:
            return None
        self._value = mean(self._buf)
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
