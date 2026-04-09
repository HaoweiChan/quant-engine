"""Streaming Fisher Transform.

Normalizes price to a near-Gaussian distribution, making
extreme values sharper and easier to detect for crossover signals.

Algorithm:
1. Normalize price within rolling high-low range to [-1, +1]
2. Apply inverse hyperbolic tangent: Fisher = 0.5 * ln((1+x)/(1-x))
3. Signal = previous Fisher value (for crossover detection)
"""
from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass


@dataclass(frozen=True)
class FisherResult:
    """Fisher Transform output."""

    fisher: float    # current Fisher Transform value
    signal: float    # previous Fisher value (trigger line)


class FisherTransform:
    """Streaming Fisher Transform.

    Parameters
    ----------
    period : int
        Lookback for high-low normalization range. Default 10.
    """

    __slots__ = ("_period", "_highs", "_lows", "_prev_norm", "_prev_fisher", "_value")

    def __init__(self, period: int = 10) -> None:
        if period < 2:
            raise ValueError(f"period must be >= 2, got {period}")
        self._period = period
        self._highs: deque[float] = deque(maxlen=period)
        self._lows: deque[float] = deque(maxlen=period)
        self._prev_norm: float = 0.0
        self._prev_fisher: float = 0.0
        self._value: FisherResult | None = None

    def update(self, high: float, low: float, close: float) -> FisherResult | None:
        """Feed one bar, return FisherResult (None during warmup)."""
        mid = (high + low) / 2.0
        self._highs.append(high)
        self._lows.append(low)

        if len(self._highs) < self._period:
            return None

        highest = max(self._highs)
        lowest = min(self._lows)
        rng = highest - lowest

        if rng == 0:
            norm = 0.0
        else:
            # Normalize to [-1, +1] range
            raw = 2.0 * ((mid - lowest) / rng) - 1.0
            # EMA-smooth the normalization
            norm = 0.33 * raw + 0.67 * self._prev_norm
            # Clamp to avoid atanh singularity
            norm = max(-0.999, min(0.999, norm))

        signal = self._prev_fisher
        fisher = 0.5 * math.log((1.0 + norm) / (1.0 - norm))

        self._prev_norm = norm
        self._prev_fisher = fisher

        self._value = FisherResult(fisher=fisher, signal=signal)
        return self._value

    @property
    def value(self) -> FisherResult | None:
        return self._value

    @property
    def ready(self) -> bool:
        return self._value is not None

    def reset(self) -> None:
        self._highs.clear()
        self._lows.clear()
        self._prev_norm = 0.0
        self._prev_fisher = 0.0
        self._value = None
