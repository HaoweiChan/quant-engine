"""Streaming Schaff Trend Cycle (STC).

STC applies double stochastic smoothing to the MACD line,
producing a fast-cycling oscillator (0-100) for trend timing.

Algorithm:
1. MACD = EMA(fast) - EMA(slow)
2. %K1 = Stochastic of MACD over cycle period
3. %D1 = EMA-smooth of %K1
4. %K2 = Stochastic of %D1 over cycle period
5. STC = EMA-smooth of %K2
"""
from __future__ import annotations

from collections import deque

from src.indicators.ema import EMA


class STC:
    """Streaming Schaff Trend Cycle.

    Parameters
    ----------
    fast : int
        Fast EMA period. Default 23.
    slow : int
        Slow EMA period. Default 50.
    cycle : int
        Stochastic lookback / smoothing cycle. Default 10.
    """

    __slots__ = (
        "_fast_ema", "_slow_ema", "_cycle",
        "_macd_buf", "_d1_buf",
        "_d1", "_stc",
        "_value",
    )

    def __init__(
        self, fast: int = 23, slow: int = 50, cycle: int = 10
    ) -> None:
        if fast >= slow:
            raise ValueError(f"fast ({fast}) must be < slow ({slow})")
        if cycle < 2:
            raise ValueError(f"cycle must be >= 2, got {cycle}")
        self._fast_ema = EMA(fast)
        self._slow_ema = EMA(slow)
        self._cycle = cycle
        self._macd_buf: deque[float] = deque(maxlen=cycle)
        self._d1_buf: deque[float] = deque(maxlen=cycle)
        self._d1: float | None = None
        self._stc: float | None = None
        self._value: float | None = None

    def update(self, price: float) -> float | None:
        """Feed one price, return STC value 0-100 (None during warmup)."""
        fast_val = self._fast_ema.update(price)
        slow_val = self._slow_ema.update(price)
        if fast_val is None or slow_val is None:
            return None

        macd = fast_val - slow_val
        self._macd_buf.append(macd)
        if len(self._macd_buf) < self._cycle:
            return None

        # First stochastic pass on MACD
        hi = max(self._macd_buf)
        lo = min(self._macd_buf)
        rng = hi - lo
        k1 = ((macd - lo) / rng * 100.0) if rng > 0 else 50.0

        # EMA-smooth %K1 → %D1
        factor = 2.0 / (self._cycle + 1)
        if self._d1 is None:
            self._d1 = k1
        else:
            self._d1 = k1 * factor + self._d1 * (1.0 - factor)

        self._d1_buf.append(self._d1)
        if len(self._d1_buf) < self._cycle:
            return None

        # Second stochastic pass on %D1
        hi2 = max(self._d1_buf)
        lo2 = min(self._d1_buf)
        rng2 = hi2 - lo2
        k2 = ((self._d1 - lo2) / rng2 * 100.0) if rng2 > 0 else 50.0

        # EMA-smooth %K2 → STC
        if self._stc is None:
            self._stc = k2
        else:
            self._stc = k2 * factor + self._stc * (1.0 - factor)

        self._value = max(0.0, min(100.0, self._stc))
        return self._value

    @property
    def value(self) -> float | None:
        return self._value

    @property
    def ready(self) -> bool:
        return self._value is not None

    def reset(self) -> None:
        self._fast_ema.reset()
        self._slow_ema.reset()
        self._macd_buf.clear()
        self._d1_buf.clear()
        self._d1 = None
        self._stc = None
        self._value = None
