"""Medium-Term Macro-Aligned TA-ORB Strategy.

Adapted from the short-term TA-ORB for multi-session holding.
OR-range-based stop sizing with EMA trail for overnight holds.

Strategy logic:
  Opening Range  : built from bars in [08:45, 09:00)  (day session only)
  Trend filter   : N-day close slope determines bullish / bearish / neutral
  Entry (long)   : Only if trend is BULLISH.
                   Close > OR_high * threshold_mult
  Entry (short)  : Only if trend is BEARISH.
                   Close < OR_low  / threshold_mult

Exit (StopPolicy — OR-range based):
  - Initial stop at opposite OR boundary, capped at stop_or_mult * OR_range
  - T1 at t1_rr_mult * R (where R = initial risk) → move to breakeven
  - EMA(slow) trail after breakeven, with buffer
  - Trend reversal tightens stop to breakeven (not immediate close)
  - Max hold bars time-exit
  - No forced session close — holds overnight
"""
from __future__ import annotations

from collections import deque
from datetime import date, datetime, time, timedelta
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
from src.strategies import HoldingPeriod, SignalTimeframe, StopArchitecture, StrategyCategory
from src.strategies._session_utils import in_day_session, in_night_session, in_night_or_window, in_or_window

if TYPE_CHECKING:
    from src.core.position_engine import PositionEngine


def _mean(vals: list[float]) -> float:
    return sum(vals) / len(vals)


PARAM_SCHEMA: dict[str, dict] = {
    "trend_n_days": {
        "type": "int", "default": 8, "min": 3, "max": 20,
        "description": "N-day lookback for slope-based trend filter.",
        "grid": [5, 8, 12],
    },
    "min_slope_pct": {
        "type": "float", "default": 0.0003, "min": 0.0001, "max": 0.003,
        "description": "Minimum daily slope fraction to declare a trend.",
        "grid": [0.0002, 0.0003, 0.0005],
    },
    "trend_threshold_mult": {
        "type": "float", "default": 1.0, "min": 1.0, "max": 1.01,
        "description": "OR breakout multiplier when trend is confirmed (TA part).",
        "grid": [1.0, 1.001, 1.002],
    },
    "min_or_width_pct": {
        "type": "float", "default": 0.001, "min": 0.0003, "max": 0.005,
        "description": "Minimum OR width as fraction of price (low-vol filter).",
    },
    "max_or_width_pct": {
        "type": "float", "default": 0.03, "min": 0.005, "max": 0.05,
        "description": "Maximum OR width as fraction of price (gap filter).",
    },
    "stop_or_mult": {
        "type": "float", "default": 1.5, "min": 0.5, "max": 3.0,
        "description": "Max initial stop distance as multiple of OR range.",
        "grid": [1.0, 1.5, 2.0],
    },
    "t1_rr_mult": {
        "type": "float", "default": 2.0, "min": 1.0, "max": 5.0,
        "description": "T1 target as multiple of initial risk (R). At 2R move to breakeven.",
        "grid": [1.5, 2.0, 2.5, 3.0],
    },
    "ema_fast": {
        "type": "int", "default": 5, "min": 3, "max": 30,
        "description": "Fast EMA period on 15m bars.",
        "grid": [3, 5, 8, 13],
    },
    "ema_slow": {
        "type": "int", "default": 13, "min": 5, "max": 50,
        "description": "Slow EMA period on 15m bars (trail stop reference).",
        "grid": [8, 13, 21, 34],
    },
    "atr_len": {
        "type": "int", "default": 10, "min": 5, "max": 30,
        "description": "ATR calculation period (on 15m bars, used for ATR ceiling).",
    },
    "atr_ceil": {
        "type": "float", "default": 0.0, "min": 0.0, "max": 5.0,
        "description": "Max ATR as multiple of rolling avg (0=disabled). Blocks volatile entries.",
        "grid": [0.0, 1.5, 2.0, 2.5],
    },
    "ema_trail_buffer_pts": {
        "type": "float", "default": 12.0, "min": 0.0, "max": 30.0,
        "description": "Points buffer for EMA trail stop after breakeven.",
        "grid": [5.0, 8.0, 10.0, 12.0, 15.0],
    },
    "max_hold_bars": {
        "type": "int", "default": 200, "min": 4, "max": 300,
        "description": "Max 15m bars to hold before time-exit (200 bars = ~50h).",
        "grid": [96, 144, 200, 240, 300],
    },
    "allow_night": {
        "type": "int", "default": 1, "min": 0, "max": 1,
        "description": "Allow entries during night session (0=day only, 1=day+night).",
    },
    "require_vwap": {
        "type": "int", "default": 1, "min": 0, "max": 1,
        "description": "Require VWAP confirmation: long above VWAP, short below (0=disabled, 1=enabled).",
    },
    "trend_mode": {
        "type": "int", "default": 1, "min": 0, "max": 1,
        "description": "Trend filter mode: 0=N-day slope, 1=EMA fast/slow crossover.",
        "grid": [0, 1],
    },
    "ema_spread_min": {
        "type": "float", "default": 0.0, "min": 0.0, "max": 0.01,
        "description": "Min |EMA_fast - EMA_slow| / price to enter. 0=disabled. Filters weak trends.",
        "grid": [0.0, 0.001, 0.002, 0.003, 0.005],
    },
    "or_atr_min": {
        "type": "float", "default": 0.0, "min": 0.0, "max": 2.0,
        "description": "Min OR range / ATR ratio to enter. 0=disabled. Filters weak ORs.",
        "grid": [0.0, 0.3, 0.5, 0.7],
    },
    "or_atr_max": {
        "type": "float", "default": 0.0, "min": 0.0, "max": 5.0,
        "description": "Max OR range / ATR ratio to enter. 0=disabled. Filters gap ORs.",
        "grid": [0.0, 1.5, 2.0, 3.0],
    },
    "max_pyramid_levels": {
        "type": "int", "default": 4, "min": 1, "max": 4,
        "description": "Max pyramid levels (1=no adds, 4=entry + 3 adds with gamma decay).",
        "grid": [1, 2, 3, 4],
    },
    "pyramid_gamma": {
        "type": "float", "default": 0.7, "min": 0.3, "max": 1.0,
        "description": "Anti-martingale decay: Size_k = base_lots * gamma^k.",
        "grid": [0.5, 0.7, 0.85],
    },
    "pyramid_trigger_atr": {
        "type": "float", "default": 1.5, "min": 0.5, "max": 5.0,
        "description": "ATR multiple for first add trigger. Level N triggers at N * this value.",
        "grid": [1.0, 1.5, 2.0, 3.0],
    },
    "latest_night_entry_hour": {
        "type": "int", "default": 20, "min": 17, "max": 23,
        "description": "Latest hour (HH:00) to allow night session entries. 0=disabled.",
        "grid": [18, 20, 22],
    },
    "adx_period": {
        "type": "int", "default": 14, "min": 7, "max": 21,
        "description": "Smoothing period for ADX regime strength indicator.",
        "grid": [10, 14, 18],
    },
    "adx_threshold": {
        "type": "float", "default": 25.0, "min": 0.0, "max": 35.0,
        "description": "Min ADX score to permit breakout entries. 0=disabled.",
        "grid": [0.0, 22.0, 25.0, 30.0],
    },
    "vol_len": {
        "type": "int", "default": 20, "min": 5, "max": 60,
        "description": "Rolling window for volume average.",
    },
    "vol_mult": {
        "type": "float", "default": 0.0, "min": 0.0, "max": 3.0,
        "description": "Min volume spike vs rolling avg for entry confirmation. 0=disabled.",
        "grid": [0.0, 1.0, 1.2, 1.5],
    },
    "macro_ma_len": {
        "type": "int", "default": 60, "min": 20, "max": 200,
        "description": "Slow MA period for macro trend distance filter.",
    },
    "macro_filter_atr": {
        "type": "float", "default": 0.0, "min": 0.0, "max": 8.0,
        "description": "Block entry if |price - macro_ma| > N*ATR. 0=disabled.",
        "grid": [0.0, 4.0, 5.0, 6.0],
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
        "Medium-term Macro-Aligned TA-ORB: Opening Range Breakout with N-day slope "
        "trend filter. OR-range-based stops (initial at opposite OR boundary, T1 at 2R). "
        "Entries on day session OR breakout, holds overnight. EMA trail after breakeven. "
        "Pyramid support."
    ),
    "paper": "Modified ORB Strategies with Threshold Adjusting on Taiwan Futures Market (IEEE 2019)",
}

_ATR_SCALE = 1.6


# ---------------------------------------------------------------------------
# Indicators — EMA fast/slow (trail), ATR (ceiling filter), VWAP
# ---------------------------------------------------------------------------

class _Indicators:
    """Rolling indicators for medium-term TA-ORB."""

    def __init__(
        self,
        ema_fast: int,
        ema_slow: int,
        atr_len: int,
        adx_period: int = 14,
        vol_len: int = 20,
        macro_ma_len: int = 60,
    ) -> None:
        self._n_fast = ema_fast
        self._n_slow = ema_slow
        self._atr_len = atr_len
        self._adx_period = adx_period
        self._vol_len = vol_len
        self._macro_ma_len = macro_ma_len

        max_buf = max(ema_fast + 2, ema_slow + 2, atr_len + 2)
        self._closes: deque[float] = deque(maxlen=max_buf + 1)
        self._last_ts: datetime | None = None

        self._ema_fast_v: float | None = None
        self._ema_slow_v: float | None = None

        self.ema_fast: float | None = None
        self.ema_slow: float | None = None
        self.atr: float | None = None
        self.atr_avg: float | None = None
        self._atr_history: deque[float] = deque(maxlen=50)

        # VWAP (resets per calendar date)
        self.vwap: float | None = None
        self._vwap_date = None
        self._cum_pv = 0.0
        self._cum_vol = 0.0

        # ADX regime filter (smoothed directional movement)
        self.adx: float = 0.0
        self._dm_alpha = 1.0 / max(adx_period, 1)
        self._plus_dm: float = 0.0
        self._minus_dm: float = 0.0
        self._last_price: float | None = None

        # Volume confirmation
        self._vol_history: deque[float] = deque(maxlen=vol_len)
        self.vol_ratio: float | None = None

        # Macro MA for extreme-trend filter
        self._macro_ema: float | None = None
        self.macro_ma: float | None = None

    def update(self, price: float, ts: datetime, volume: float = 0.0) -> None:
        if ts == self._last_ts:
            return
        self._last_ts = ts
        self._closes.append(price)
        self._update_vwap(ts, price, volume)
        self._update_adx(price)
        self._update_volume(volume)
        self._update_macro_ma(price)
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
        if self._last_price is None:
            self._last_price = price
            return
        delta = price - self._last_price
        tr = abs(delta)
        up_move = max(delta, 0.0)
        down_move = max(-delta, 0.0)
        self._plus_dm += self._dm_alpha * (up_move - self._plus_dm)
        self._minus_dm += self._dm_alpha * (down_move - self._minus_dm)
        atr_val = max(
            self._plus_dm + self._minus_dm, 1e-6
        ) if tr == 0 else max(tr, 1e-6)
        # Use smoothed TR for DI normalization
        plus_di = 100.0 * (self._plus_dm / max(self._plus_dm + self._minus_dm, 1e-6))
        minus_di = 100.0 * (self._minus_dm / max(self._plus_dm + self._minus_dm, 1e-6))
        dx = 100.0 * abs(plus_di - minus_di) / max(plus_di + minus_di, 1e-6)
        self.adx += self._dm_alpha * (dx - self.adx)
        self._last_price = price

    def _update_volume(self, volume: float) -> None:
        self._vol_history.append(max(volume, 0.0))
        if len(self._vol_history) >= 5:
            avg = _mean(list(self._vol_history))
            self.vol_ratio = volume / avg if avg > 0 else None
        else:
            self.vol_ratio = None

    def _update_macro_ma(self, price: float) -> None:
        k = 2.0 / (self._macro_ma_len + 1)
        if self._macro_ema is None:
            self._macro_ema = price
        else:
            self._macro_ema = price * k + self._macro_ema * (1.0 - k)
        if len(self._closes) >= self._macro_ma_len:
            self.macro_ma = self._macro_ema

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

        self._ema_fast_v = self._ema_step(self._ema_fast_v, price, self._n_fast, closes)
        self._ema_slow_v = self._ema_step(self._ema_slow_v, price, self._n_slow, closes)
        if n >= self._n_fast:
            self.ema_fast = self._ema_fast_v
        if n >= self._n_slow:
            self.ema_slow = self._ema_slow_v

        if n >= self._atr_len + 1:
            diffs = [abs(closes[i] - closes[i - 1])
                     for i in range(n - self._atr_len, n)]
            self.atr = _mean(diffs) * _ATR_SCALE
            self._atr_history.append(self.atr)
            if len(self._atr_history) >= 10:
                self.atr_avg = _mean(list(self._atr_history))

    def snapshot(self) -> dict[str, float | None]:
        return {
            "ema_fast": self.ema_fast,
            "ema_slow": self.ema_slow,
            "vwap": self.vwap,
            "adx": self.adx,
        }

    def indicator_meta(self) -> dict[str, dict]:
        return {
            "ema_fast":  {"panel": "price", "color": "#FF6B6B", "label": "EMA Fast"},
            "ema_slow":  {"panel": "price", "color": "#4ECDC4", "label": "EMA Slow"},
            "vwap":      {"panel": "price", "color": "#95E1D3", "label": "VWAP"},
            "adx":       {"panel": "oscillator", "color": "#FFD93D", "label": "ADX"},
        }


# ---------------------------------------------------------------------------
# Per-day ORB state
# ---------------------------------------------------------------------------

class _ORBState:
    """Tracks per-session state needed for one TA-ORB cycle.

    Supports both day session (OR window 08:45-09:00) and night session
    (OR window 15:15-15:30).  Each session gets its own OR range and
    traded flag so the strategy can fire up to one entry per session.
    """

    def __init__(self) -> None:
        self._current_session_key: str | None = None
        self.or_high: float | None = None
        self.or_low: float | None = None
        self.or_frozen: bool = False
        self.traded_session: bool = False
        self.long_threshold: float = 1.0
        self.short_threshold: float = 1.0
        self.or_range: float = 0.0
        self.entry_direction: str | None = None

    @staticmethod
    def _session_key(ts: datetime) -> str:
        """Return a unique key per session: 'day:YYYY-MM-DD' or 'night:YYYY-MM-DD'."""
        t = ts.time()
        if in_day_session(t):
            return f"day:{ts.date()}"
        # Night session spans midnight: 15:15→05:00+1d.
        # Bars before midnight belong to the same night as bars after.
        if t >= time(15, 0):
            return f"night:{ts.date()}"
        return f"night:{ts.date() - timedelta(days=1)}"

    def reset_if_new_session(self, ts: datetime) -> None:
        key = self._session_key(ts)
        if key != self._current_session_key:
            self._current_session_key = key
            self.or_high = None
            self.or_low = None
            self.or_frozen = False
            self.traded_session = False
            self.long_threshold = 1.0
            self.short_threshold = 1.0
            self.or_range = 0.0
            self.entry_direction = None

    def in_any_or_window(self, t: time) -> bool:
        return in_or_window(t) or in_night_or_window(t)

    def update_or(self, price: float, ts: datetime,
                  bar_high: float | None = None, bar_low: float | None = None) -> None:
        if self.or_frozen:
            return
        if self.in_any_or_window(ts.time()):
            hi = bar_high if bar_high is not None else price
            lo = bar_low if bar_low is not None else price
            self.or_high = max(self.or_high or hi, hi)
            self.or_low = min(self.or_low or lo, lo)

    def freeze_or(self) -> None:
        if not self.or_frozen and self.or_high is not None and self.or_low is not None:
            self.or_frozen = True
            self.or_range = self.or_high - self.or_low

    def is_valid(self, min_width_pct: float, max_width_pct: float, mid_price: float) -> bool:
        if self.or_high is None or self.or_low is None or self.or_range <= 0:
            return False
        pct = self.or_range / mid_price
        return min_width_pct <= pct <= max_width_pct


# ---------------------------------------------------------------------------
# N-day trend filter
# ---------------------------------------------------------------------------

class _TrendFilter:
    """N-day slope-based trend direction."""

    def __init__(self, n_days: int = 8, min_slope_pct: float = 0.0003) -> None:
        self._n = n_days
        self._min_slope = min_slope_pct
        self._closes: deque[float] = deque(maxlen=n_days + 1)
        self._last_close_date: date | None = None

    def update_daily_close(self, close: float, d: date) -> None:
        if d != self._last_close_date:
            self._last_close_date = d
            self._closes.append(close)

    def trend(self) -> str:
        closes = list(self._closes)
        if len(closes) < self._n:
            return "neutral"
        oldest = closes[-self._n]
        newest = closes[-1]
        if oldest <= 0:
            return "neutral"
        slope = (newest - oldest) / oldest / max(self._n - 1, 1)
        if slope > self._min_slope:
            return "bullish"
        if slope < -self._min_slope:
            return "bearish"
        return "neutral"

    @property
    def warmed_up(self) -> bool:
        return len(self._closes) >= self._n


# ---------------------------------------------------------------------------
# Entry policy
# ---------------------------------------------------------------------------

class TAORBEntryPolicy(EntryPolicy):
    """TA-ORB entry: breakout of an adjusted Opening Range with trend gate.

    Stop sizing uses OR range: initial stop at opposite OR boundary,
    capped at stop_or_mult * OR_range.
    """

    def __init__(
        self,
        lots: float = 1.0,
        contract_type: str = "large",
        latest_entry_time: time = time(10, 30),
        trend_n_days: int = 8,
        min_slope_pct: float = 0.0003,
        base_threshold_mult: float = 1.0,
        trend_threshold_mult: float = 1.0,
        min_or_width_pct: float = 0.001,
        max_or_width_pct: float = 0.03,
        stop_or_mult: float = 1.5,
        t1_rr_mult: float = 2.0,
        ema_fast: int = 5,
        ema_slow: int = 13,
        atr_len: int = 10,
        atr_ceil: float = 0.0,
        allow_night: int = 0,
        require_vwap: int = 1,
        trend_mode: int = 1,
        or_atr_min: float = 0.0,
        or_atr_max: float = 0.0,
        ema_spread_min: float = 0.0,
        latest_night_entry_hour: int = 20,
        adx_period: int = 14,
        adx_threshold: float = 25.0,
        vol_len: int = 20,
        vol_mult: float = 0.0,
        macro_ma_len: int = 60,
        macro_filter_atr: float = 0.0,
    ) -> None:
        self._lots = lots
        self._contract_type = contract_type
        self._latest_entry = latest_entry_time
        self._base_mult = base_threshold_mult
        self._trend_mult = trend_threshold_mult
        self._min_or_pct = min_or_width_pct
        self._max_or_pct = max_or_width_pct
        self._stop_or_mult = stop_or_mult
        self._t1_rr_mult = t1_rr_mult
        self._atr_ceil = atr_ceil
        self._allow_night = bool(allow_night)
        self._require_vwap = bool(require_vwap)
        self._trend_mode = trend_mode
        self._or_atr_min = or_atr_min
        self._or_atr_max = or_atr_max
        self._ema_spread_min = ema_spread_min
        self._latest_night_entry = time(latest_night_entry_hour, 0)
        self._adx_threshold = adx_threshold
        self._vol_mult = vol_mult
        self._macro_filter_atr = macro_filter_atr
        self.orb_state = _ORBState()
        self.trend_filter = _TrendFilter(n_days=trend_n_days, min_slope_pct=min_slope_pct)
        self._last_close_update_date: date | None = None
        self.ind = _Indicators(
            ema_fast=ema_fast, ema_slow=ema_slow, atr_len=atr_len,
            adx_period=adx_period, vol_len=vol_len, macro_ma_len=macro_ma_len,
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
        ts = snapshot.timestamp
        t = ts.time()
        price = snapshot.price

        day_ok = in_day_session(t)
        night_ok = self._allow_night and in_night_session(t)
        if not (day_ok or night_ok):
            return None

        self.ind.update(price, ts, snapshot.volume)
        self.orb_state.reset_if_new_session(ts)
        self._maybe_update_daily_close(price, ts)

        # Build OR during either day or night OR window
        if self.orb_state.in_any_or_window(t):
            self.orb_state.update_or(price, ts,
                                     bar_high=snapshot.bar_high,
                                     bar_low=snapshot.bar_low)
            return None

        if not self.orb_state.or_frozen:
            self.orb_state.freeze_or()
            if not self.orb_state.is_valid(self._min_or_pct, self._max_or_pct, price):
                self.orb_state.traded_session = True
                return None
            # OR/ATR ratio filter — normalize OR quality across regimes
            atr = self.ind.atr
            if atr is not None and atr > 0 and self.orb_state.or_range > 0:
                or_atr_ratio = self.orb_state.or_range / atr
                if self._or_atr_min > 0 and or_atr_ratio < self._or_atr_min:
                    self.orb_state.traded_session = True
                    return None
                if self._or_atr_max > 0 and or_atr_ratio > self._or_atr_max:
                    self.orb_state.traded_session = True
                    return None
            self._set_thresholds()

        if self.orb_state.traded_session:
            return None

        # Latest entry time gate — day and night sessions
        if day_ok and t > self._latest_entry:
            return None
        if night_ok:
            # Night spans midnight: block if past latest hour (pre-midnight)
            # or any time after midnight (post-midnight entries are too stale)
            if t >= time(15, 15) and t > self._latest_night_entry:
                return None
            if t <= time(5, 0):
                return None

        trend = self._get_trend()
        if trend == "neutral":
            return None

        # ADX regime filter — block entries in choppy markets
        if self._adx_threshold > 0 and self.ind.adx < self._adx_threshold:
            return None

        # EMA spread filter — require minimum trend strength
        if (self._ema_spread_min > 0
                and self.ind.ema_fast is not None
                and self.ind.ema_slow is not None
                and price > 0):
            spread_pct = abs(self.ind.ema_fast - self.ind.ema_slow) / price
            if spread_pct < self._ema_spread_min:
                return None

        or_high = self.orb_state.or_high
        or_low = self.orb_state.or_low
        or_range = self.orb_state.or_range
        if or_high is None or or_low is None or or_range <= 0:
            return None

        # ATR ceiling filter: block entries during abnormally volatile bars
        atr = self.ind.atr
        if self._atr_ceil > 0 and atr is not None and self.ind.atr_avg is not None:
            if self.ind.atr_avg > 0 and atr > self._atr_ceil * self.ind.atr_avg:
                return None

        # Volume confirmation filter
        if (self._vol_mult > 0
                and self.ind.vol_ratio is not None
                and self.ind.vol_ratio < self._vol_mult):
            return None

        # Macro trend distance filter — block entries in extreme dislocations
        if (self._macro_filter_atr > 0
                and self.ind.macro_ma is not None
                and atr is not None and atr > 0):
            dist = abs(price - self.ind.macro_ma)
            if dist > self._macro_filter_atr * atr:
                return None

        # VWAP confirmation filter
        vwap = self.ind.vwap
        if self._require_vwap and vwap is not None:
            if trend == "bullish" and price < vwap:
                return None
            if trend == "bearish" and price > vwap:
                return None

        # OR-range-based stop: opposite OR boundary, capped at stop_or_mult * OR_range
        max_stop_dist = self._stop_or_mult * or_range
        long_trigger = or_high * self.orb_state.long_threshold
        short_trigger = or_low / self.orb_state.short_threshold

        # --- Long breakout ---
        if trend == "bullish" and price > long_trigger:
            raw_stop_dist = price - or_low
            stop_dist = min(raw_stop_dist, max_stop_dist)
            initial_stop = price - stop_dist
            risk_r = stop_dist
            t1_target = price + risk_r * self._t1_rr_mult

            self.orb_state.entry_direction = "long"
            return EntryDecision(
                lots=self._lots,
                contract_type=self._contract_type,
                initial_stop=initial_stop,
                direction="long",
                metadata={
                    "or_range": or_range, "risk_r": risk_r,
                    "t1_target": t1_target,
                    "strategy": "mt_ta_orb",
                },
            )

        # --- Short breakout ---
        if trend == "bearish" and price < short_trigger:
            raw_stop_dist = or_high - price
            stop_dist = min(raw_stop_dist, max_stop_dist)
            initial_stop = price + stop_dist
            risk_r = stop_dist
            t1_target = price - risk_r * self._t1_rr_mult

            self.orb_state.entry_direction = "short"
            return EntryDecision(
                lots=self._lots,
                contract_type=self._contract_type,
                initial_stop=initial_stop,
                direction="short",
                metadata={
                    "or_range": or_range, "risk_r": risk_r,
                    "t1_target": t1_target,
                    "strategy": "mt_ta_orb",
                },
            )
        return None

    def _get_trend(self) -> str:
        """Return trend direction based on selected mode."""
        if self._trend_mode == 1:
            # EMA crossover: fast > slow → bullish
            if self.ind.ema_fast is None or self.ind.ema_slow is None:
                return "neutral"
            if self.ind.ema_fast > self.ind.ema_slow:
                return "bullish"
            if self.ind.ema_fast < self.ind.ema_slow:
                return "bearish"
            return "neutral"
        return self.trend_filter.trend()

    def _set_thresholds(self) -> None:
        trend = self._get_trend()
        if trend == "bullish":
            self.orb_state.long_threshold = self._trend_mult
            self.orb_state.short_threshold = self._base_mult
        elif trend == "bearish":
            self.orb_state.long_threshold = self._base_mult
            self.orb_state.short_threshold = self._trend_mult
        else:
            self.orb_state.long_threshold = self._base_mult
            self.orb_state.short_threshold = self._base_mult

    def _maybe_update_daily_close(self, price: float, ts: datetime) -> None:
        """Update daily close for trend filter — once per calendar date.

        Removed the in_day_session() gate so night session bars (especially
        post-midnight) also trigger the update, keeping the N-day slope
        fresh for night entries.
        """
        d = ts.date()
        if d != self._last_close_update_date:
            self.trend_filter.update_daily_close(price, d)
            self._last_close_update_date = d


# ---------------------------------------------------------------------------
# Stop policy — OR-range T1 -> breakeven -> EMA trail
# ---------------------------------------------------------------------------

class TAORBStopPolicy(StopPolicy):
    """OR-range-based T1 -> breakeven, then EMA(slow) trail.

    Initial stop from entry metadata (OR boundary).
    T1 target at t1_rr_mult * R triggers breakeven.
    After breakeven, EMA(slow) trail with buffer.
    Trend reversal tightens stop to breakeven.
    """

    def __init__(
        self,
        indicators: _Indicators,
        entry_policy: TAORBEntryPolicy,
        t1_rr_mult: float = 2.0,
        ema_trail_buffer_pts: float = 12.0,
        max_hold_bars: int = 200,
    ) -> None:
        self._ind = indicators
        self._entry_policy = entry_policy
        self._t1_rr_mult = t1_rr_mult
        self._trail_buf = ema_trail_buffer_pts
        self._max_hold = max_hold_bars
        self._t1_target: float | None = None
        self._at_breakeven: bool = False
        self._bar_counts: dict[str, int] = {}

    def initial_stop(
        self, entry_price: float, direction: str, snapshot: MarketSnapshot,
    ) -> float:
        self._at_breakeven = False
        # T1 target is computed from the entry metadata (risk_r * t1_rr_mult)
        # but we also compute from OR state as fallback
        orb = self._entry_policy.orb_state
        or_range = orb.or_range if orb.or_range > 0 else 200.0
        stop_dist = min(
            abs(entry_price - (orb.or_low if direction == "long" else orb.or_high or entry_price)),
            self._entry_policy._stop_or_mult * or_range,
        ) if orb.or_high is not None and orb.or_low is not None else or_range
        if stop_dist <= 0:
            stop_dist = or_range
        risk_r = stop_dist
        if direction == "long":
            self._t1_target = entry_price + risk_r * self._t1_rr_mult
            return entry_price - stop_dist
        else:
            self._t1_target = entry_price - risk_r * self._t1_rr_mult
            return entry_price + stop_dist

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

        # Trend reversal: tighten to breakeven (not immediate close)
        trend = self._entry_policy._get_trend()
        if position.direction == "long" and trend == "bearish":
            if not self._at_breakeven and stop < entry:
                self._at_breakeven = True
                return entry
        elif position.direction == "short" and trend == "bullish":
            if not self._at_breakeven and stop > entry:
                self._at_breakeven = True
                return entry

        # T1 breakeven trigger
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


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def create_ta_orb_engine(
    max_loss: float = 500_000,
    lots: float = 1.0,
    contract_type: str = "large",
    trend_n_days: int = 8,
    min_slope_pct: float = 0.0003,
    trend_threshold_mult: float = 1.0,
    min_or_width_pct: float = 0.001,
    max_or_width_pct: float = 0.03,
    stop_or_mult: float = 1.5,
    t1_rr_mult: float = 2.0,
    ema_fast: int = 5,
    ema_slow: int = 13,
    atr_len: int = 10,
    atr_ceil: float = 0.0,
    ema_trail_buffer_pts: float = 12.0,
    max_hold_bars: int = 200,
    allow_night: int = 1,
    require_vwap: int = 1,
    trend_mode: int = 1,
    or_atr_min: float = 0.0,
    or_atr_max: float = 0.0,
    ema_spread_min: float = 0.0,
    latest_night_entry_hour: int = 20,
    adx_period: int = 14,
    adx_threshold: float = 25.0,
    vol_len: int = 20,
    vol_mult: float = 0.0,
    macro_ma_len: int = 60,
    macro_filter_atr: float = 0.0,
    max_pyramid_levels: int = 4,
    pyramid_gamma: float = 0.7,
    pyramid_trigger_atr: float = 1.5,
) -> "PositionEngine":
    """Build a PositionEngine wired with the medium-term TA-ORB strategy."""
    from src.core.position_engine import PositionEngine

    entry = TAORBEntryPolicy(
        lots=lots,
        contract_type=contract_type,
        trend_n_days=trend_n_days,
        min_slope_pct=min_slope_pct,
        trend_threshold_mult=trend_threshold_mult,
        min_or_width_pct=min_or_width_pct,
        max_or_width_pct=max_or_width_pct,
        stop_or_mult=stop_or_mult,
        t1_rr_mult=t1_rr_mult,
        ema_fast=ema_fast,
        ema_slow=ema_slow,
        atr_len=atr_len,
        atr_ceil=atr_ceil,
        allow_night=allow_night,
        require_vwap=require_vwap,
        trend_mode=trend_mode,
        or_atr_min=or_atr_min,
        or_atr_max=or_atr_max,
        ema_spread_min=ema_spread_min,
        latest_night_entry_hour=latest_night_entry_hour,
        adx_period=adx_period,
        adx_threshold=adx_threshold,
        vol_len=vol_len,
        vol_mult=vol_mult,
        macro_ma_len=macro_ma_len,
        macro_filter_atr=macro_filter_atr,
    )
    stop = TAORBStopPolicy(
        indicators=entry.ind,
        entry_policy=entry,
        t1_rr_mult=t1_rr_mult,
        ema_trail_buffer_pts=ema_trail_buffer_pts,
        max_hold_bars=max_hold_bars,
    )
    if max_pyramid_levels > 1:
        from src.core.policies import PyramidAddPolicy
        from src.core.types import PyramidConfig

        triggers = [pyramid_trigger_atr * (i + 1) for i in range(max_pyramid_levels - 1)]
        pyramid_config = PyramidConfig(
            max_loss=max_loss,
            max_levels=max_pyramid_levels,
            add_trigger_atr=triggers,
            atr_key="entry_tf",
            gamma=pyramid_gamma,
            base_lots=lots,
            internal_atr_len=10,
        )
        add_policy = PyramidAddPolicy(pyramid_config)
    else:
        add_policy = NoAddPolicy()
    engine = PositionEngine(
        entry_policy=entry,
        add_policy=add_policy,
        stop_policy=stop,
        config=EngineConfig(max_loss=max_loss),
    )
    engine.indicator_provider = entry.ind  # type: ignore[attr-defined]
    return engine
