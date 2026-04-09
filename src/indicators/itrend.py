"""Streaming Ehlers Instantaneous Trendline (iTrend).

Near-zero-lag trend indicator that removes the dominant cycle
from price data. Based on John Ehlers' 2-pole smoothing filter.

The iTrend value tracks the trend component of price with
significantly less lag than a comparable EMA.
"""
from __future__ import annotations


class ITrend:
    """Streaming Ehlers Instantaneous Trendline.

    Uses a 2-pole super-smoother filter variation.
    Produces a trend line with near-zero lag.
    """

    __slots__ = (
        "_prices", "_values", "_count", "_value",
    )

    def __init__(self) -> None:
        self._prices: list[float] = []  # last 4 prices
        self._values: list[float] = []  # last 3 iTrend values
        self._count: int = 0
        self._value: float | None = None

    def update(self, price: float) -> float | None:
        """Feed one price, return iTrend value (None during first 6 bars)."""
        self._count += 1
        self._prices.append(price)
        if len(self._prices) > 4:
            self._prices.pop(0)

        if self._count < 7:
            # Warmup: use simple average
            self._values.append(price)
            if len(self._values) > 3:
                self._values.pop(0)
            if self._count >= 4:
                self._value = (price + 2.0 * self._prices[-2] + self._prices[-3]) / 4.0
            return self._value

        # Ehlers iTrend formula:
        # iTrend = (a - a²/4) * price
        #        + (a²/2) * price[1]
        #        - (a - 3a²/4) * price[2]
        #        + 2(1-a) * iTrend[1]
        #        - (1-a)² * iTrend[2]
        # where a = 2/(period+1), typically a ≈ 0.07 for period=27
        # Simplified Ehlers uses fixed coefficients:
        a = 0.07

        p0 = self._prices[-1]
        p1 = self._prices[-2] if len(self._prices) >= 2 else p0
        p2 = self._prices[-3] if len(self._prices) >= 3 else p1

        v1 = self._values[-1] if len(self._values) >= 1 else p0
        v2 = self._values[-2] if len(self._values) >= 2 else v1

        it = (
            (a - a * a / 4.0) * p0
            + (a * a / 2.0) * p1
            - (a - 3.0 * a * a / 4.0) * p2
            + 2.0 * (1.0 - a) * v1
            - (1.0 - a) ** 2 * v2
        )

        self._values.append(it)
        if len(self._values) > 3:
            self._values.pop(0)

        self._value = it
        return self._value

    @property
    def value(self) -> float | None:
        return self._value

    @property
    def ready(self) -> bool:
        return self._value is not None

    def reset(self) -> None:
        self._prices.clear()
        self._values.clear()
        self._count = 0
        self._value = None
