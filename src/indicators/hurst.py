"""Streaming Hurst Exponent via Rescaled Range (R/S) analysis.

H > 0.5 → trending (persistent)
H = 0.5 → random walk
H < 0.5 → mean-reverting (anti-persistent)

Computationally expensive — best used on longer timeframes (daily, 4h)
or with a recalculation interval (not every bar).
"""
from __future__ import annotations

import math
from collections import deque


class HurstExponent:
    """Streaming Hurst Exponent via R/S analysis.

    Parameters
    ----------
    period : int
        Rolling window of prices for R/S calculation. Default 100.
    min_sub_period : int
        Minimum sub-sample size for R/S regression. Default 10.
    """

    __slots__ = ("_period", "_min_sub", "_buf", "_value")

    def __init__(self, period: int = 100, min_sub_period: int = 10) -> None:
        if period < 20:
            raise ValueError(f"period must be >= 20, got {period}")
        if min_sub_period < 2:
            raise ValueError(f"min_sub_period must be >= 2, got {min_sub_period}")
        self._period = period
        self._min_sub = min_sub_period
        self._buf: deque[float] = deque(maxlen=period)
        self._value: float | None = None

    def update(self, price: float) -> float | None:
        """Feed one price, return Hurst exponent (None during warmup)."""
        self._buf.append(price)
        if len(self._buf) < self._period:
            return None

        prices = list(self._buf)
        # Convert to log returns
        returns = [
            math.log(prices[i] / prices[i - 1])
            for i in range(1, len(prices))
            if prices[i - 1] > 0 and prices[i] > 0
        ]
        if len(returns) < self._min_sub:
            return None

        self._value = _compute_hurst(returns, self._min_sub)
        return self._value

    @property
    def value(self) -> float | None:
        return self._value

    @property
    def ready(self) -> bool:
        return self._value is not None

    def reset(self) -> None:
        self._buf.clear()
        self._value = None


def _compute_hurst(returns: list[float], min_sub: int) -> float:
    """Compute Hurst exponent from log returns using R/S analysis."""
    n = len(returns)
    # Generate sub-sample sizes (powers of 2 that fit)
    sizes: list[int] = []
    s = min_sub
    while s <= n // 2:
        sizes.append(s)
        s *= 2
    if not sizes:
        sizes = [n]

    log_sizes: list[float] = []
    log_rs: list[float] = []

    for size in sizes:
        n_chunks = n // size
        if n_chunks < 1:
            continue

        rs_values: list[float] = []
        for chunk_i in range(n_chunks):
            chunk = returns[chunk_i * size : (chunk_i + 1) * size]

            # Mean of chunk
            mean_c = sum(chunk) / len(chunk)

            # Cumulative deviation from mean
            cum_dev = []
            running = 0.0
            for x in chunk:
                running += x - mean_c
                cum_dev.append(running)

            # Range
            r = max(cum_dev) - min(cum_dev)

            # Standard deviation
            var = sum((x - mean_c) ** 2 for x in chunk) / len(chunk)
            s_dev = math.sqrt(var) if var > 0 else 0.0

            if s_dev > 0:
                rs_values.append(r / s_dev)

        if rs_values:
            avg_rs = sum(rs_values) / len(rs_values)
            if avg_rs > 0:
                log_sizes.append(math.log(size))
                log_rs.append(math.log(avg_rs))

    if len(log_sizes) < 2:
        return 0.5  # insufficient data, assume random walk

    # Linear regression: log(R/S) = H * log(n) + c
    n_pts = len(log_sizes)
    sum_x = sum(log_sizes)
    sum_y = sum(log_rs)
    sum_xy = sum(x * y for x, y in zip(log_sizes, log_rs))
    sum_x2 = sum(x * x for x in log_sizes)

    denom = n_pts * sum_x2 - sum_x * sum_x
    if denom == 0:
        return 0.5

    hurst = (n_pts * sum_xy - sum_x * sum_y) / denom
    # Clamp to valid range
    return max(0.0, min(1.0, hurst))
