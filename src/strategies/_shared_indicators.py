"""Reusable rolling indicator computations for strategy modules.

All indicators operate on close prices only (MarketSnapshot.price) since
intraday snapshots don't expose high/low.
"""
from __future__ import annotations

from collections import deque
from statistics import mean, stdev


class RollingMA:
    """Simple moving average over a fixed window."""

    def __init__(self, length: int) -> None:
        self._length = length
        self._buf: deque[float] = deque(maxlen=length)

    def update(self, price: float) -> None:
        self._buf.append(price)

    @property
    def value(self) -> float | None:
        if len(self._buf) < self._length:
            return None
        return mean(self._buf)


class RollingATR:
    """ATR approximated as SMA(|delta-close|, n).

    True range requires high/low which isn't available from MarketSnapshot,
    so we use absolute close-to-close changes as a proxy.
    """

    def __init__(self, length: int) -> None:
        self._length = length
        self._closes: deque[float] = deque(maxlen=length + 1)

    def update(self, price: float) -> None:
        self._closes.append(price)

    @property
    def value(self) -> float | None:
        closes = list(self._closes)
        if len(closes) < self._length + 1:
            return None
        tr_vals = [abs(closes[i] - closes[i - 1]) for i in range(len(closes) - self._length, len(closes))]
        return mean(tr_vals)


class RollingBB:
    """Bollinger Bands with asymmetric multipliers."""

    def __init__(self, length: int, upper_mult: float = 2.0, lower_mult: float = 2.0) -> None:
        self._length = length
        self._upper_mult = upper_mult
        self._lower_mult = lower_mult
        self._buf: deque[float] = deque(maxlen=length)
        self.mid: float | None = None
        self.upper: float | None = None
        self.lower: float | None = None

    def update(self, price: float) -> None:
        self._buf.append(price)
        if len(self._buf) < self._length:
            return
        window = list(self._buf)
        self.mid = mean(window)
        sd = stdev(window) if len(window) > 1 else 0.0
        self.upper = self.mid + self._upper_mult * sd
        self.lower = self.mid - self._lower_mult * sd


class RollingRSI:
    """Non-smoothed Wilder RSI over a fixed window."""

    def __init__(self, length: int) -> None:
        self._length = length
        self._closes: deque[float] = deque(maxlen=length + 1)

    def update(self, price: float) -> None:
        self._closes.append(price)

    @property
    def value(self) -> float | None:
        closes = list(self._closes)
        if len(closes) < self._length + 1:
            return None
        changes = [closes[i] - closes[i - 1] for i in range(len(closes) - self._length, len(closes))]
        gains = [c for c in changes if c > 0]
        losses = [-c for c in changes if c < 0]
        avg_gain = mean(gains) if gains else 0.0
        avg_loss = mean(losses) if losses else 0.0
        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        return 100.0 - (100.0 / (1.0 + rs))
