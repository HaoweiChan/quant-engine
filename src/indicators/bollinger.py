"""Streaming Bollinger Bands.

Matches the implementations in volatility_squeeze._compute_signal and
bollinger_pinbar._compute. Supports asymmetric multipliers (different
upper/lower widths) as used in bb_mean_reversion.
"""
from __future__ import annotations

from collections import deque
from math import sqrt
from statistics import mean


def _stdev(vals: list[float], avg: float) -> float:
    """Population standard deviation (matches strategy _stdev helpers)."""
    if len(vals) < 2:
        return 0.0
    variance = sum((v - avg) ** 2 for v in vals) / len(vals)
    return sqrt(variance)


PARAM_SPEC: dict[str, dict] = {
    "period": {"type": "int", "default": 20, "min": 5, "max": 60, "description": "Bollinger SMA lookback period."},
    "upper_mult": {"type": "float", "default": 2.0, "min": 0.5, "max": 4.0, "description": "Upper band std-dev multiplier."},
    "lower_mult": {"type": "float", "default": 2.0, "min": 0.5, "max": 4.0, "description": "Lower band std-dev multiplier."},
}


class BollingerBands:
    """Rolling Bollinger Bands on close prices.

    Parameters
    ----------
    period : int
        SMA lookback period.
    upper_mult : float
        Standard deviation multiplier for upper band.
    lower_mult : float
        Standard deviation multiplier for lower band.
        Defaults to same as upper_mult for symmetric bands.

    Attributes (None until warmup completes):
        mid: SMA(period)
        upper: mid + upper_mult * stdev
        lower: mid - lower_mult * stdev
    """

    __slots__ = (
        "_period", "_upper_mult", "_lower_mult", "_buf",
        "mid", "upper", "lower",
    )

    def __init__(
        self,
        period: int = 20,
        upper_mult: float = 2.0,
        lower_mult: float | None = None,
    ) -> None:
        if period < 1:
            raise ValueError(f"period must be >= 1, got {period}")
        self._period = period
        self._upper_mult = upper_mult
        self._lower_mult = lower_mult if lower_mult is not None else upper_mult
        self._buf: deque[float] = deque(maxlen=period)
        self.mid: float | None = None
        self.upper: float | None = None
        self.lower: float | None = None

    def update(self, price: float) -> bool:
        """Feed one close price. Returns True when bands are ready."""
        self._buf.append(price)
        if len(self._buf) < self._period:
            return False
        window = list(self._buf)
        self.mid = mean(window)
        sd = _stdev(window, self.mid)
        self.upper = self.mid + self._upper_mult * sd
        self.lower = self.mid - self._lower_mult * sd
        return True

    @property
    def ready(self) -> bool:
        return self.mid is not None

    def reset(self) -> None:
        self._buf.clear()
        self.mid = None
        self.upper = None
        self.lower = None
