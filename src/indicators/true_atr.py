"""Streaming True ATR using OHLC bars.

Unlike the proxy ATR in ``atr.py`` (which uses |close-to-close|),
this computes proper True Range = max(H-L, |H-prevC|, |L-prevC|)
and smooths with either EMA (Wilder) or SMA.
"""
from __future__ import annotations

from collections import deque


class TrueATR:
    """True Average True Range from OHLC data.

    Parameters
    ----------
    period : int
        Smoothing period. Default 14.
    smoothing : str
        ``"ema"`` for Wilder-style (default) or ``"sma"`` for simple average.
    """

    __slots__ = (
        "_period", "_use_ema", "_prev_close",
        "_tr_buf", "_value", "_count",
    )

    def __init__(self, period: int = 14, smoothing: str = "ema") -> None:
        if period < 1:
            raise ValueError(f"period must be >= 1, got {period}")
        if smoothing not in ("ema", "sma"):
            raise ValueError(f"smoothing must be 'ema' or 'sma', got {smoothing!r}")
        self._period = period
        self._use_ema = smoothing == "ema"
        self._prev_close: float | None = None
        self._tr_buf: deque[float] = deque(maxlen=period)
        self._value: float | None = None
        self._count = 0

    def update(self, high: float, low: float, close: float) -> float | None:
        """Feed one OHLC bar, return current ATR (None during warmup)."""
        if self._prev_close is None:
            # First bar: TR = high - low
            tr = high - low
        else:
            tr = max(
                high - low,
                abs(high - self._prev_close),
                abs(low - self._prev_close),
            )
        self._prev_close = close
        self._count += 1

        if self._use_ema:
            if self._value is None:
                self._tr_buf.append(tr)
                if len(self._tr_buf) < self._period:
                    return None
                self._value = sum(self._tr_buf) / self._period
            else:
                # Wilder smoothing: ATR = (prev * (n-1) + TR) / n
                self._value = (self._value * (self._period - 1) + tr) / self._period
        else:
            self._tr_buf.append(tr)
            if len(self._tr_buf) < self._period:
                return None
            self._value = sum(self._tr_buf) / self._period

        return self._value

    @property
    def value(self) -> float | None:
        return self._value

    @property
    def ready(self) -> bool:
        return self._value is not None

    def reset(self) -> None:
        self._prev_close = None
        self._tr_buf.clear()
        self._value = None
        self._count = 0
