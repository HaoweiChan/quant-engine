"""Streaming Chaikin Money Flow (CMF).

CMF = sum(Money Flow Volume, n) / sum(Volume, n)

Where Money Flow Volume = Money Flow Multiplier * Volume
      Money Flow Multiplier = ((close - low) - (high - close)) / (high - low)

Oscillates between -1 and +1.
"""
from __future__ import annotations

from collections import deque


class CMF:
    """Streaming Chaikin Money Flow.

    Parameters
    ----------
    period : int
        Rolling window. Default 20.
    """

    __slots__ = ("_period", "_mfv_buf", "_vol_buf", "_value")

    def __init__(self, period: int = 20) -> None:
        if period < 1:
            raise ValueError(f"period must be >= 1, got {period}")
        self._period = period
        self._mfv_buf: deque[float] = deque(maxlen=period)
        self._vol_buf: deque[float] = deque(maxlen=period)
        self._value: float | None = None

    def update(
        self, high: float, low: float, close: float, volume: float
    ) -> float | None:
        """Feed one OHLCV bar, return CMF (None during warmup)."""
        rng = high - low
        if rng > 0:
            mfm = ((close - low) - (high - close)) / rng
        else:
            mfm = 0.0
        mfv = mfm * volume

        self._mfv_buf.append(mfv)
        self._vol_buf.append(volume)

        if len(self._mfv_buf) < self._period:
            return None

        total_vol = sum(self._vol_buf)
        if total_vol == 0:
            self._value = 0.0
        else:
            self._value = sum(self._mfv_buf) / total_vol
        return self._value

    @property
    def value(self) -> float | None:
        return self._value

    @property
    def ready(self) -> bool:
        return self._value is not None

    def reset(self) -> None:
        self._mfv_buf.clear()
        self._vol_buf.clear()
        self._value = None
