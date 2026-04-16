"""Streaming Donchian Channel.

Matches donchian_trend_strength._compute_donchian: rolling highest-high
and lowest-low over a lookback window of close prices.
"""
from __future__ import annotations

from collections import deque


PARAM_SPEC: dict[str, dict] = {
    "period": {"type": "int", "default": 20, "min": 5, "max": 100, "description": "Donchian channel lookback period."},
}


class Donchian:
    """Rolling Donchian Channel on close prices.

    Attributes (None until warmup completes):
        upper: highest close in window
        lower: lowest close in window
        mid: (upper + lower) / 2
        width: upper - lower
    """

    __slots__ = ("_period", "_buf", "upper", "lower", "mid", "width")

    def __init__(self, period: int = 20) -> None:
        if period < 1:
            raise ValueError(f"period must be >= 1, got {period}")
        self._period = period
        self._buf: deque[float] = deque(maxlen=period)
        self.upper: float | None = None
        self.lower: float | None = None
        self.mid: float | None = None
        self.width: float | None = None

    def update(self, price: float) -> bool:
        """Feed one close price. Returns True when channel is ready."""
        self._buf.append(price)
        if len(self._buf) < self._period:
            return False
        self.upper = max(self._buf)
        self.lower = min(self._buf)
        self.mid = (self.upper + self.lower) / 2.0
        self.width = self.upper - self.lower
        return True

    @property
    def ready(self) -> bool:
        return self.upper is not None

    def reset(self) -> None:
        self._buf.clear()
        self.upper = None
        self.lower = None
        self.mid = None
        self.width = None
