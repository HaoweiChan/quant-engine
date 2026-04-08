"""Streaming ATR (Average True Range) variants.

All operate on close-to-close |delta| since MarketSnapshot doesn't
expose high/low. This matches the proxy used across all strategies.

Classes:
- ATR: SMA-based rolling ATR (matches _shared_indicators.RollingATR and
  _compute_entry_atr in volatility_squeeze / bb_mean_reversion).
- SmoothedATR: Rolling average of raw ATR values, used by pyramid_wrapper
  and enhanced_bnh for sizing.
- ATRPercentile: Tracks where current ATR sits relative to recent history.
  Matches volatility_squeeze._update_atr_percentile.
"""
from __future__ import annotations

from collections import deque
from statistics import mean


class ATR:
    """SMA-based ATR over close-to-close absolute changes.

    Parameters
    ----------
    period : int
        Number of |delta| values to average.
    scale : float
        Multiplier applied to the raw ATR. Some strategies use sqrt(2)
        or similar scaling. Default 1.0.
    """

    __slots__ = ("_period", "_scale", "_closes", "_value")

    def __init__(self, period: int = 14, scale: float = 1.0) -> None:
        if period < 1:
            raise ValueError(f"period must be >= 1, got {period}")
        self._period = period
        self._scale = scale
        self._closes: deque[float] = deque(maxlen=period + 1)
        self._value: float | None = None

    def update(self, price: float) -> float | None:
        """Feed one close price, return scaled ATR (None during warmup)."""
        self._closes.append(price)
        closes = list(self._closes)
        if len(closes) < self._period + 1:
            return None
        tr_vals = [
            abs(closes[i] - closes[i - 1])
            for i in range(len(closes) - self._period, len(closes))
        ]
        self._value = mean(tr_vals) * self._scale
        return self._value

    @property
    def value(self) -> float | None:
        return self._value

    @property
    def ready(self) -> bool:
        return self._value is not None

    def reset(self) -> None:
        self._closes.clear()
        self._value = None


class SmoothedATR:
    """Rolling average of externally-provided ATR values.

    Used by pyramid_wrapper and enhanced_bnh to smooth raw daily ATR
    before using it for position sizing.

    Parameters
    ----------
    period : int
        Number of raw ATR values to average.
    """

    __slots__ = ("_period", "_buf", "_value")

    def __init__(self, period: int = 14) -> None:
        if period < 1:
            raise ValueError(f"period must be >= 1, got {period}")
        self._period = period
        self._buf: deque[float] = deque(maxlen=period)
        self._value: float | None = None

    def update(self, raw_atr: float) -> float | None:
        """Feed one raw ATR value, return smoothed ATR (None during warmup)."""
        self._buf.append(raw_atr)
        if len(self._buf) < self._period:
            return None
        self._value = sum(self._buf) / len(self._buf)
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


class ATRPercentile:
    """Tracks where current ATR sits relative to recent history.

    Matches volatility_squeeze._update_atr_percentile. Computes the
    percentile rank of the latest close-to-close |delta| within a
    rolling history window.

    Parameters
    ----------
    history_len : int
        Maximum number of ATR values to keep for percentile calculation.
    min_samples : int
        Minimum history size before returning a percentile.
    """

    __slots__ = ("_history_len", "_min_samples", "_history", "_value")

    def __init__(self, history_len: int = 100, min_samples: int = 20) -> None:
        self._history_len = history_len
        self._min_samples = min_samples
        self._history: deque[float] = deque(maxlen=history_len)
        self._value: float | None = None

    def update(self, atr_value: float) -> float | None:
        """Feed one ATR value, return percentile rank 0-100 (None during warmup)."""
        self._history.append(atr_value)
        if len(self._history) < self._min_samples:
            return None
        below = sum(1 for v in self._history if v <= atr_value)
        self._value = 100.0 * below / len(self._history)
        return self._value

    @property
    def value(self) -> float | None:
        return self._value

    @property
    def ready(self) -> bool:
        return self._value is not None

    def reset(self) -> None:
        self._history.clear()
        self._value = None
