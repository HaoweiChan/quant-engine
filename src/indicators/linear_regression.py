"""Streaming Linear Regression (slope, R-squared, forecast).

Rolling OLS on close prices over a fixed window.
- slope: trend direction and speed
- r_squared: trend quality (1 = perfect line, 0 = no relationship)
- forecast: extrapolated next value on the regression line
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass


@dataclass(frozen=True)
class LinRegResult:
    """Linear regression output."""

    slope: float       # price change per bar
    intercept: float   # y-intercept (at start of window)
    r_squared: float   # coefficient of determination (0-1)
    forecast: float    # predicted next value


class LinearRegression:
    """Streaming linear regression over a rolling window.

    Parameters
    ----------
    period : int
        Window size. Default 20.
    """

    __slots__ = ("_period", "_buf", "_value")

    def __init__(self, period: int = 20) -> None:
        if period < 2:
            raise ValueError(f"period must be >= 2, got {period}")
        self._period = period
        self._buf: deque[float] = deque(maxlen=period)
        self._value: LinRegResult | None = None

    def update(self, price: float) -> LinRegResult | None:
        """Feed one price, return LinRegResult (None during warmup)."""
        self._buf.append(price)
        if len(self._buf) < self._period:
            return None

        n = self._period
        # x = 0, 1, ..., n-1
        # Pre-computed sums for x = 0..n-1:
        #   sum_x = n*(n-1)/2, sum_x2 = n*(n-1)*(2n-1)/6
        sum_x = n * (n - 1) / 2.0
        sum_x2 = n * (n - 1) * (2 * n - 1) / 6.0

        sum_y = 0.0
        sum_xy = 0.0
        sum_y2 = 0.0
        for i, y in enumerate(self._buf):
            sum_y += y
            sum_xy += i * y
            sum_y2 += y * y

        denom = n * sum_x2 - sum_x * sum_x
        if denom == 0:
            return None

        slope = (n * sum_xy - sum_x * sum_y) / denom
        intercept = (sum_y - slope * sum_x) / n

        # R-squared
        ss_tot = sum_y2 - sum_y * sum_y / n
        if ss_tot == 0:
            r_squared = 1.0  # all values identical → perfect fit
        else:
            ss_res = 0.0
            for i, y in enumerate(self._buf):
                pred = intercept + slope * i
                ss_res += (y - pred) ** 2
            r_squared = 1.0 - ss_res / ss_tot

        forecast = intercept + slope * n  # next bar prediction

        self._value = LinRegResult(
            slope=slope,
            intercept=intercept,
            r_squared=r_squared,
            forecast=forecast,
        )
        return self._value

    @property
    def value(self) -> LinRegResult | None:
        return self._value

    @property
    def ready(self) -> bool:
        return self._value is not None

    def reset(self) -> None:
        self._buf.clear()
        self._value = None
