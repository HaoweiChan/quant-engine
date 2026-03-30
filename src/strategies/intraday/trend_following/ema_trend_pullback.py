"""EMA Trend Pullback Strategy (intraday bars, TAIFEX TX/MTX).

Strategy class: Trend-following / pullback
Timeframe     : Intraday (1-min bars from backtest engine)

Entry logic
-----------
Long:
  1. EMA(trend) is rising  (large-trend filter)
  2. Price pulled back into EMA(fast)/EMA(slow) zone  -> price <= EMA(slow)
  3. Pullback depth >= min_pullback_pts below EMA(fast)
  4. RSI(short) < oversold threshold (structural stress)
  5. ADX >= adx_min  (market is trending, not chopping)
  6. VWAP alignment: price below VWAP (discount) for long
  7. Volume confirmation: bar volume above rolling average
  8. Not in force-close window

Short: mirror image.

Exit logic (StopPolicy)
-----------------------
  Initial stop  : entry +/- atr_sl_mult x ATR
  T1 target     : entry +/- atr_t1_mult x ATR  ->  move stop to breakeven
  EMA(slow) trail : once at breakeven, trail stop at EMA(slow) +/- trail_buf.
  Max hold bars : time-exit after N bars to prevent bleed.
  Force close   : 13:25-13:45 day / 04:50-05:00 night  ->  stop = price.

ATR approximation: SMA(|delta-close|, atr_len) x 1.6
"""
from __future__ import annotations

from collections import deque
from datetime import datetime, time
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
from src.strategies import StrategyCategory, StrategyTimeframe
from src.strategies._session_utils import in_day_session, in_force_close, in_night_session

if TYPE_CHECKING:
    from src.core.position_engine import PositionEngine


def _mean(vals: list[float]) -> float:
    return sum(vals) / len(vals)


PARAM_SCHEMA: dict[str, dict] = {
    "bar_agg": {
        "type": "int", "default": 3, "min": 1, "max": 15,
        "description": "Aggregate N raw bars into one before indicator update.",
        "grid": [1, 3, 5],
    },
    "ema_fast": {
        "type": "int", "default": 5, "min": 3, "max": 50,
        "description": "Fast EMA period (pullback zone upper).",
        "grid": [5, 8, 13],
    },
    "ema_slow": {
        "type": "int", "default": 34, "min": 10, "max": 80,
        "description": "Slow EMA period (pullback zone lower).",
        "grid": [15, 21, 34],
    },
    "ema_trend": {
        "type": "int", "default": 144, "min": 30, "max": 300,
        "description": "Trend EMA period (direction filter).",
    },
    "ema_align": {
        "type": "int", "default": 1, "min": 0, "max": 1,
        "description": "Require EMA alignment (fast>slow for long, fast<slow for short).",
        "grid": [0, 1],
    },
    "rsi_len": {
        "type": "int", "default": 3, "min": 2, "max": 7,
        "description": "Short RSI period for structural stress confirmation.",
        "grid": [3, 5],
    },
    "rsi_oversold": {
        "type": "float", "default": 35.0, "min": 10.0, "max": 50.0,
        "description": "RSI oversold threshold for long pullback entries.",
        "grid": [25.0, 30.0, 35.0, 40.0, 45.0],
    },
    "rsi_overbought": {
        "type": "float", "default": 65.0, "min": 55.0, "max": 90.0,
        "description": "RSI overbought threshold for short pullback entries.",
        "grid": [60.0, 65.0, 70.0, 75.0],
    },
    "vol_len": {
        "type": "int", "default": 20, "min": 5, "max": 100,
        "description": "Rolling window for volume average.",
        "grid": [10, 20],
    },
    "vol_mult": {
        "type": "float", "default": 0.8, "min": 0.5, "max": 2.0,
        "description": "Min volume spike vs rolling average for entry.",
        "grid": [0.8, 1.0, 1.2],
    },
    "vwap_filter": {
        "type": "int", "default": 1, "min": 0, "max": 1,
        "description": "Require VWAP directional alignment (1=on, 0=off).",
        "grid": [0, 1],
    },
    "min_pullback_pts": {
        "type": "float", "default": 3.0, "min": 2.0, "max": 30.0,
        "description": "Min pullback depth in points to filter wick touches.",
        "grid": [3.0, 5.0, 8.0, 12.0],
    },
    "atr_len": {
        "type": "int", "default": 10, "min": 5, "max": 50,
        "description": "ATR calculation period.",
    },
    "atr_sl_mult": {
        "type": "float", "default": 2.0, "min": 0.5, "max": 3.0,
        "description": "ATR multiplier for initial stop loss.",
        "grid": [1.5, 2.0, 2.5, 3.0],
    },
    "atr_t1_mult": {
        "type": "float", "default": 5.0, "min": 1.5, "max": 8.0,
        "description": "ATR multiplier for T1 target (breakeven trigger).",
        "grid": [3.0, 4.0, 5.0],
    },
    "atr_ceil": {
        "type": "float", "default": 0.0, "min": 0.0, "max": 5.0,
        "description": "Max ATR as multiple of rolling avg (0=disabled).",
        "grid": [0.0, 1.5, 2.0, 2.5],
    },
    "adx_len": {
        "type": "int", "default": 14, "min": 7, "max": 30,
        "description": "ADX calculation period.",
    },
    "adx_min": {
        "type": "float", "default": 30.0, "min": 10.0, "max": 40.0,
        "description": "Minimum ADX for entry (trend strength filter).",
        "grid": [20.0, 25.0, 30.0],
    },
    "ema_trail_buffer_pts": {
        "type": "float", "default": 5.0, "min": 0.0, "max": 20.0,
        "description": "Points buffer for EMA trail stop after breakeven.",
        "grid": [2.0, 5.0, 8.0],
    },
    "max_hold_bars": {
        "type": "int", "default": 120, "min": 10, "max": 300,
        "description": "Max bars to hold before time-exit.",
        "grid": [60, 90, 120, 180],
    },
    "allow_night": {
        "type": "int", "default": 1, "min": 0, "max": 1,
        "description": "Allow entries during night session (0=no, 1=yes).",
    },
}

STRATEGY_META: dict = {
    "category": StrategyCategory.TREND_FOLLOWING,
    "timeframe": StrategyTimeframe.INTRADAY,
    "session": "both",
    "bars_per_day": 1050,
    "presets": {
        "quick": {"n_bars": 21000, "note": "~1 month (20 trading days)"},
        "standard": {"n_bars": 63000, "note": "~3 months (60 trading days)"},
        "full_year": {"n_bars": 264600, "note": "~1 year (252 trading days)"},
    },
    "description": (
        "EMA Trend Pullback is an intraday trend-following strategy. "
        "Enters on pullbacks to EMA zone confirmed by RSI-3 stress, "
        "ADX >= 30 trend filter, and VWAP alignment. "
        "Exits via ATR T1 -> breakeven, then EMA trail. Max hold 120 bars."
    ),
}

_ATR_SCALE = 1.6


class _Indicators:
    """Rolling indicators with EMA-smoothed ADX, VWAP, volume, and bar aggregation."""

    def __init__(
        self,
        ema_fast: int,
        ema_slow: int,
        ema_trend: int,
        rsi_len: int,
        atr_len: int,
        adx_len: int,
        vol_len: int = 20,
        bar_agg: int = 1,
    ) -> None:
        self._n_fast = ema_fast
        self._n_slow = ema_slow
        self._n_trend = ema_trend
        self._rsi_len = rsi_len
        self._atr_len = atr_len
        self._adx_len = adx_len
        self._vol_len = vol_len
        self._bar_agg = max(bar_agg, 1)
        self._agg_count = 0
        max_buf = max(ema_trend + 2, rsi_len + 2, atr_len + 2, adx_len * 3)
        self._closes: deque[float] = deque(maxlen=max_buf + 1)
        self._volumes: deque[float] = deque(maxlen=max(vol_len, 1) + 1)
        self._last_ts: datetime | None = None
        self._last_vol: float = 0.0
        self._ema_fast_v: float | None = None
        self._ema_slow_v: float | None = None
        self._ema_trend_v: float | None = None
        self._ema_trend_prev: float | None = None
        self.ema_fast: float | None = None
        self.ema_slow: float | None = None
        self.ema_trend: float | None = None
        self.ema_trend_rising: bool | None = None
        self.rsi: float | None = None
        self.atr: float | None = None
        self.atr_avg: float | None = None
        self._atr_history: deque[float] = deque(maxlen=50)
        self.vol_ratio: float | None = None
        # EMA-smoothed ADX (responsive, like keltner_vwap_breakout)
        self.adx: float = 0.0
        self._prev_price: float | None = None
        self._adx_alpha = 2.0 / (adx_len + 1)
        self._plus_dm_ema: float | None = None
        self._minus_dm_ema: float | None = None
        self._atr_dm_ema: float | None = None
        self._adx_ema: float | None = None
        # VWAP (daily reset)
        self.vwap: float | None = None
        self._vwap_date = None
        self._cum_pv = 0.0
        self._cum_vol = 0.0

    def update(self, price: float, ts: datetime, volume: float = 0.0) -> None:
        if ts == self._last_ts:
            return
        self._last_ts = ts
        self._last_vol = volume
        self._update_vwap(ts, price, volume)
        self._update_adx(price)
        self._agg_count += 1
        if self._agg_count < self._bar_agg:
            return
        self._agg_count = 0
        self._closes.append(price)
        self._volumes.append(volume)
        self._compute(price)

    def _update_vwap(self, ts: datetime, price: float, volume: float) -> None:
        d = ts.date()
        if d != self._vwap_date:
            self._vwap_date = d
            self._cum_pv = 0.0
            self._cum_vol = 0.0
        self._cum_pv += price * max(volume, 0.0)
        self._cum_vol += max(volume, 0.0)
        self.vwap = self._cum_pv / self._cum_vol if self._cum_vol > 0 else None

    def _update_adx(self, price: float) -> None:
        """EMA-smoothed ADX — same responsive method as keltner_vwap_breakout."""
        if self._prev_price is None:
            self._prev_price = price
            return
        tr = abs(price - self._prev_price)
        delta = price - self._prev_price
        pdm = max(delta, 0.0)
        mdm = max(-delta, 0.0)
        a = self._adx_alpha
        if self._atr_dm_ema is None:
            self._atr_dm_ema = tr
            self._plus_dm_ema = pdm
            self._minus_dm_ema = mdm
        else:
            self._atr_dm_ema = a * tr + (1 - a) * self._atr_dm_ema
            self._plus_dm_ema = a * pdm + (1 - a) * self._plus_dm_ema
            self._minus_dm_ema = a * mdm + (1 - a) * self._minus_dm_ema
        if self._atr_dm_ema and self._atr_dm_ema > 1e-9:
            pdi = 100.0 * (self._plus_dm_ema / self._atr_dm_ema)
            mdi = 100.0 * (self._minus_dm_ema / self._atr_dm_ema)
            denom = pdi + mdi
            if denom > 1e-9:
                dx = 100.0 * abs(pdi - mdi) / denom
                if self._adx_ema is None:
                    self._adx_ema = dx
                else:
                    self._adx_ema = a * dx + (1 - a) * self._adx_ema
                self.adx = self._adx_ema
        self._prev_price = price

    @staticmethod
    def _ema_step(prev: float | None, price: float, n: int,
                  seed_closes: list[float]) -> float:
        if prev is None:
            if len(seed_closes) >= n:
                return _mean(seed_closes[-n:])
            return price
        k = 2.0 / (n + 1)
        return price * k + prev * (1.0 - k)

    def _compute(self, price: float) -> None:
        closes = list(self._closes)
        n = len(closes)
        self._ema_trend_prev = self._ema_trend_v
        self._ema_fast_v = self._ema_step(self._ema_fast_v, price, self._n_fast, closes)
        self._ema_slow_v = self._ema_step(self._ema_slow_v, price, self._n_slow, closes)
        self._ema_trend_v = self._ema_step(self._ema_trend_v, price, self._n_trend, closes)
        if n >= self._n_fast:
            self.ema_fast = self._ema_fast_v
        if n >= self._n_slow:
            self.ema_slow = self._ema_slow_v
        if n >= self._n_trend:
            self.ema_trend = self._ema_trend_v
            if self._ema_trend_prev is not None and self._ema_trend_v is not None:
                self.ema_trend_rising = self._ema_trend_v > self._ema_trend_prev
        if n >= self._atr_len + 1:
            diffs = [abs(closes[i] - closes[i - 1])
                     for i in range(n - self._atr_len, n)]
            self.atr = _mean(diffs) * _ATR_SCALE
            self._atr_history.append(self.atr)
            if len(self._atr_history) >= 10:
                self.atr_avg = _mean(list(self._atr_history))
        # RSI (simple, short-period structural stress)
        if n >= self._rsi_len + 1:
            changes = [closes[i] - closes[i - 1] for i in range(n - self._rsi_len, n)]
            gains = [c for c in changes if c > 0]
            losses = [-c for c in changes if c < 0]
            ag = _mean(gains) if gains else 0.0
            al = _mean(losses) if losses else 0.0
            self.rsi = 100.0 if al == 0 else 100.0 - 100.0 / (1.0 + ag / al)
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


class EMATrendPullbackEntry(EntryPolicy):
    """Enter on EMA pullback with RSI stress, ADX trend, and VWAP alignment."""

    def __init__(
        self,
        lots: float = 1.0,
        contract_type: str = "large",
        bar_agg: int = 3,
        ema_fast: int = 5,
        ema_slow: int = 21,
        ema_trend: int = 89,
        ema_align: int = 1,
        rsi_len: int = 3,
        rsi_oversold: float = 35.0,
        rsi_overbought: float = 65.0,
        vol_len: int = 20,
        vol_mult: float = 0.8,
        vwap_filter: int = 1,
        min_pullback_pts: float = 3.0,
        atr_len: int = 10,
        atr_sl_mult: float = 2.0,
        atr_t1_mult: float = 5.0,
        atr_ceil: float = 0.0,
        adx_len: int = 14,
        adx_min: float = 30.0,
        ema_trail_buffer_pts: float = 5.0,
        allow_night: int = 1,
        max_hold_bars: int = 120,
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
            vol_len=vol_len, bar_agg=bar_agg,
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
        if in_force_close(t):
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
        # Volume confirmation
        if ind.vol_ratio is not None and ind.vol_ratio < self._vol_mult:
            return None
        # Long: trend up, pullback into EMA zone, RSI oversold, VWAP discount
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
        # Short: trend down, pullback up, RSI overbought, VWAP premium
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
        atr_sl_mult: float = 2.0,
        atr_t1_mult: float = 5.0,
        ema_trail_buffer_pts: float = 5.0,
        max_hold_bars: int = 120,
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
        t = snapshot.timestamp.time()
        stop = position.stop_level
        entry = position.entry_price
        pid = position.position_id
        self._bar_counts[pid] = self._bar_counts.get(pid, 0) + 1
        # Force close: session end or max hold
        if in_force_close(t) or self._bar_counts[pid] >= self._max_hold:
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
    bar_agg: int = 3,
    ema_fast: int = 5,
    ema_slow: int = 21,
    ema_trend: int = 89,
    ema_align: int = 1,
    rsi_len: int = 3,
    rsi_oversold: float = 35.0,
    rsi_overbought: float = 65.0,
    vol_len: int = 20,
    vol_mult: float = 0.8,
    vwap_filter: int = 1,
    min_pullback_pts: float = 3.0,
    atr_len: int = 10,
    atr_sl_mult: float = 2.0,
    atr_t1_mult: float = 5.0,
    atr_ceil: float = 0.0,
    adx_len: int = 14,
    adx_min: float = 30.0,
    ema_trail_buffer_pts: float = 5.0,
    max_hold_bars: int = 120,
    allow_night: int = 1,
) -> "PositionEngine":
    """Build a PositionEngine wired with the EMA Trend Pullback strategy."""
    from src.core.position_engine import PositionEngine

    entry = EMATrendPullbackEntry(
        lots=lots, contract_type=contract_type, bar_agg=bar_agg,
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
    return PositionEngine(
        entry_policy=entry,
        add_policy=NoAddPolicy(),
        stop_policy=stop,
        config=EngineConfig(max_loss=max_loss),
    )
