"""Medium-Term Keltner + VWAP + ADX Regime-Adaptive Breakout Strategy.

Adapted from the short-term (1-min) version to 15-min bars for multi-session holding.

Strategy logic:
  Keltner Channel (EMA ± K * ATR) defines volatility bands on 15m bars.
  ADX regime filter:
    - Trending (ADX >= threshold): breakout at KC extremes
    - Choppy   (ADX <  threshold): mean-reversion at KC extremes + RSI
  VWAP directional alignment (optional).
  RSI oversold/overbought confirmation for choppy-regime entries.
  Volume spike confirmation.

Exit logic (medium-term pattern):
  Initial stop  : entry ± atr_sl_mult x ATR
  T1 target     : entry ± atr_t1_mult x ATR → move stop to breakeven
  EMA(slow) trail after breakeven, with buffer
  Max hold bars : time-exit after N 15m bars
  No forced session close — holds overnight.
"""
from __future__ import annotations

from collections import deque
from datetime import datetime
from typing import TYPE_CHECKING

from src.core.policies import EntryPolicy, NoAddPolicy, StopPolicy
from src.core.types import (
    AccountState,
    EngineConfig,
    EngineState,
    EntryDecision,
    MarketSignal,
    MarketSnapshot,
    Position,
)
from src.indicators import ADX, EMA, RSI, VWAP, compose_param_schema
from src.strategies import HoldingPeriod, SignalTimeframe, StopArchitecture, StrategyCategory
from src.strategies._session_utils import in_day_session, in_night_session

if TYPE_CHECKING:
    from src.core.position_engine import PositionEngine


def _mean(vals: list[float]) -> float:
    return sum(vals) / len(vals)


_INDICATOR_PARAMS = compose_param_schema({
    "adx_period": (ADX, "period"),
    "rsi_len": (RSI, "period"),
})
_INDICATOR_PARAMS["adx_period"]["min"] = 7
_INDICATOR_PARAMS["adx_period"]["max"] = 30
_INDICATOR_PARAMS["adx_period"]["description"] = "ADX smoothing period."
_INDICATOR_PARAMS["rsi_len"]["default"] = 3
_INDICATOR_PARAMS["rsi_len"]["min"] = 2
_INDICATOR_PARAMS["rsi_len"]["max"] = 10
_INDICATOR_PARAMS["rsi_len"]["description"] = "RSI lookback period (short for structural stress)."

PARAM_SCHEMA: dict[str, dict] = {
    "kc_len": {
        "type": "int", "default": 20, "min": 10, "max": 60,
        "description": "EMA lookback for Keltner midline (15m bars). 20 bars = 5 hours.",
    },
    "kc_mult": {
        "type": "float", "default": 0.3, "min": 0.05, "max": 1.0,
        "description": "KC width as fraction of ATR.",
    },
    **_INDICATOR_PARAMS,
    "adx_threshold": {
        "type": "float", "default": 35.0, "min": 10.0, "max": 50.0,
        "description": "ADX above this = trending (breakout), below = choppy (reversion).",
    },
    "rsi_oversold": {
        "type": "float", "default": 30.0, "min": 10.0, "max": 45.0,
        "description": "RSI threshold for oversold (mean-reversion long).",
    },
    "rsi_overbought": {
        "type": "float", "default": 75.0, "min": 55.0, "max": 90.0,
        "description": "RSI threshold for overbought (mean-reversion short).",
    },
    "vwap_filter": {
        "type": "int", "default": 0, "min": 0, "max": 1,
        "description": "Require VWAP alignment for entries (1=on, 0=off).",
    },
    "ema_fast": {
        "type": "int", "default": 5, "min": 3, "max": 30,
        "description": "Fast EMA period on 15m bars.",
    },
    "ema_slow": {
        "type": "int", "default": 13, "min": 5, "max": 50,
        "description": "Slow EMA period on 15m bars (trail stop reference).",
    },
    "atr_len": {
        "type": "int", "default": 10, "min": 5, "max": 30,
        "description": "ATR calculation period (on 15m bars).",
    },
    "atr_sl_mult": {
        "type": "float", "default": 1.6, "min": 0.5, "max": 3.0,
        "description": "ATR multiplier for initial stop loss.",
    },
    "atr_t1_mult": {
        "type": "float", "default": 6.0, "min": 1.5, "max": 10.0,
        "description": "ATR multiplier for T1 target (breakeven trigger).",
    },
    "atr_ceil": {
        "type": "float", "default": 0.0, "min": 0.0, "max": 5.0,
        "description": "Max ATR as multiple of rolling avg (0=disabled).",
    },
    "ema_trail_buffer_pts": {
        "type": "float", "default": 12.0, "min": 0.0, "max": 30.0,
        "description": "Points buffer for EMA trail stop after breakeven.",
    },
    "trend_ma_len": {
        "type": "int", "default": 40, "min": 20, "max": 100,
        "description": "Trend EMA lookback for extreme-trend filter (15m bars). 40 bars = ~10h.",
    },
    "trend_filter_atr": {
        "type": "float", "default": 3.0, "min": 0.5, "max": 5.0,
        "description": "Block entries when |price - trend_ema| > N * ATR.",
    },
    "vol_len": {
        "type": "int", "default": 20, "min": 5, "max": 60,
        "description": "Rolling window for average volume.",
    },
    "vol_mult": {
        "type": "float", "default": 1.0, "min": 0.3, "max": 3.0,
        "description": "Min volume vs rolling average for entry.",
    },
    "max_hold_bars": {
        "type": "int", "default": 200, "min": 10, "max": 300,
        "description": "Max 15m bars to hold before time-exit (200 bars = ~50h).",
    },
    "allow_night": {
        "type": "int", "default": 1, "min": 0, "max": 1,
        "description": "Allow entries during night session (0=day only, 1=day+night).",
    },
}

STRATEGY_META: dict = {
    "category": StrategyCategory.BREAKOUT,
    "signal_timeframe": SignalTimeframe.FIFTEEN_MIN,
    "holding_period": HoldingPeriod.MEDIUM_TERM,
    "stop_architecture": StopArchitecture.SWING,
    "expected_duration_minutes": (120, 720),
    "tradeable_sessions": ["day", "night"],
    "bars_per_day": 70,
    "presets": {
        "quick": {"n_bars": 1400, "note": "~1 month (20 trading days x 70 bars)"},
        "standard": {"n_bars": 4200, "note": "~3 months (60 trading days x 70 bars)"},
        "full_year": {"n_bars": 17640, "note": "~1 year (252 trading days x 70 bars)"},
    },
    "description": (
        "Medium-term Keltner + VWAP + ADX regime-adaptive strategy on 15m bars. "
        "Breakout in trending regime, mean-reversion in choppy. Holds overnight. "
        "ATR T1 -> breakeven, then EMA trail. Pyramid support."
    ),
}

_ATR_SCALE = 1.6


# ---------------------------------------------------------------------------
# Indicators
# ---------------------------------------------------------------------------

class _Indicators:
    """Thin wrapper: centralized ADX/RSI/EMA/VWAP + custom KC bands, ATR & volume ratio."""

    def __init__(
        self,
        kc_len: int,
        kc_mult: float,
        rsi_len: int,
        adx_period: int,
        trend_ma_len: int,
        vol_len: int,
        ema_fast: int,
        ema_slow: int,
        atr_len: int,
    ) -> None:
        self._kc_mult = kc_mult
        self._vol_len = vol_len
        self._atr_len = atr_len
        self._kc_ema = EMA(period=kc_len)
        self._trend_ema_ind = EMA(period=trend_ma_len)
        self._ema_fast_ind = EMA(period=ema_fast)
        self._ema_slow_ind = EMA(period=ema_slow)
        self._rsi_ind = RSI(period=rsi_len)
        self._adx_ind = ADX(period=adx_period)
        self._vwap_ind = VWAP()
        self._closes: deque[float] = deque(maxlen=atr_len + 2)
        self._volumes: deque[float] = deque(maxlen=max(vol_len, 1) + 1)
        self._last_ts: datetime | None = None
        self.kc_mid: float | None = None
        self.kc_upper: float | None = None
        self.kc_lower: float | None = None
        self.rsi: float | None = None
        self.adx: float = 0.0
        self.trend_ema: float | None = None
        self.vol_ratio: float | None = None
        self.vwap: float | None = None
        self.ema_fast: float | None = None
        self.ema_slow: float | None = None
        self.atr: float | None = None
        self.atr_avg: float | None = None
        self._atr_history: deque[float] = deque(maxlen=50)

    def update(self, price: float, timestamp: datetime, volume: float = 0.0) -> None:
        if timestamp == self._last_ts:
            return
        self._last_ts = timestamp
        self._closes.append(price)
        self._volumes.append(volume)
        self._vwap_ind.update(price, max(volume, 0.0), timestamp)
        self.vwap = self._vwap_ind.value
        self._adx_ind.update(price)
        self.adx = self._adx_ind.value or 0.0
        self._rsi_ind.update(price)
        self.rsi = self._rsi_ind.value
        self._ema_fast_ind.update(price)
        self.ema_fast = self._ema_fast_ind.value
        self._ema_slow_ind.update(price)
        self.ema_slow = self._ema_slow_ind.value
        self._trend_ema_ind.update(price)
        self.trend_ema = self._trend_ema_ind.value
        # KC midline via EMA + custom ATR-based bands
        mid = self._kc_ema.update(price)
        self.kc_mid = mid
        if mid is not None and self.atr is not None and self.atr > 0:
            width = self._kc_mult * self.atr
            self.kc_upper = mid + width
            self.kc_lower = mid - width
        # Custom ATR (SMA of |delta-close| × scale)
        closes = list(self._closes)
        n = len(closes)
        if n >= self._atr_len + 1:
            diffs = [abs(closes[i] - closes[i - 1]) for i in range(n - self._atr_len, n)]
            self.atr = _mean(diffs) * _ATR_SCALE
            self._atr_history.append(self.atr)
            if len(self._atr_history) >= 10:
                self.atr_avg = _mean(list(self._atr_history))
        # Volume ratio
        vols = list(self._volumes)
        nv = len(vols)
        if nv >= self._vol_len and self._vol_len > 0:
            avg_vol = _mean(vols[-self._vol_len:])
            self.vol_ratio = vols[-1] / avg_vol if avg_vol > 0 else 0.0
        elif nv > 0 and vols[-1] > 0:
            self.vol_ratio = 1.0
        else:
            self.vol_ratio = None

    def snapshot(self) -> dict[str, float | None]:
        return {
            "kc_upper": self.kc_upper, "kc_mid": self.kc_mid, "kc_lower": self.kc_lower,
            "ema_fast": self.ema_fast, "ema_slow": self.ema_slow,
            "vwap": self.vwap, "trend_ema": self.trend_ema,
            "rsi": self.rsi, "adx": self.adx if self.adx else None,
        }

    def indicator_meta(self) -> dict[str, dict]:
        return {
            "kc_upper":  {"panel": "price", "color": "#FF6B6B", "label": "KC Upper"},
            "kc_mid":    {"panel": "price", "color": "#4ECDC4", "label": "KC Mid"},
            "kc_lower":  {"panel": "price", "color": "#FF6B6B", "label": "KC Lower"},
            "ema_fast":  {"panel": "price", "color": "#FFE66D", "label": "EMA Fast"},
            "ema_slow":  {"panel": "price", "color": "#95E1D3", "label": "EMA Slow"},
            "vwap":      {"panel": "price", "color": "#DDA0DD", "label": "VWAP"},
            "trend_ema": {"panel": "price", "color": "#87CEEB", "label": "Trend EMA"},
            "rsi":       {"panel": "sub",   "color": "#A8D8EA", "label": "RSI"},
            "adx":       {"panel": "sub",   "color": "#F38181", "label": "ADX"},
        }


# ---------------------------------------------------------------------------
# Entry policy
# ---------------------------------------------------------------------------

class KeltnerVWAPEntryPolicy(EntryPolicy):
    """Dual-regime entry: breakout in trending, mean-reversion in choppy."""

    def __init__(
        self,
        indicators: _Indicators,
        lots: float = 1.0,
        contract_type: str = "large",
        adx_threshold: float = 35.0,
        vwap_filter: int = 0,
        atr_sl_mult: float = 1.6,
        atr_t1_mult: float = 6.0,
        atr_ceil: float = 0.0,
        rsi_oversold: float = 30.0,
        rsi_overbought: float = 75.0,
        trend_filter_atr: float = 3.0,
        vol_mult: float = 1.0,
        allow_night: int = 1,
    ) -> None:
        self._ind = indicators
        self._lots = lots
        self._contract_type = contract_type
        self._adx_threshold = adx_threshold
        self._use_vwap = bool(vwap_filter)
        self._atr_sl_mult = atr_sl_mult
        self._atr_t1_mult = atr_t1_mult
        self._atr_ceil = atr_ceil
        self._rsi_oversold = rsi_oversold
        self._rsi_overbought = rsi_overbought
        self._trend_filter_atr = trend_filter_atr
        self._vol_mult = vol_mult
        self._allow_night = bool(allow_night)

    def should_enter(
        self,
        snapshot: MarketSnapshot,
        signal: MarketSignal | None,
        engine_state: EngineState,
        account: AccountState | None = None,
    ) -> EntryDecision | None:
        if engine_state.mode == "halted":
            return None
        t = snapshot.timestamp.time()

        day_ok = in_day_session(t)
        night_ok = self._allow_night and in_night_session(t)
        if not (day_ok or night_ok):
            return None

        price = snapshot.price
        self._ind.update(price, snapshot.timestamp, snapshot.volume)
        ind = self._ind

        if any(v is None for v in (ind.kc_lower, ind.kc_upper, ind.rsi, ind.trend_ema)):
            return None
        atr = ind.atr
        if atr is None or atr <= 0:
            return None
        if self._atr_ceil > 0 and ind.atr_avg is not None and ind.atr_avg > 0:
            if atr > self._atr_ceil * ind.atr_avg:
                return None

        # Extreme trend filter
        if abs(price - ind.trend_ema) > self._trend_filter_atr * atr:
            return None
        # Volume confirmation
        if ind.vol_ratio is not None and ind.vol_ratio < self._vol_mult:
            return None

        sl_pts = atr * self._atr_sl_mult
        is_trending = ind.adx >= self._adx_threshold

        if not is_trending:
            # CHOPPY regime: mean reversion at KC extremes + RSI
            if price < ind.kc_lower and ind.rsi < self._rsi_oversold:
                if self._use_vwap and ind.vwap is not None and price > ind.vwap:
                    return None
                return EntryDecision(
                    lots=self._lots,
                    contract_type=self._contract_type,
                    initial_stop=price - sl_pts,
                    direction="long",
                    metadata={
                        "regime": "MR", "adx": round(ind.adx, 1),
                        "rsi": round(ind.rsi, 1), "atr": atr,
                        "t1_target": price + atr * self._atr_t1_mult,
                        "strategy": "mt_keltner_vwap_breakout",
                    },
                )
            if price > ind.kc_upper and ind.rsi > self._rsi_overbought:
                if self._use_vwap and ind.vwap is not None and price < ind.vwap:
                    return None
                return EntryDecision(
                    lots=self._lots,
                    contract_type=self._contract_type,
                    initial_stop=price + sl_pts,
                    direction="short",
                    metadata={
                        "regime": "MR", "adx": round(ind.adx, 1),
                        "rsi": round(ind.rsi, 1), "atr": atr,
                        "t1_target": price - atr * self._atr_t1_mult,
                        "strategy": "mt_keltner_vwap_breakout",
                    },
                )
        else:
            # TRENDING regime: breakout follow at KC extremes
            if price > ind.kc_upper:
                if self._use_vwap and ind.vwap is not None and price < ind.vwap:
                    return None
                return EntryDecision(
                    lots=self._lots,
                    contract_type=self._contract_type,
                    initial_stop=price - sl_pts,
                    direction="long",
                    metadata={
                        "regime": "BO", "adx": round(ind.adx, 1),
                        "rsi": round(ind.rsi, 1), "atr": atr,
                        "t1_target": price + atr * self._atr_t1_mult,
                        "strategy": "mt_keltner_vwap_breakout",
                    },
                )
            if price < ind.kc_lower:
                if self._use_vwap and ind.vwap is not None and price > ind.vwap:
                    return None
                return EntryDecision(
                    lots=self._lots,
                    contract_type=self._contract_type,
                    initial_stop=price + sl_pts,
                    direction="short",
                    metadata={
                        "regime": "BO", "adx": round(ind.adx, 1),
                        "rsi": round(ind.rsi, 1), "atr": atr,
                        "t1_target": price - atr * self._atr_t1_mult,
                        "strategy": "mt_keltner_vwap_breakout",
                    },
                )
        return None


# ---------------------------------------------------------------------------
# Stop policy — T1 -> breakeven -> EMA trail
# ---------------------------------------------------------------------------

class KeltnerVWAPStopPolicy(StopPolicy):
    """ATR T1 -> breakeven, then EMA(slow) trail, with max hold time-exit."""

    def __init__(
        self,
        indicators: _Indicators,
        atr_sl_mult: float = 1.6,
        atr_t1_mult: float = 6.0,
        ema_trail_buffer_pts: float = 12.0,
        max_hold_bars: int = 200,
    ) -> None:
        self._ind = indicators
        self._atr_sl_mult = atr_sl_mult
        self._atr_t1_mult = atr_t1_mult
        self._trail_buf = ema_trail_buffer_pts
        self._max_hold = max_hold_bars
        self._t1_target: float | None = None
        self._at_breakeven: bool = False
        self._bar_counts: dict[str, int] = {}

    def initial_stop(
        self, entry_price: float, direction: str, snapshot: MarketSnapshot,
    ) -> float:
        self._at_breakeven = False
        self._t1_target = None
        atr = self._ind.atr if self._ind.atr is not None else snapshot.atr.get("daily", 200.0)
        if direction == "long":
            self._t1_target = entry_price + atr * self._atr_t1_mult
            return entry_price - atr * self._atr_sl_mult
        else:
            self._t1_target = entry_price - atr * self._atr_t1_mult
            return entry_price + atr * self._atr_sl_mult

    def update_stop(
        self,
        position: Position,
        snapshot: MarketSnapshot,
        high_history: deque[float],
    ) -> float:
        self._ind.update(snapshot.price, snapshot.timestamp, snapshot.volume)
        price = snapshot.price
        stop = position.stop_level
        entry = position.entry_price
        pid = position.position_id

        # Time exit
        self._bar_counts[pid] = self._bar_counts.get(pid, 0) + 1
        if self._bar_counts[pid] >= self._max_hold:
            self._bar_counts.pop(pid, None)
            return price

        if position.direction == "long":
            # T1 breakeven trigger
            if (not self._at_breakeven
                    and self._t1_target is not None
                    and price >= self._t1_target
                    and stop < entry):
                self._at_breakeven = True
                return entry
            if self._at_breakeven and self._ind.ema_slow is not None:
                trail_level = self._ind.ema_slow - self._trail_buf
                return max(stop, trail_level)
        else:
            # T1 breakeven trigger
            if (not self._at_breakeven
                    and self._t1_target is not None
                    and price <= self._t1_target
                    and stop > entry):
                self._at_breakeven = True
                return entry
            if self._at_breakeven and self._ind.ema_slow is not None:
                trail_level = self._ind.ema_slow + self._trail_buf
                return min(stop, trail_level)

        return stop


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def create_keltner_vwap_breakout_engine(
    max_loss: float = 500_000,
    lots: float = 1.0,
    contract_type: str = "large",
    kc_len: int = 20,
    kc_mult: float = 0.3,
    adx_period: int = 14,
    adx_threshold: float = 35.0,
    rsi_len: int = 3,
    rsi_oversold: float = 30.0,
    rsi_overbought: float = 75.0,
    vwap_filter: int = 0,
    ema_fast: int = 5,
    ema_slow: int = 13,
    atr_len: int = 10,
    atr_sl_mult: float = 1.6,
    atr_t1_mult: float = 6.0,
    atr_ceil: float = 0.0,
    ema_trail_buffer_pts: float = 12.0,
    trend_ma_len: int = 40,
    trend_filter_atr: float = 3.0,
    vol_len: int = 20,
    vol_mult: float = 1.0,
    max_hold_bars: int = 200,
    allow_night: int = 1,
    pyramid_risk_level: int = 0,
) -> "PositionEngine":
    """Build a PositionEngine wired with the medium-term Keltner VWAP Breakout strategy."""
    from src.core.policies import PyramidAddPolicy
    from src.core.position_engine import PositionEngine
    from src.core.types import pyramid_config_from_risk_level

    indicators = _Indicators(
        kc_len=kc_len,
        kc_mult=kc_mult,
        rsi_len=rsi_len,
        adx_period=adx_period,
        trend_ma_len=trend_ma_len,
        vol_len=vol_len,
        ema_fast=ema_fast,
        ema_slow=ema_slow,
        atr_len=atr_len,
    )
    entry = KeltnerVWAPEntryPolicy(
        indicators=indicators,
        lots=lots,
        contract_type=contract_type,
        adx_threshold=adx_threshold,
        vwap_filter=vwap_filter,
        atr_sl_mult=atr_sl_mult,
        atr_t1_mult=atr_t1_mult,
        atr_ceil=atr_ceil,
        rsi_oversold=rsi_oversold,
        rsi_overbought=rsi_overbought,
        trend_filter_atr=trend_filter_atr,
        vol_mult=vol_mult,
        allow_night=allow_night,
    )
    stop = KeltnerVWAPStopPolicy(
        indicators=indicators,
        atr_sl_mult=atr_sl_mult,
        atr_t1_mult=atr_t1_mult,
        ema_trail_buffer_pts=ema_trail_buffer_pts,
        max_hold_bars=max_hold_bars,
    )
    pcfg = pyramid_config_from_risk_level(pyramid_risk_level, max_loss, lots)
    add_policy = PyramidAddPolicy(pcfg) if pcfg is not None else NoAddPolicy()
    engine = PositionEngine(
        entry_policy=entry,
        add_policy=add_policy,
        stop_policy=stop,
        config=EngineConfig(max_loss=max_loss, pyramid_risk_level=pyramid_risk_level),
    )
    engine.indicator_provider = indicators  # type: ignore[attr-defined]
    return engine
