"""Streaming Stochastic Oscillator (%K / %D).

%K = (close - lowest_low) / (highest_high - lowest_low) * 100
%D = SMA(%K, d_period)

Supports both Fast Stochastic (raw %K) and Slow Stochastic
(smoothed %K via ``smooth`` parameter).
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass


@dataclass(frozen=True)
class StochasticResult:
    """Stochastic oscillator output."""

    k: float   # %K line (0-100)
    d: float   # %D line (0-100)


PARAM_SPEC: dict[str, dict] = {
    "k_period": {"type": "int", "default": 14, "min": 5, "max": 30, "description": "Stochastic %K lookback."},
    "d_period": {"type": "int", "default": 3, "min": 2, "max": 10, "description": "Stochastic %D SMA period."},
    "smooth": {"type": "int", "default": 3, "min": 1, "max": 10, "description": "Slow stochastic %K smoothing."},
}


class Stochastic:
    """Streaming Stochastic Oscillator.

    Parameters
    ----------
    k_period : int
        Lookback for highest high / lowest low. Default 14.
    d_period : int
        SMA period for %D line. Default 3.
    smooth : int
        SMA smoothing applied to raw %K (1 = fast stochastic). Default 3.
    """

    __slots__ = (
        "_k_period", "_d_period", "_smooth",
        "_highs", "_lows",
        "_raw_k_buf", "_smooth_k_buf",
        "_value",
    )

    def __init__(
        self, k_period: int = 14, d_period: int = 3, smooth: int = 3
    ) -> None:
        if k_period < 1:
            raise ValueError(f"k_period must be >= 1, got {k_period}")
        if d_period < 1:
            raise ValueError(f"d_period must be >= 1, got {d_period}")
        if smooth < 1:
            raise ValueError(f"smooth must be >= 1, got {smooth}")
        self._k_period = k_period
        self._d_period = d_period
        self._smooth = smooth
        self._highs: deque[float] = deque(maxlen=k_period)
        self._lows: deque[float] = deque(maxlen=k_period)
        self._raw_k_buf: deque[float] = deque(maxlen=smooth)
        self._smooth_k_buf: deque[float] = deque(maxlen=d_period)
        self._value: StochasticResult | None = None

    def update(self, high: float, low: float, close: float) -> StochasticResult | None:
        """Feed one bar (high, low, close), return result (None during warmup)."""
        self._highs.append(high)
        self._lows.append(low)

        if len(self._highs) < self._k_period:
            return None

        highest = max(self._highs)
        lowest = min(self._lows)
        rng = highest - lowest
        raw_k = ((close - lowest) / rng * 100.0) if rng > 0 else 50.0

        # Smooth %K
        self._raw_k_buf.append(raw_k)
        if len(self._raw_k_buf) < self._smooth:
            return None
        k = sum(self._raw_k_buf) / self._smooth

        # %D = SMA of smoothed %K
        self._smooth_k_buf.append(k)
        if len(self._smooth_k_buf) < self._d_period:
            return None
        d = sum(self._smooth_k_buf) / self._d_period

        self._value = StochasticResult(k=k, d=d)
        return self._value

    @property
    def value(self) -> StochasticResult | None:
        return self._value

    @property
    def ready(self) -> bool:
        return self._value is not None

    def reset(self) -> None:
        self._highs.clear()
        self._lows.clear()
        self._raw_k_buf.clear()
        self._smooth_k_buf.clear()
        self._value = None
