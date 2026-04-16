"""EMA Trend Pullback Strategy — Multi-Timeframe (1h trend, 15m entry).

Strategy class: Trend-following / pullback
Entry TF      : 15m bars (received from facade via signal_timeframe metadata)
Signal TF     : 1h bars (internally aggregated: 4 × 15m via bar_agg_trend)

Entry logic
-----------
Long:
  1. EMA(trend) rising on 1h bars      (trend direction filter)
  2. Price pulled back into EMA zone on 15m bars (price <= EMA(slow))
  3. Pullback depth >= min_pullback_pts below EMA(fast)
  4. RSI(short) < oversold threshold   (structural stress, 15m bars)
  5. ADX >= adx_min                    (market is trending, 15m smoothed)
  6. VWAP alignment: price below VWAP  (discount)
  7. Volume confirmation: bar volume above rolling average

Short: mirror image.

Exit logic (StopPolicy)
-----------------------
  Initial stop  : entry +/- atr_sl_mult x ATR
  T1 target     : entry +/- atr_t1_mult x ATR  ->  move stop to breakeven
  EMA(slow) trail : once at breakeven, trail stop at EMA(slow) +/- trail_buf.
  Max hold bars : time-exit after N 15m bars to prevent bleed.
  No forced session close — medium-term, holds overnight.

ATR approximation: SMA(|delta-close|, atr_len) x 1.6  (computed on 15m bars)
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
    "rsi_len": (RSI, "period"),
    "adx_len": (ADX, "period"),
})
_INDICATOR_PARAMS["rsi_len"]["default"] = 3
_INDICATOR_PARAMS["rsi_len"]["min"] = 2
_INDICATOR_PARAMS["rsi_len"]["max"] = 7
_INDICATOR_PARAMS["rsi_len"]["description"] = "Short RSI period for structural stress confirmation (on entry TF)."
_INDICATOR_PARAMS["adx_len"]["min"] = 7
_INDICATOR_PARAMS["adx_len"]["max"] = 30
_INDICATOR_PARAMS["adx_len"]["description"] = "ADX calculation period (1-min smoothed)."

PARAM_SCHEMA: dict[str, dict] = {
    "bar_agg_trend": {
        "type": "int", "default": 4, "min": 1, "max": 16,
        "description": "Aggregate N incoming bars for trend EMA (4 = 1h on 15m feed). 0=no aggregation.",
    },
    "ema_fast": {
        "type": "int", "default": 5, "min": 3, "max": 30,
        "description": "Fast EMA period on entry TF bars (pullback zone upper).",
    },
    "ema_slow": {
        "type": "int", "default": 13, "min": 5, "max": 50,
        "description": "Slow EMA period on entry TF bars (pullback zone lower).",
    },
    "ema_trend": {
        "type": "int", "default": 8, "min": 4, "max": 48,
        "description": "Trend EMA period on signal TF bars (direction filter). 8 bars at 1h = 8h.",
    },
    "ema_align": {
        "type": "int", "default": 1, "min": 0, "max": 1,
        "description": "Require EMA alignment (fast>slow for long, fast<slow for short).",
    },
    **_INDICATOR_PARAMS,
    "rsi_oversold": {
        "type": "float", "default": 40.0, "min": 10.0, "max": 55.0,
        "description": "RSI oversold threshold for long pullback entries.",
    },
    "rsi_overbought": {
        "type": "float", "default": 60.0, "min": 50.0, "max": 90.0,
        "description": "RSI overbought threshold for short pullback entries.",
    },
    "vol_len": {
        "type": "int", "default": 20, "min": 5, "max": 60,
        "description": "Rolling window for volume average (on entry TF).",
    },
    "vol_mult": {
        "type": "float", "default": 0.8, "min": 0.3, "max": 2.0,
        "description": "Min volume vs rolling average for entry.",
    },
    "vwap_filter": {
        "type": "int", "default": 0, "min": 0, "max": 1,
        "description": "Require VWAP directional alignment (1=on, 0=off).",
    },
    "min_pullback_pts": {
        "type": "float", "default": 5.0, "min": 2.0, "max": 40.0,
        "description": "Min pullback depth in points to filter wick touches.",
    },
    "atr_len": {
        "type": "int", "default": 10, "min": 5, "max": 30,
        "description": "ATR calculation period (on entry TF bars).",
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
    "adx_min": {
        "type": "float", "default": 25.0, "min": 10.0, "max": 40.0,
        "description": "Minimum ADX for entry (trend strength filter).",
    },
    "ema_trail_buffer_pts": {
        "type": "float", "default": 12.0, "min": 0.0, "max": 30.0,
        "description": "Points buffer for EMA trail stop after breakeven.",
    },
    "max_hold_bars": {
        "type": "int", "default": 200, "min": 4, "max": 300,
        "description": "Max entry-TF bars to hold before time-exit (200 bars at 15m = 50h ~2 days).",
    },
    "allow_night": {
        "type": "int", "default": 1, "min": 0, "max": 1,
        "description": "Allow entries during night session (0=no, 1=yes).",
    },
}

STRATEGY_META: dict = {
    "category": StrategyCategory.TREND_FOLLOWING,
    "signal_timeframe": SignalTimeframe.FIFTEEN_MIN,
    "holding_period": HoldingPeriod.MEDIUM_TERM,
    "stop_architecture": StopArchitecture.SWING,
    "expected_duration_minutes": (120, 720),
    "tradeable_sessions": ["day", "night"],
    "bars_per_day": 70,
    "presets": {
        "quick": {"n_bars": 1400, "note": "~1 month (20 trading days × 70 bars)"},
        "standard": {"n_bars": 4200, "note": "~3 months (60 trading days × 70 bars)"},
        "full_year": {"n_bars": 17640, "note": "~1 year (252 trading days × 70 bars)"},
    },
    "description": (
        "EMA Trend Pullback multi-timeframe: receives 15m bars from facade, "
        "internally aggregates to 1h for trend direction. Pullback entry on "
        "15m bars confirmed by RSI-3 stress, ADX >= 25, and VWAP alignment. "
        "Exits via ATR T1 -> breakeven, then EMA trail. Holds overnight."
    ),
}

_ATR_SCALE = 1.6


class _Indicators:
    """Thin wrapper: centralized EMA/RSI/ADX/VWAP + custom ATR & volume ratio."""

    def __init__(
        self,
        ema_fast: int,
        ema_slow: int,
        ema_trend: int,
        rsi_len: int,
        atr_len: int,
        adx_len: int,
        vol_len: int = 20,
        bar_agg_trend: int = 4,
    ) -> None:
        self._atr_len = atr_len
        self._vol_len = vol_len
        self._bar_agg = 1
        self._agg_count = 0
        self._bar_agg_trend = max(bar_agg_trend, 1) if bar_agg_trend > 0 else 1
        self._agg_count_trend = 0
        self._ema_fast_ind = EMA(period=ema_fast)
        self._ema_slow_ind = EMA(period=ema_slow)
        self._ema_trend_ind = EMA(period=ema_trend)
        self._rsi_ind = RSI(period=rsi_len)
        self._adx_ind = ADX(period=adx_len)
        self._vwap_ind = VWAP()
        self._closes: deque[float] = deque(maxlen=atr_len + 2)
        self._volumes: deque[float] = deque(maxlen=max(vol_len, 1) + 1)
        self._last_ts: datetime | None = None
        self.ema_fast: float | None = None
        self.ema_slow: float | None = None
        self.ema_trend: float | None = None
        self.ema_trend_rising: bool | None = None
        self.rsi: float | None = None
        self.atr: float | None = None
        self.atr_avg: float | None = None
        self._atr_history: deque[float] = deque(maxlen=50)
        self.vol_ratio: float | None = None
        self.adx: float = 0.0
        self.vwap: float | None = None

    def update(self, price: float, ts: datetime, volume: float = 0.0) -> None:
        if ts == self._last_ts:
            return
        self._last_ts = ts
        self._vwap_ind.update(price, max(volume, 0.0), ts)
        self.vwap = self._vwap_ind.value
        self._adx_ind.update(price)
        self.adx = self._adx_ind.value or 0.0
        self._agg_count += 1
        if self._agg_count >= self._bar_agg:
            self._agg_count = 0
            self._closes.append(price)
            self._volumes.append(volume)
            self._ema_fast_ind.update(price)
            self.ema_fast = self._ema_fast_ind.value
            self._ema_slow_ind.update(price)
            self.ema_slow = self._ema_slow_ind.value
            self._rsi_ind.update(price)
            self.rsi = self._rsi_ind.value
            self._compute_entry_atr()
            self._compute_vol_ratio()
        self._agg_count_trend += 1
        if self._agg_count_trend >= self._bar_agg_trend:
            self._agg_count_trend = 0
            prev = self._ema_trend_ind.value
            self._ema_trend_ind.update(price)
            self.ema_trend = self._ema_trend_ind.value
            if prev is not None and self.ema_trend is not None:
                self.ema_trend_rising = self.ema_trend > prev

    def _compute_entry_atr(self) -> None:
        closes = list(self._closes)
        n = len(closes)
        if n >= self._atr_len + 1:
            diffs = [abs(closes[i] - closes[i - 1]) for i in range(n - self._atr_len, n)]
            self.atr = _mean(diffs) * _ATR_SCALE
            self._atr_history.append(self.atr)
            if len(self._atr_history) >= 10:
                self.atr_avg = _mean(list(self._atr_history))

    def _compute_vol_ratio(self) -> None:
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
            "ema_fast": self.ema_fast,
            "ema_slow": self.ema_slow,
            "ema_trend": self.ema_trend,
            "vwap": self.vwap,
            "rsi": self.rsi,
            "adx": self.adx if self.adx else None,
        }

    def indicator_meta(self) -> dict[str, dict]:
        return {
            "ema_fast":  {"panel": "price", "color": "#FF6B6B", "label": "EMA Fast"},
            "ema_slow":  {"panel": "price", "color": "#4ECDC4", "label": "EMA Slow"},
            "ema_trend": {"panel": "price", "color": "#FFE66D", "label": "EMA Trend (1h)"},
            "vwap":      {"panel": "price", "color": "#95E1D3", "label": "VWAP"},
            "rsi":       {"panel": "sub",   "color": "#A8D8EA", "label": "RSI"},
            "adx":       {"panel": "sub",   "color": "#F38181", "label": "ADX"},
        }


class EMATrendPullbackEntry(EntryPolicy):
    """Enter on EMA pullback with RSI stress, ADX trend, and VWAP alignment."""

    def __init__(
        self,
        lots: float = 1.0,
        contract_type: str = "large",
        bar_agg_trend: int = 4,
        ema_fast: int = 5,
        ema_slow: int = 13,
        ema_trend: int = 8,
        ema_align: int = 1,
        rsi_len: int = 3,
        rsi_oversold: float = 40.0,
        rsi_overbought: float = 60.0,
        vol_len: int = 20,
        vol_mult: float = 0.8,
        vwap_filter: int = 0,
        min_pullback_pts: float = 5.0,
        atr_len: int = 10,
        atr_sl_mult: float = 1.6,
        atr_t1_mult: float = 6.0,
        atr_ceil: float = 0.0,
        adx_len: int = 14,
        adx_min: float = 25.0,
        ema_trail_buffer_pts: float = 12.0,
        allow_night: int = 1,
        max_hold_bars: int = 200,
    ) -> None:
        self._lots = lots
        self._contract_type = contract_type
        self._ema_align = bool(ema_align)
        self._rsi_oversold = rsi_oversold
        self._rsi_overbought = rsi_overbought
        self._vol_mult = vol_mult
        self._use_vwap = bool(vwap_filter)
        self._min_pullback = min_pullback_pts
        self._atr_sl_mult = atr_sl_mult
        self._atr_t1_mult = atr_t1_mult
        self._atr_ceil = atr_ceil
        self._adx_min = adx_min
        self._allow_night = bool(allow_night)
        self.ind = _Indicators(
            ema_fast=ema_fast, ema_slow=ema_slow, ema_trend=ema_trend,
            rsi_len=rsi_len, atr_len=atr_len, adx_len=adx_len,
            vol_len=vol_len, bar_agg_trend=bar_agg_trend,
        )

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
        self.ind.update(price, snapshot.timestamp, snapshot.volume)
        ind = self.ind
        if any(v is None for v in (
            ind.ema_fast, ind.ema_slow, ind.ema_trend,
            ind.ema_trend_rising, ind.rsi, ind.atr,
        )):
            return None
        if ind.adx < self._adx_min:
            return None
        atr = ind.atr
        if atr is None or atr <= 0:
            return None
        if self._atr_ceil > 0 and ind.atr_avg is not None and ind.atr_avg > 0:
            if atr > self._atr_ceil * ind.atr_avg:
                return None
        if ind.vol_ratio is not None and ind.vol_ratio < self._vol_mult:
            return None
        if ind.ema_trend_rising is True:
            if self._ema_align and ind.ema_fast <= ind.ema_slow:
                pass
            else:
                in_zone = price <= ind.ema_slow
                deep_enough = (ind.ema_fast - price) >= self._min_pullback
                rsi_ok = ind.rsi < self._rsi_oversold
                vwap_ok = (not self._use_vwap or ind.vwap is None
                           or price < ind.vwap)
                if in_zone and deep_enough and rsi_ok and vwap_ok:
                    return EntryDecision(
                        lots=self._lots, contract_type=self._contract_type,
                        initial_stop=price - atr * self._atr_sl_mult,
                        direction="long",
                        metadata={
                            "atr": atr, "ema_fast": ind.ema_fast,
                            "ema_slow": ind.ema_slow,
                            "t1_target": price + atr * self._atr_t1_mult,
                            "rsi": ind.rsi, "adx": ind.adx,
                            "vwap": ind.vwap,
                            "strategy": "ema_trend_pullback",
                        },
                    )
        if ind.ema_trend_rising is False:
            if self._ema_align and ind.ema_fast >= ind.ema_slow:
                pass
            else:
                in_zone = price >= ind.ema_slow
                deep_enough = (price - ind.ema_fast) >= self._min_pullback
                rsi_ok = ind.rsi > self._rsi_overbought
                vwap_ok = (not self._use_vwap or ind.vwap is None
                           or price > ind.vwap)
                if in_zone and deep_enough and rsi_ok and vwap_ok:
                    return EntryDecision(
                        lots=self._lots, contract_type=self._contract_type,
                        initial_stop=price + atr * self._atr_sl_mult,
                        direction="short",
                        metadata={
                            "atr": atr, "ema_fast": ind.ema_fast,
                            "ema_slow": ind.ema_slow,
                            "t1_target": price - atr * self._atr_t1_mult,
                            "rsi": ind.rsi, "adx": ind.adx,
                            "vwap": ind.vwap,
                            "strategy": "ema_trend_pullback",
                        },
                    )
        return None


class EMATrendPullbackStop(StopPolicy):
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
        atr = self._ind.atr if self._ind.atr is not None else snapshot.atr["daily"]
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
        self._bar_counts[pid] = self._bar_counts.get(pid, 0) + 1
        max_raw = self._max_hold * self._ind._bar_agg
        if self._bar_counts[pid] >= max_raw:
            self._bar_counts.pop(pid, None)
            return price
        if position.direction == "long":
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


def create_ema_trend_pullback_engine(
    max_loss: float = 500_000,
    lots: float = 1.0,
    contract_type: str = "large",
    bar_agg_trend: int = 4,
    ema_fast: int = 5,
    ema_slow: int = 13,
    ema_trend: int = 8,
    ema_align: int = 1,
    rsi_len: int = 3,
    rsi_oversold: float = 40.0,
    rsi_overbought: float = 60.0,
    vol_len: int = 20,
    vol_mult: float = 0.8,
    vwap_filter: int = 0,
    min_pullback_pts: float = 5.0,
    atr_len: int = 10,
    atr_sl_mult: float = 1.6,
    atr_t1_mult: float = 6.0,
    atr_ceil: float = 0.0,
    adx_len: int = 14,
    adx_min: float = 25.0,
    ema_trail_buffer_pts: float = 12.0,
    max_hold_bars: int = 200,
    allow_night: int = 1,
    pyramid_risk_level: int = 0,
) -> "PositionEngine":
    from src.core.policies import PyramidAddPolicy
    from src.core.position_engine import PositionEngine
    from src.core.types import pyramid_config_from_risk_level

    entry = EMATrendPullbackEntry(
        lots=lots, contract_type=contract_type,
        bar_agg_trend=bar_agg_trend,
        ema_fast=ema_fast, ema_slow=ema_slow, ema_trend=ema_trend,
        ema_align=ema_align,
        rsi_len=rsi_len, rsi_oversold=rsi_oversold, rsi_overbought=rsi_overbought,
        vol_len=vol_len, vol_mult=vol_mult, vwap_filter=vwap_filter,
        min_pullback_pts=min_pullback_pts,
        atr_len=atr_len, atr_sl_mult=atr_sl_mult, atr_t1_mult=atr_t1_mult,
        atr_ceil=atr_ceil,
        adx_len=adx_len, adx_min=adx_min,
        ema_trail_buffer_pts=ema_trail_buffer_pts,
        max_hold_bars=max_hold_bars,
        allow_night=allow_night,
    )
    stop = EMATrendPullbackStop(
        indicators=entry.ind,
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
    engine.indicator_provider = entry.ind  # type: ignore[attr-defined]
    return engine
