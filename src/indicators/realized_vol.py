"""Streaming close-to-close realized volatility indicator.

Computes annualized realized volatility as the population standard deviation
of daily log-returns over a rolling window, scaled by sqrt(252).

    vol = std(log(close_t / close_{t-1})) * sqrt(252)
"""
from __future__ import annotations

import math
from collections import deque

_TRADING_DAYS_PER_YEAR = 252

PARAM_SPEC: dict[str, dict] = {
    "period": {
        "type": "int",
        "default": 10,
        "min": 5,
        "max": 60,
        "description": "Realized-volatility lookback in trading days.",
    },
}


class RealizedVol:
    """Close-to-close realized volatility, annualized.

    Computes population std of log-returns over ``period`` days and
    scales by sqrt(252) to annualize.

    Parameters
    ----------
    period : int
        Number of daily log-returns to include in the rolling window.
        Must be >= 2.
    """

    __slots__ = ("_period", "_returns", "_value")

    def __init__(self, period: int = 10) -> None:
        if period < 2:
            raise ValueError(f"period must be >= 2, got {period}")
        self._period = period
        self._returns: deque[float] = deque(maxlen=period)
        self._value: float | None = None

    def update(self, prev_close: float, curr_close: float) -> float | None:
        """Feed one daily close pair, return annualized vol (None during warmup).

        Parameters
        ----------
        prev_close : float
            Previous session close price.
        curr_close : float
            Current session close price.

        Returns
        -------
        float | None
            Annualized realized volatility, or None if fewer than ``period``
            returns have been accumulated.
        """
        if prev_close <= 0:
            return self._value
        ret = math.log(curr_close / prev_close)
        self._returns.append(ret)
        if len(self._returns) < self._period:
            return None
        mean_ret = sum(self._returns) / len(self._returns)
        var = sum((r - mean_ret) ** 2 for r in self._returns) / len(self._returns)
        self._value = math.sqrt(var * _TRADING_DAYS_PER_YEAR)
        return self._value

    @property
    def value(self) -> float | None:
        """Current annualized realized volatility, or None during warmup."""
        return self._value

    @property
    def ready(self) -> bool:
        """True once the warmup window is filled."""
        return self._value is not None

    def reset(self) -> None:
        """Clear all accumulated state for session boundary resets."""
        self._returns.clear()
        self._value = None
