"""Streaming Exponential Moving Average (EMA).

Two variants:
- EMA: classic EMA with SMA seed over the first `period` values.
- EMAStep: stateless one-shot helper matching the _ema_step pattern used
  in several strategies (seed from a provided buffer).
"""
from __future__ import annotations

from collections import deque


PARAM_SPEC: dict[str, dict] = {
    "period": {"type": "int", "default": 20, "min": 2, "max": 500, "description": "EMA lookback period."},
}


class EMA:
    """Streaming EMA with SMA-seed warmup.

    Seeded from the first ``period`` prices (SMA), then updated
    incrementally: ``EMA_t = price * k + EMA_{t-1} * (1-k)``.
    """

    __slots__ = ("_period", "_k", "_seed_buf", "_value", "_count")

    def __init__(self, period: int) -> None:
        if period < 1:
            raise ValueError(f"period must be >= 1, got {period}")
        self._period = period
        self._k = 2.0 / (period + 1)
        self._seed_buf: deque[float] = deque(maxlen=period)
        self._value: float | None = None
        self._count = 0

    def update(self, price: float) -> float | None:
        """Feed one price and return current EMA (None during warmup)."""
        self._count += 1
        if self._value is None:
            self._seed_buf.append(price)
            if len(self._seed_buf) < self._period:
                return None
            self._value = sum(self._seed_buf) / self._period
        else:
            self._value = price * self._k + self._value * (1.0 - self._k)
        return self._value

    @property
    def value(self) -> float | None:
        return self._value

    @property
    def count(self) -> int:
        """Number of prices fed so far."""
        return self._count

    @property
    def ready(self) -> bool:
        return self._value is not None

    def reset(self) -> None:
        self._seed_buf.clear()
        self._value = None
        self._count = 0


def ema_step(
    prev: float | None,
    price: float,
    period: int,
    seed_closes: list[float],
) -> float:
    """Stateless EMA step matching the pattern in ta_orb / keltner_vwap / etc.

    If ``prev`` is None and enough seed data exists, returns SMA seed.
    Otherwise returns standard EMA update.
    """
    if prev is None:
        if len(seed_closes) >= period:
            return sum(seed_closes[-period:]) / period
        return price
    k = 2.0 / (period + 1)
    return price * k + prev * (1.0 - k)
