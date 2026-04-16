"""Streaming MACD (Moving Average Convergence Divergence).

MACD line = EMA(fast) - EMA(slow)
Signal line = EMA(MACD line, signal_period)
Histogram = MACD - Signal
"""
from __future__ import annotations

from dataclasses import dataclass

from src.indicators.ema import EMA


@dataclass(frozen=True)
class MACDResult:
    """Snapshot of all three MACD components."""

    macd: float       # EMA(fast) - EMA(slow)
    signal: float     # EMA of MACD line
    histogram: float  # macd - signal


PARAM_SPEC: dict[str, dict] = {
    "fast": {"type": "int", "default": 12, "min": 5, "max": 20, "description": "MACD fast EMA period."},
    "slow": {"type": "int", "default": 26, "min": 15, "max": 50, "description": "MACD slow EMA period."},
    "signal": {"type": "int", "default": 9, "min": 3, "max": 20, "description": "MACD signal EMA period."},
}


class MACD:
    """Streaming MACD with configurable periods.

    Parameters
    ----------
    fast : int
        Fast EMA period. Default 12.
    slow : int
        Slow EMA period. Default 26.
    signal : int
        Signal line EMA period. Default 9.
    """

    __slots__ = ("_fast_ema", "_slow_ema", "_signal_ema", "_value")

    def __init__(
        self, fast: int = 12, slow: int = 26, signal: int = 9
    ) -> None:
        if fast >= slow:
            raise ValueError(f"fast ({fast}) must be < slow ({slow})")
        if signal < 1:
            raise ValueError(f"signal must be >= 1, got {signal}")
        self._fast_ema = EMA(fast)
        self._slow_ema = EMA(slow)
        self._signal_ema = EMA(signal)
        self._value: MACDResult | None = None

    def update(self, price: float) -> MACDResult | None:
        """Feed one price, return MACDResult (None during warmup)."""
        fast_val = self._fast_ema.update(price)
        slow_val = self._slow_ema.update(price)
        if fast_val is None or slow_val is None:
            return None
        macd_line = fast_val - slow_val
        sig_val = self._signal_ema.update(macd_line)
        if sig_val is None:
            return None
        self._value = MACDResult(
            macd=macd_line,
            signal=sig_val,
            histogram=macd_line - sig_val,
        )
        return self._value

    @property
    def value(self) -> MACDResult | None:
        return self._value

    @property
    def ready(self) -> bool:
        return self._value is not None

    def reset(self) -> None:
        self._fast_ema.reset()
        self._slow_ema.reset()
        self._signal_ema.reset()
        self._value = None
