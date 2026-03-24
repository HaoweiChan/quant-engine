"""EMA Trend Pullback Strategy (intraday bars, TAIFEX TX/MTX).

Strategy class: Trend-following / pullback
Timeframe     : Intraday (1-min bars from backtest engine)

Entry logic
-----------
Long:
  1. EMA(trend) is rising  (large-trend filter)
  2. Price pulled back into EMA(fast)/EMA(slow) zone  -> price <= EMA(slow)
  3. Pullback depth >= min_pullback_pts below EMA(fast)
  4. StochRSI %K crossed UP through %D within stoch_cross_lookback bars
  5. StochRSI %K was below stoch_oversold before that cross
  6. ADX >= adx_min  (market is trending, not chopping)
  7. Not in force-close window

Short: mirror image.

Exit logic (StopPolicy)
-----------------------
  Initial stop  : entry +/- atr_sl_mult x ATR
  T1 target     : entry +/- atr_t1_mult x ATR  ->  move stop to breakeven
  EMA(slow) trail : once at breakeven, trail stop at EMA(slow) +/- trail_buf.
  Force close   : 13:25-13:45 day / 04:50-05:00 night  ->  stop = price.

ATR approximation: SMA(|delta-close|, atr_len) x 1.6
"""
from __future__ import annotations

from collections import deque
from datetime import datetime, time
from typing import TYPE_CHECKING


def _mean(vals: list[float]) -> float:
    return sum(vals) / len(vals)

from src.core.policies import EntryPolicy, NoAddPolicy, StopPolicy
from src.core.types import (
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


PARAM_SCHEMA: dict[str, dict] = {
    "bar_agg":       {"type": "int",   "default": 5,    "min": 1,    "max": 15,
                      "description": "Aggregate N raw bars into one before indicator update (e.g. 5 = 5-min bars from 1-min feed).",
                      "grid": [1, 3, 5, 10]},
    "ema_fast":      {"type": "int",   "default": 13,   "min": 3,    "max": 50,
                      "description": "Fast EMA period (pullback zone upper).",
                      "grid": [5, 8, 13]},
    "ema_slow":      {"type": "int",   "default": 34,   "min": 10,   "max": 80,
                      "description": "Slow EMA period (pullback zone lower).",
                      "grid": [15, 21, 34]},
    "ema_trend":     {"type": "int",   "default": 144,  "min": 30,   "max": 300,
                      "description": "Trend EMA period (direction filter)."},
    "ema_align":     {"type": "int",   "default": 1,    "min": 0,    "max": 1,
                      "description": "Require EMA alignment (fast>slow for long, fast<slow for short).",
                      "grid": [0, 1]},
    "stoch_rsi_len": {"type": "int",   "default": 14,   "min": 5,    "max": 30,
                      "description": "RSI period for StochRSI calculation."},
    "stoch_k":       {"type": "int",   "default": 3,    "min": 2,    "max": 10,
                      "description": "StochRSI %K smoothing period."},
    "stoch_d":       {"type": "int",   "default": 3,    "min": 2,    "max": 10,
                      "description": "StochRSI %D smoothing period."},
    "stoch_oversold":      {"type": "float", "default": 15.0, "min": 5.0,  "max": 40.0,
                            "description": "StochRSI oversold threshold for long entries.",
                            "grid": [15.0, 20.0, 25.0, 30.0]},
    "stoch_overbought":    {"type": "float", "default": 85.0, "min": 60.0, "max": 95.0,
                            "description": "StochRSI overbought threshold for short entries.",
                            "grid": [70.0, 75.0, 80.0, 85.0]},
    "stoch_cross_lookback": {"type": "int",  "default": 3,   "min": 2,    "max": 8,
                             "description": "Bars to look back for StochRSI cross.",
                             "grid": [2, 3, 4, 5]},
    "min_pullback_pts":    {"type": "float", "default": 15.0, "min": 2.0,  "max": 30.0,
                            "description": "Min pullback depth in points to filter wick touches.",
                            "grid": [3.0, 5.0, 8.0, 12.0, 15.0]},
    "atr_len":       {"type": "int",   "default": 10,   "min": 5,    "max": 50,
                      "description": "ATR calculation period."},
    "atr_sl_mult":   {"type": "float", "default": 1.5,  "min": 0.8,  "max": 5.0,
                      "description": "ATR multiplier for initial stop loss.",
                      "grid": [1.0, 1.2, 1.5, 2.0, 2.5]},
    "atr_t1_mult":   {"type": "float", "default": 2.5,  "min": 1.5,  "max": 8.0,
                      "description": "ATR multiplier for T1 target (breakeven trigger).",
                      "grid": [2.0, 2.5, 3.0, 4.0, 5.0]},
    "atr_ceil":      {"type": "float", "default": 0.0,  "min": 0.0,  "max": 5.0,
                      "description": "Max ATR as multiple of rolling avg (0=disabled). Blocks entries in volatile chop.",
                      "grid": [0.0, 1.5, 2.0, 2.5]},
    "adx_len":       {"type": "int",   "default": 14,   "min": 7,    "max": 30,
                      "description": "ADX calculation period."},
    "adx_min":       {"type": "float", "default": 30.0, "min": 10.0, "max": 35.0,
                      "description": "Minimum ADX for entry (trend strength filter).",
                      "grid": [15.0, 18.0, 20.0, 22.0, 25.0, 30.0]},
    "ema_trail_buffer_pts": {"type": "float", "default": 5.0, "min": 0.0, "max": 20.0,
                             "description": "Points buffer for EMA trail stop.",
                             "grid": [2.0, 5.0, 8.0, 10.0]},
    "allow_night":   {"type": "int",   "default": 0,    "min": 0,    "max": 1,
                      "description": "Allow entries during night session (0=no, 1=yes)."},
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
        "Enters on pullbacks to EMA zone confirmed by StochRSI cross and ADX filter. "
        "Exits via ATR T1 -> breakeven, then EMA trail."
    ),
}

_ATR_SCALE = 1.6


class _Indicators:
    """Rolling indicators fed one bar close at a time, with optional bar aggregation."""

    def __init__(
        self,
        ema_fast: int,
        ema_slow: int,
        ema_trend: int,
        stoch_rsi_len: int,
        stoch_k: int,
        stoch_d: int,
        atr_len: int,
        adx_len: int,
        bar_agg: int = 1,
    ) -> None:
        self._n_fast = ema_fast
        self._n_slow = ema_slow
        self._n_trend = ema_trend
        self._srsi_len = stoch_rsi_len
        self._stoch_k = stoch_k
        self._stoch_d = stoch_d
        self._atr_len = atr_len
        self._adx_len = adx_len
        self._bar_agg = max(bar_agg, 1)
        self._agg_count = 0
        max_buf = max(ema_trend + 2,
                      stoch_rsi_len + stoch_k + stoch_d + 4,
                      atr_len + 2,
                      adx_len * 3)
        self._closes: deque[float] = deque(maxlen=max_buf + 1)
        self._last_ts: datetime | None = None
        self._ema_fast_v: float | None = None
        self._ema_slow_v: float | None = None
        self._ema_trend_v: float | None = None
        self._ema_trend_prev: float | None = None
        self.ema_fast: float | None = None
        self.ema_slow: float | None = None
        self.ema_trend: float | None = None
        self.ema_trend_rising: bool | None = None
        self.stoch_k_val: float | None = None
        self.stoch_d_val: float | None = None
        self._k_hist: deque[float] = deque(maxlen=20)
        self._d_hist: deque[float] = deque(maxlen=20)
        self.atr: float | None = None
        self.atr_avg: float | None = None
        self._atr_history: deque[float] = deque(maxlen=50)
        self.adx: float | None = None
        self._prev_close: float | None = None
        self._sm_tr: float | None = None
        self._sm_plus_dm: float | None = None
        self._sm_minus_dm: float | None = None
        self._dx_buf: deque[float] = deque(maxlen=adx_len + 1)

    def update(self, price: float, ts: datetime) -> None:
        if ts == self._last_ts:
            return
        self._last_ts = ts
        self._agg_count += 1
        if self._agg_count < self._bar_agg:
            return
        self._agg_count = 0
        self._closes.append(price)
        self._compute(price)

    def stoch_cross_up_within(self, lookback: int, oversold: float) -> bool:
        """True if %K crossed above %D within lookback bars from oversold."""
        ks = list(self._k_hist)
        ds = list(self._d_hist)
        n = min(len(ks), len(ds))
        if n < 2:
            return False
        w = min(lookback + 1, n)
        ks, ds = ks[-w:], ds[-w:]
        for i in range(1, len(ks)):
            if ks[i] > ds[i] and ks[i - 1] <= ds[i - 1]:
                if any(k < oversold for k in ks[:i]):
                    return True
        return False

    def stoch_cross_down_within(self, lookback: int, overbought: float) -> bool:
        """True if %K crossed below %D within lookback bars from overbought."""
        ks = list(self._k_hist)
        ds = list(self._d_hist)
        n = min(len(ks), len(ds))
        if n < 2:
            return False
        w = min(lookback + 1, n)
        ks, ds = ks[-w:], ds[-w:]
        for i in range(1, len(ks)):
            if ks[i] < ds[i] and ks[i - 1] >= ds[i - 1]:
                if any(k > overbought for k in ks[:i]):
                    return True
        return False

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
        self._compute_stoch_rsi(closes)
        self._compute_adx(price)

    def _rsi_from_slice(self, window: list[float]) -> float | None:
        if len(window) < self._srsi_len + 1:
            return None
        changes = [window[i] - window[i - 1] for i in range(1, len(window))]
        gains = [c for c in changes if c > 0]
        losses = [-c for c in changes if c < 0]
        ag = _mean(gains) if gains else 0.0
        al = _mean(losses) if losses else 0.0
        if al == 0:
            return 100.0
        return 100.0 - 100.0 / (1.0 + ag / al)

    def _compute_stoch_rsi(self, closes: list[float]) -> None:
        need = self._srsi_len + self._stoch_k + self._stoch_d + 2
        if len(closes) < need:
            return
        rsi_series: list[float] = []
        total_needed = self._stoch_k + self._stoch_d
        for lag in range(total_needed - 1, -1, -1):
            end = len(closes) - lag
            sub = closes[max(0, end - self._srsi_len - 1): end]
            r = self._rsi_from_slice(sub)
            if r is None:
                return
            rsi_series.append(r)
        raw_k: list[float] = []
        for i in range(len(rsi_series) - self._stoch_k + 1):
            w = rsi_series[i: i + self._stoch_k]
            lo, hi = min(w), max(w)
            raw_k.append(0.0 if hi == lo else (w[-1] - lo) / (hi - lo) * 100.0)
        if len(raw_k) < self._stoch_d:
            return
        k = raw_k[-1]
        d = _mean(raw_k[-self._stoch_d:])
        self._k_hist.append(k)
        self._d_hist.append(d)
        self.stoch_k_val = k
        self.stoch_d_val = d

    def _compute_adx(self, price: float) -> None:
        if self._prev_close is None:
            self._prev_close = price
            return
        prev = self._prev_close
        self._prev_close = price
        tr = abs(price - prev)
        plus_dm = max(price - prev, 0.0)
        minus_dm = max(prev - price, 0.0)
        if plus_dm == minus_dm:
            plus_dm = minus_dm = 0.0
        elif plus_dm < minus_dm:
            plus_dm = 0.0
        else:
            minus_dm = 0.0
        n = float(self._adx_len)
        if self._sm_tr is None:
            self._sm_tr = tr
            self._sm_plus_dm = plus_dm
            self._sm_minus_dm = minus_dm
        else:
            self._sm_tr = self._sm_tr - self._sm_tr / n + tr
            self._sm_plus_dm = self._sm_plus_dm - self._sm_plus_dm / n + plus_dm
            self._sm_minus_dm = self._sm_minus_dm - self._sm_minus_dm / n + minus_dm
        if self._sm_tr and self._sm_tr > 0:
            pdi = 100.0 * self._sm_plus_dm / self._sm_tr
            mdi = 100.0 * self._sm_minus_dm / self._sm_tr
            denom = pdi + mdi
            dx = 100.0 * abs(pdi - mdi) / denom if denom > 0 else 0.0
            self._dx_buf.append(dx)
            if len(self._dx_buf) >= self._adx_len:
                self.adx = _mean(list(self._dx_buf)[-self._adx_len:])


class EMATrendPullbackEntry(EntryPolicy):
    """Enter on EMA pullback with StochRSI reset and ADX trend filter."""

    def __init__(
        self,
        lots: float = 1.0,
        contract_type: str = "large",
        bar_agg: int = 5,
        ema_fast: int = 8,
        ema_slow: int = 21,
        ema_trend: int = 89,
        ema_align: int = 1,
        stoch_rsi_len: int = 14,
        stoch_k: int = 3,
        stoch_d: int = 3,
        stoch_oversold: float = 20.0,
        stoch_overbought: float = 80.0,
        stoch_cross_lookback: int = 3,
        min_pullback_pts: float = 8.0,
        atr_len: int = 10,
        atr_sl_mult: float = 1.5,
        atr_t1_mult: float = 2.5,
        atr_ceil: float = 0.0,
        adx_len: int = 14,
        adx_min: float = 20.0,
        ema_trail_buffer_pts: float = 2.0,
        allow_night: int = 0,
    ) -> None:
        self._lots = lots
        self._contract_type = contract_type
        self._ema_align = bool(ema_align)
        self._stoch_oversold = stoch_oversold
        self._stoch_overbought = stoch_overbought
        self._stoch_cross_lookback = stoch_cross_lookback
        self._min_pullback = min_pullback_pts
        self._atr_sl_mult = atr_sl_mult
        self._atr_t1_mult = atr_t1_mult
        self._atr_ceil = atr_ceil
        self._adx_min = adx_min
        self._allow_night = bool(allow_night)
        self.ind = _Indicators(
            ema_fast=ema_fast, ema_slow=ema_slow, ema_trend=ema_trend,
            stoch_rsi_len=stoch_rsi_len, stoch_k=stoch_k, stoch_d=stoch_d,
            atr_len=atr_len, adx_len=adx_len, bar_agg=bar_agg,
        )

    def should_enter(
        self,
        snapshot: MarketSnapshot,
        signal: MarketSignal | None,
        engine_state: EngineState,
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
        self.ind.update(price, snapshot.timestamp)
        ind = self.ind
        if any(v is None for v in (
            ind.ema_fast, ind.ema_slow, ind.ema_trend,
            ind.ema_trend_rising, ind.stoch_k_val, ind.stoch_d_val, ind.atr,
        )):
            return None
        if ind.adx is not None and ind.adx < self._adx_min:
            return None
        atr = ind.atr
        if atr is None or atr <= 0:
            return None
        # Volatility ceiling: skip entries in abnormally volatile chop
        if self._atr_ceil > 0 and ind.atr_avg is not None and ind.atr_avg > 0:
            if atr > self._atr_ceil * ind.atr_avg:
                return None
        # Long: trend up, price in pullback zone, StochRSI cross from oversold
        if ind.ema_trend_rising is True:
            if self._ema_align and ind.ema_fast <= ind.ema_slow:
                pass  # EMAs not properly stacked for long
            else:
                in_zone = price <= ind.ema_slow
                deep_enough = (ind.ema_fast - price) >= self._min_pullback
                stoch_ok = ind.stoch_cross_up_within(
                    self._stoch_cross_lookback, self._stoch_oversold)
                if in_zone and deep_enough and stoch_ok:
                    return EntryDecision(
                        lots=self._lots, contract_type=self._contract_type,
                        initial_stop=price - atr * self._atr_sl_mult,
                        direction="long",
                        metadata={
                            "atr": atr, "ema_fast": ind.ema_fast,
                            "ema_slow": ind.ema_slow,
                            "t1_target": price + atr * self._atr_t1_mult,
                            "stoch_k": ind.stoch_k_val, "adx": ind.adx,
                            "strategy": "ema_trend_pullback",
                        },
                    )
        # Short: trend down, price in pullback zone, StochRSI cross from overbought
        if ind.ema_trend_rising is False:
            if self._ema_align and ind.ema_fast >= ind.ema_slow:
                pass  # EMAs not properly stacked for short
            else:
                in_zone = price >= ind.ema_slow
                deep_enough = (price - ind.ema_fast) >= self._min_pullback
                stoch_ok = ind.stoch_cross_down_within(
                    self._stoch_cross_lookback, self._stoch_overbought)
                if in_zone and deep_enough and stoch_ok:
                    return EntryDecision(
                        lots=self._lots, contract_type=self._contract_type,
                        initial_stop=price + atr * self._atr_sl_mult,
                        direction="short",
                        metadata={
                            "atr": atr, "ema_fast": ind.ema_fast,
                            "ema_slow": ind.ema_slow,
                            "t1_target": price - atr * self._atr_t1_mult,
                            "stoch_k": ind.stoch_k_val, "adx": ind.adx,
                            "strategy": "ema_trend_pullback",
                        },
                    )
        return None


class EMATrendPullbackStop(StopPolicy):
    """ATR T1 -> breakeven, then EMA(slow) trailing close exit."""

    def __init__(
        self,
        indicators: _Indicators,
        atr_sl_mult: float = 1.5,
        atr_t1_mult: float = 2.5,
        ema_trail_buffer_pts: float = 2.0,
    ) -> None:
        self._ind = indicators
        self._atr_sl_mult = atr_sl_mult
        self._atr_t1_mult = atr_t1_mult
        self._trail_buf = ema_trail_buffer_pts
        self._t1_target: float | None = None
        self._at_breakeven: bool = False

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
        self._ind.update(snapshot.price, snapshot.timestamp)
        price = snapshot.price
        t = snapshot.timestamp.time()
        stop = position.stop_level
        entry = position.entry_price
        if in_force_close(t):
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
    max_loss: float = 150_000,
    lots: float = 1.0,
    contract_type: str = "large",
    bar_agg: int = 5,
    ema_fast: int = 8,
    ema_slow: int = 21,
    ema_trend: int = 89,
    ema_align: int = 1,
    stoch_rsi_len: int = 14,
    stoch_k: int = 3,
    stoch_d: int = 3,
    stoch_oversold: float = 20.0,
    stoch_overbought: float = 80.0,
    stoch_cross_lookback: int = 3,
    min_pullback_pts: float = 8.0,
    atr_len: int = 10,
    atr_sl_mult: float = 1.5,
    atr_t1_mult: float = 2.5,
    atr_ceil: float = 0.0,
    adx_len: int = 14,
    adx_min: float = 20.0,
    ema_trail_buffer_pts: float = 2.0,
    allow_night: int = 0,
) -> "PositionEngine":
    """Build a PositionEngine wired with the EMA Trend Pullback strategy."""
    from src.core.position_engine import PositionEngine

    entry = EMATrendPullbackEntry(
        lots=lots, contract_type=contract_type, bar_agg=bar_agg,
        ema_fast=ema_fast, ema_slow=ema_slow, ema_trend=ema_trend,
        ema_align=ema_align,
        stoch_rsi_len=stoch_rsi_len, stoch_k=stoch_k, stoch_d=stoch_d,
        stoch_oversold=stoch_oversold, stoch_overbought=stoch_overbought,
        stoch_cross_lookback=stoch_cross_lookback,
        min_pullback_pts=min_pullback_pts,
        atr_len=atr_len, atr_sl_mult=atr_sl_mult, atr_t1_mult=atr_t1_mult,
        atr_ceil=atr_ceil,
        adx_len=adx_len, adx_min=adx_min,
        ema_trail_buffer_pts=ema_trail_buffer_pts,
        allow_night=allow_night,
    )
    stop = EMATrendPullbackStop(
        indicators=entry.ind,
        atr_sl_mult=atr_sl_mult,
        atr_t1_mult=atr_t1_mult,
        ema_trail_buffer_pts=ema_trail_buffer_pts,
    )
    return PositionEngine(
        entry_policy=entry,
        add_policy=NoAddPolicy(),
        stop_policy=stop,
        config=EngineConfig(max_loss=max_loss),
    )
