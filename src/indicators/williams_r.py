"""Streaming Williams %R.

Inverted stochastic oscillator ranging from -100 (oversold) to 0 (overbought).
%R = (highest_high - close) / (highest_high - lowest_low) * -100
"""
from __future__ import annotations

from collections import deque


class WilliamsR:
    """Streaming Williams %R.

    Parameters
    ----------
    period : int
        Lookback for highest high / lowest low. Default 14.
    """

    __slots__ = ("_period", "_highs", "_lows", "_value")

    def __init__(self, period: int = 14) -> None:
        if period < 1:
            raise ValueError(f"period must be >= 1, got {period}")
        self._period = period
        self._highs: deque[float] = deque(maxlen=period)
        self._lows: deque[float] = deque(maxlen=period)
        self._value: float | None = None

    def update(self, high: float, low: float, close: float) -> float | None:
        """Feed one bar (high, low, close), return %R (None during warmup)."""
        self._highs.append(high)
        self._lows.append(low)

        if len(self._highs) < self._period:
            return None

        highest = max(self._highs)
        lowest = min(self._lows)
        rng = highest - lowest

        if rng == 0:
            self._value = -50.0  # midpoint when flat
        else:
            self._value = (highest - close) / rng * -100.0
        return self._value

    @property
    def value(self) -> float | None:
        return self._value

    @property
    def ready(self) -> bool:
        return self._value is not None

    def reset(self) -> None:
        self._highs.clear()
        self._lows.clear()
        self._value = None
