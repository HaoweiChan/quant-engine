"""Streaming On-Balance Volume (OBV).

Cumulative volume indicator: adds volume on up-closes,
subtracts on down-closes. No warmup period.
"""
from __future__ import annotations


class OBV:
    """Streaming OBV — ready from the second bar onward."""

    __slots__ = ("_obv", "_prev_close", "_ready")

    def __init__(self) -> None:
        self._obv: float = 0.0
        self._prev_close: float | None = None
        self._ready: bool = False

    def update(self, close: float, volume: float) -> float | None:
        """Feed one bar's close and volume, return current OBV.

        Returns None on the first bar (no prior close to compare).
        """
        if self._prev_close is None:
            self._prev_close = close
            return None
        if close > self._prev_close:
            self._obv += volume
        elif close < self._prev_close:
            self._obv -= volume
        # equal → OBV unchanged
        self._prev_close = close
        self._ready = True
        return self._obv

    @property
    def value(self) -> float | None:
        return self._obv if self._ready else None

    @property
    def ready(self) -> bool:
        return self._ready

    def reset(self) -> None:
        self._obv = 0.0
        self._prev_close = None
        self._ready = False
