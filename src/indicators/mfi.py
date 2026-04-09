"""Streaming Money Flow Index (MFI).

Volume-weighted RSI. Uses typical price and volume to compute
buying/selling pressure on a 0-100 scale.

Typical Price = (high + low + close) / 3
Money Flow = Typical Price * Volume
Positive MF: when TP > prev TP
Negative MF: when TP < prev TP
MFI = 100 - 100 / (1 + Positive MF sum / Negative MF sum)
"""
from __future__ import annotations

from collections import deque


class MFI:
    """Streaming Money Flow Index.

    Parameters
    ----------
    period : int
        Rolling window. Default 14.
    """

    __slots__ = ("_period", "_prev_tp", "_pos_mf", "_neg_mf", "_value")

    def __init__(self, period: int = 14) -> None:
        if period < 1:
            raise ValueError(f"period must be >= 1, got {period}")
        self._period = period
        self._prev_tp: float | None = None
        self._pos_mf: deque[float] = deque(maxlen=period)
        self._neg_mf: deque[float] = deque(maxlen=period)
        self._value: float | None = None

    def update(
        self, high: float, low: float, close: float, volume: float
    ) -> float | None:
        """Feed one OHLCV bar, return MFI 0-100 (None during warmup)."""
        tp = (high + low + close) / 3.0
        raw_mf = tp * volume

        if self._prev_tp is None:
            self._prev_tp = tp
            return None

        if tp > self._prev_tp:
            self._pos_mf.append(raw_mf)
            self._neg_mf.append(0.0)
        elif tp < self._prev_tp:
            self._pos_mf.append(0.0)
            self._neg_mf.append(raw_mf)
        else:
            self._pos_mf.append(0.0)
            self._neg_mf.append(0.0)

        self._prev_tp = tp

        if len(self._pos_mf) < self._period:
            return None

        pos_sum = sum(self._pos_mf)
        neg_sum = sum(self._neg_mf)

        if neg_sum == 0:
            self._value = 100.0
        else:
            ratio = pos_sum / neg_sum
            self._value = 100.0 - 100.0 / (1.0 + ratio)
        return self._value

    @property
    def value(self) -> float | None:
        return self._value

    @property
    def ready(self) -> bool:
        return self._value is not None

    def reset(self) -> None:
        self._prev_tp = None
        self._pos_mf.clear()
        self._neg_mf.clear()
        self._value = None
