"""Streaming Parabolic SAR (Stop and Reverse).

Classic Wilder trailing stop that accelerates as the trend extends.

- In an uptrend, SAR is below price and rises toward it.
- In a downtrend, SAR is above price and falls toward it.
- When price crosses SAR, the trend reverses.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PSARResult:
    """Parabolic SAR output."""

    sar: float     # current SAR level
    trend: int     # +1 uptrend, -1 downtrend
    af: float      # current acceleration factor


class ParabolicSAR:
    """Streaming Parabolic SAR.

    Parameters
    ----------
    af_start : float
        Initial acceleration factor. Default 0.02.
    af_step : float
        AF increment on each new extreme. Default 0.02.
    af_max : float
        Maximum acceleration factor. Default 0.2.
    """

    __slots__ = (
        "_af_start", "_af_step", "_af_max",
        "_trend", "_sar", "_ep", "_af",
        "_prev_high", "_prev_low",
        "_count", "_value",
    )

    def __init__(
        self,
        af_start: float = 0.02,
        af_step: float = 0.02,
        af_max: float = 0.2,
    ) -> None:
        if af_start <= 0 or af_max <= 0 or af_step <= 0:
            raise ValueError("af_start, af_step, af_max must be > 0")
        if af_start > af_max:
            raise ValueError(f"af_start ({af_start}) must be <= af_max ({af_max})")
        self._af_start = af_start
        self._af_step = af_step
        self._af_max = af_max
        self._trend: int = 1
        self._sar: float = 0.0
        self._ep: float = 0.0   # extreme point
        self._af: float = af_start
        self._prev_high: float = 0.0
        self._prev_low: float = 0.0
        self._count: int = 0
        self._value: PSARResult | None = None

    def update(self, high: float, low: float, close: float) -> PSARResult | None:
        """Feed one bar (high, low, close), return PSARResult.

        Returns None for the first bar (needs at least 2 bars).
        """
        self._count += 1

        if self._count == 1:
            # Initialize with first bar
            self._prev_high = high
            self._prev_low = low
            return None

        if self._count == 2:
            # Initialize trend from first two bars
            if close >= self._prev_high:
                self._trend = 1
                self._sar = self._prev_low
                self._ep = high
            else:
                self._trend = -1
                self._sar = self._prev_high
                self._ep = low
            self._af = self._af_start
        else:
            # Update SAR
            self._sar = self._sar + self._af * (self._ep - self._sar)

            if self._trend == 1:
                # In uptrend, SAR cannot be above prior two lows
                self._sar = min(self._sar, self._prev_low)

                if low < self._sar:
                    # Reverse to downtrend
                    self._trend = -1
                    self._sar = self._ep
                    self._ep = low
                    self._af = self._af_start
                else:
                    if high > self._ep:
                        self._ep = high
                        self._af = min(self._af + self._af_step, self._af_max)
            else:
                # In downtrend, SAR cannot be below prior two highs
                self._sar = max(self._sar, self._prev_high)

                if high > self._sar:
                    # Reverse to uptrend
                    self._trend = 1
                    self._sar = self._ep
                    self._ep = high
                    self._af = self._af_start
                else:
                    if low < self._ep:
                        self._ep = low
                        self._af = min(self._af + self._af_step, self._af_max)

        self._prev_high = high
        self._prev_low = low

        self._value = PSARResult(sar=self._sar, trend=self._trend, af=self._af)
        return self._value

    @property
    def value(self) -> PSARResult | None:
        return self._value

    @property
    def ready(self) -> bool:
        return self._value is not None

    def reset(self) -> None:
        self._trend = 1
        self._sar = 0.0
        self._ep = 0.0
        self._af = self._af_start
        self._prev_high = 0.0
        self._prev_low = 0.0
        self._count = 0
        self._value = None
