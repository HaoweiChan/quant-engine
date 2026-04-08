"""Streaming Average Directional Index (ADX).

EMA-smoothed variant operating on close prices only (no high/low).

This matches the dominant implementation across strategies:
volatility_squeeze, donchian_trend_strength, bollinger_pinbar,
keltner_vwap_breakout, atr_mean_reversion, vwap_statistical_deviation,
ema_trend_pullback, structural_orb.

Uses |close - prev_close| as TR proxy since MarketSnapshot doesn't
expose high/low.
"""
from __future__ import annotations


class ADX:
    """Streaming EMA-smoothed ADX on close-to-close changes.

    Parameters
    ----------
    period : int
        EMA smoothing period. Alpha = 2 / (period + 1).
    """

    __slots__ = (
        "_alpha",
        "_prev_price",
        "_atr_ema",
        "_plus_dm_ema",
        "_minus_dm_ema",
        "_adx_ema",
        "_value",
    )

    def __init__(self, period: int = 14) -> None:
        if period < 1:
            raise ValueError(f"period must be >= 1, got {period}")
        self._alpha = 2.0 / (period + 1)
        self._prev_price: float | None = None
        self._atr_ema: float | None = None
        self._plus_dm_ema: float | None = None
        self._minus_dm_ema: float | None = None
        self._adx_ema: float | None = None
        self._value: float | None = None

    def update(self, price: float) -> float | None:
        """Feed one close price, return current ADX (None during warmup)."""
        if self._prev_price is None:
            self._prev_price = price
            return None

        tr = abs(price - self._prev_price)
        delta = price - self._prev_price
        pdm = max(delta, 0.0)
        mdm = max(-delta, 0.0)
        a = self._alpha

        if self._atr_ema is None:
            self._atr_ema = tr
            self._plus_dm_ema = pdm
            self._minus_dm_ema = mdm
        else:
            self._atr_ema = a * tr + (1 - a) * self._atr_ema
            self._plus_dm_ema = a * pdm + (1 - a) * self._plus_dm_ema
            self._minus_dm_ema = a * mdm + (1 - a) * self._minus_dm_ema

        if self._atr_ema is not None and self._atr_ema > 1e-9:
            pdi = 100.0 * (self._plus_dm_ema / self._atr_ema)  # type: ignore[operator]
            mdi = 100.0 * (self._minus_dm_ema / self._atr_ema)  # type: ignore[operator]
            denom = pdi + mdi
            if denom > 1e-9:
                dx = 100.0 * abs(pdi - mdi) / denom
                if self._adx_ema is None:
                    self._adx_ema = dx
                else:
                    self._adx_ema = a * dx + (1 - a) * self._adx_ema
                self._value = self._adx_ema

        self._prev_price = price
        return self._value

    @property
    def value(self) -> float | None:
        return self._value

    @property
    def ready(self) -> bool:
        return self._value is not None

    def reset(self) -> None:
        self._prev_price = None
        self._atr_ema = None
        self._plus_dm_ema = None
        self._minus_dm_ema = None
        self._adx_ema = None
        self._value = None
