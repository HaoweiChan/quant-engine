"""Streaming Keltner Channel.

Matches volatility_squeeze._compute_signal Keltner section:
- Mid = EMA of close prices
- ATR = SMA of |close - prev_close| (close-to-close proxy)
- Upper/Lower = mid +/- mult * ATR
"""
from __future__ import annotations

from collections import deque
from statistics import mean


PARAM_SPEC: dict[str, dict] = {
    "period": {"type": "int", "default": 20, "min": 5, "max": 60, "description": "Keltner Channel EMA lookback."},
    "multiplier": {"type": "float", "default": 1.5, "min": 0.5, "max": 4.0, "description": "ATR multiplier for channel width."},
}


class KeltnerChannel:
    """Streaming Keltner Channel on close prices.

    Parameters
    ----------
    period : int
        EMA / ATR lookback period.
    multiplier : float
        ATR multiplier for channel width.
    atr_scale : float
        Scaling factor applied to raw ATR. Some strategies use sqrt(2).
        Default 1.0.

    Attributes (None until warmup completes):
        mid: EMA(period)
        upper: mid + multiplier * scaled_atr
        lower: mid - multiplier * scaled_atr
    """

    __slots__ = (
        "_period", "_mult", "_atr_scale", "_alpha",
        "_ema", "_closes", "_count",
        "mid", "upper", "lower",
    )

    def __init__(
        self,
        period: int = 20,
        multiplier: float = 1.5,
        atr_scale: float = 1.0,
    ) -> None:
        if period < 1:
            raise ValueError(f"period must be >= 1, got {period}")
        self._period = period
        self._mult = multiplier
        self._atr_scale = atr_scale
        self._alpha = 2.0 / (period + 1)
        self._ema: float | None = None
        self._closes: deque[float] = deque(maxlen=period + 1)
        self._count = 0
        self.mid: float | None = None
        self.upper: float | None = None
        self.lower: float | None = None

    def update(self, price: float) -> bool:
        """Feed one close price. Returns True when channel is ready."""
        self._closes.append(price)
        self._count += 1

        # EMA mid-line: SMA seed then incremental
        if self._ema is None:
            if self._count >= self._period:
                self._ema = mean(list(self._closes)[-self._period:])
        else:
            self._ema = self._alpha * price + (1 - self._alpha) * self._ema
        self.mid = self._ema

        # ATR for channel width
        closes = list(self._closes)
        if self.mid is not None and len(closes) >= self._period + 1:
            diffs = [
                abs(closes[i] - closes[i - 1])
                for i in range(max(1, len(closes) - self._period), len(closes))
            ]
            kc_atr = mean(diffs) * self._atr_scale if diffs else 0.0
            width = self._mult * kc_atr
            self.upper = self.mid + width
            self.lower = self.mid - width
            return True
        return False

    @property
    def ready(self) -> bool:
        return self.upper is not None

    def reset(self) -> None:
        self._ema = None
        self._closes.clear()
        self._count = 0
        self.mid = None
        self.upper = None
        self.lower = None
