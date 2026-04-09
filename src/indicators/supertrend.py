"""Streaming SuperTrend indicator.

ATR-based adaptive trailing stop that doubles as a trend filter.
Widens in volatile markets, tightens in calm ones.

- trend = +1 (bullish) when close > upper band flips to lower band tracking
- trend = -1 (bearish) when close < lower band flips to upper band tracking
- stop_level = current trailing stop price
"""
from __future__ import annotations

from dataclasses import dataclass

from src.indicators.true_atr import TrueATR


@dataclass(frozen=True)
class SuperTrendResult:
    """SuperTrend output."""

    trend: int          # +1 bullish, -1 bearish
    stop_level: float   # current trailing stop price


class SuperTrend:
    """Streaming SuperTrend.

    Parameters
    ----------
    atr_period : int
        ATR period for volatility. Default 10.
    multiplier : float
        ATR multiplier for band width. Default 3.0.
    """

    __slots__ = (
        "_multiplier", "_atr",
        "_prev_upper", "_prev_lower",
        "_prev_trend", "_prev_close",
        "_value",
    )

    def __init__(self, atr_period: int = 10, multiplier: float = 3.0) -> None:
        if multiplier <= 0:
            raise ValueError(f"multiplier must be > 0, got {multiplier}")
        self._multiplier = multiplier
        self._atr = TrueATR(atr_period, smoothing="ema")
        self._prev_upper: float | None = None
        self._prev_lower: float | None = None
        self._prev_trend: int = 1
        self._prev_close: float | None = None
        self._value: SuperTrendResult | None = None

    def update(self, high: float, low: float, close: float) -> SuperTrendResult | None:
        """Feed one OHLC bar, return SuperTrendResult (None during ATR warmup)."""
        atr_val = self._atr.update(high, low, close)
        if atr_val is None:
            self._prev_close = close
            return None

        hl2 = (high + low) / 2.0
        basic_upper = hl2 + self._multiplier * atr_val
        basic_lower = hl2 - self._multiplier * atr_val

        # Final upper band: can only decrease (tighten) in downtrend
        if self._prev_upper is not None and self._prev_close is not None:
            if self._prev_close <= self._prev_upper:
                final_upper = min(basic_upper, self._prev_upper)
            else:
                final_upper = basic_upper
        else:
            final_upper = basic_upper

        # Final lower band: can only increase (tighten) in uptrend
        if self._prev_lower is not None and self._prev_close is not None:
            if self._prev_close >= self._prev_lower:
                final_lower = max(basic_lower, self._prev_lower)
            else:
                final_lower = basic_lower
        else:
            final_lower = basic_lower

        # Determine trend
        if self._prev_trend == 1:
            trend = -1 if close < final_lower else 1
        else:
            trend = 1 if close > final_upper else -1

        stop_level = final_lower if trend == 1 else final_upper

        self._prev_upper = final_upper
        self._prev_lower = final_lower
        self._prev_trend = trend
        self._prev_close = close

        self._value = SuperTrendResult(trend=trend, stop_level=stop_level)
        return self._value

    @property
    def value(self) -> SuperTrendResult | None:
        return self._value

    @property
    def ready(self) -> bool:
        return self._value is not None

    def reset(self) -> None:
        self._atr.reset()
        self._prev_upper = None
        self._prev_lower = None
        self._prev_trend = 1
        self._prev_close = None
        self._value = None
