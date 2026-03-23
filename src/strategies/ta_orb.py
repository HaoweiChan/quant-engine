"""Threshold-Adjusting Opening Range Breakout (TA-ORB) Strategy.

Based on:
  - "Modified ORB Strategies with Threshold Adjusting on Taiwan Futures Market"
    (IEEE 2019) — TA_ORB concept
  - "Assessing the Profitability of Timely ORB on Index Futures" (TORB) —
    aligning the OR window to TAIFEX 8:45–9:00 (pre-TSE open)

Strategy logic:
  Opening Range  : built from bars in [08:45, 09:00)  (day session only)
  Trend filter   : N-day close slope determines bullish / bearish / neutral
  Entry (long)   : Only if trend is BULLISH.
                   Close > OR_high * threshold_mult
  Entry (short)  : Only if trend is BEARISH.
                   Close < OR_low  / threshold_mult
  No-trade conditions (any one blocks the day):
    - OR width < min_or_width_pct  (low-vol day, weak signal)
    - OR width > max_or_width_pct  (excessive gap / high-risk day)
    - Breakout bar arrives after latest_entry_time  (stale signal)
    - Engine is halted
    - Trend is NEUTRAL (no directional bias)
    - Only one trade per day (first breakout direction wins)

Exit (StopPolicy):
  - Initial stop at OR_range * stop_or_mult from entry (capped by hard_stop_pts)
  - T1 take-profit at OR_range * t1_or_mult from entry → move stop to breakeven
  - T2 take-profit at OR_range * t2_or_mult from entry → full close
  - Force-close: 13:25–13:45 (day), 04:50–05:00 (night)

Session helpers re-use the same boundaries as atr_mean_reversion.py.
"""
from __future__ import annotations

from collections import deque
from datetime import date, datetime, time
from typing import TYPE_CHECKING

from src.core.policies import EntryPolicy, NoAddPolicy, StopPolicy
from src.core.types import (
    EngineConfig,
    EngineState,
    EntryDecision,
    MarketSignal,
    MarketSnapshot,
    Position,
)

if TYPE_CHECKING:
    from src.core.position_engine import PositionEngine


# ---------------------------------------------------------------------------
# Parameter schema — single source of truth for defaults, types, and ranges
# ---------------------------------------------------------------------------

PARAM_SCHEMA: dict[str, dict] = {
    "trend_n_days":         {"type": "int",   "default": 8,     "min": 3,     "max": 20,
                             "description": "N-day lookback for slope-based trend filter.",
                             "grid": [5, 8, 12]},
    "min_slope_pct":        {"type": "float", "default": 0.0003, "min": 0.0001, "max": 0.003,
                             "description": "Minimum daily slope fraction to declare a trend.",
                             "grid": [0.0002, 0.0003, 0.0005]},
    "trend_threshold_mult": {"type": "float", "default": 1.0,   "min": 1.0,   "max": 1.01,
                             "description": "OR breakout multiplier when trend is confirmed (TA part).",
                             "grid": [1.0, 1.001, 1.002]},
    "min_or_width_pct":     {"type": "float", "default": 0.001, "min": 0.0003, "max": 0.005,
                             "description": "Minimum OR width as fraction of price (low-vol filter)."},
    "max_or_width_pct":     {"type": "float", "default": 0.03,  "min": 0.005,  "max": 0.05,
                             "description": "Maximum OR width as fraction of price (gap filter)."},
    "stop_or_mult":         {"type": "float", "default": 10.0,  "min": 3.0,   "max": 20.0,
                             "description": "Initial stop distance as multiple of OR range (disaster-only).",
                             "grid": [5.0, 10.0, 15.0]},
    "hard_stop_pts":        {"type": "float", "default": 2000.0, "min": 500.0, "max": 3000.0,
                             "description": "Hard cap on stop distance in index points.",
                             "grid": [1000.0, 2000.0]},
    "trail_or_mult":        {"type": "float", "default": 2.0,   "min": 0.5,   "max": 4.0,
                             "description": "Trailing stop distance as multiple of OR range (after T1).",
                             "grid": [1.0, 2.0, 3.0]},
    "t1_or_mult":           {"type": "float", "default": 5.0,   "min": 1.0,   "max": 10.0,
                             "description": "T1 target: move stop to breakeven, activate trail.",
                             "grid": [3.0, 5.0, 8.0]},
}

STRATEGY_META: dict = {
    "recommended_timeframe": "intraday",
    "description": "Threshold-Adjusting Opening Range Breakout for TAIFEX futures.",
    "paper": "Modified ORB Strategies with Threshold Adjusting on Taiwan Futures Market (IEEE 2019)",
}


# ---------------------------------------------------------------------------
# Session helpers  (mirrors atr_mean_reversion.py)
# ---------------------------------------------------------------------------

def _in_day_session(t: time) -> bool:
    return time(8, 45) <= t <= time(13, 15)


def _in_or_window(t: time) -> bool:
    """8:45 <= t < 9:00 — the 15-minute Opening Range building window."""
    return time(8, 45) <= t < time(9, 0)


def _in_force_close(_t: time) -> bool:
    """Disabled: positions held until trend reversal or stop.

    The strategy captures multi-day drift by not force-closing.
    Exit is driven by the trailing stop or trend-reversal logic
    in the stop policy.
    """
    return False


# ---------------------------------------------------------------------------
# Per-day ORB state  (reset at the start of each calendar date)
# ---------------------------------------------------------------------------

class _ORBState:
    """Tracks all intra-day state needed for one TA-ORB cycle."""

    def __init__(self) -> None:
        self.current_date: date | None = None
        self.or_high: float | None = None
        self.or_low: float | None = None
        self.or_frozen: bool = False
        self.traded_today: bool = False
        self.long_threshold: float = 1.0
        self.short_threshold: float = 1.0
        self.or_range: float = 0.0
        self.entry_direction: str | None = None

    def reset_if_new_day(self, ts: datetime) -> None:
        d = ts.date()
        if d != self.current_date:
            self.current_date = d
            self.or_high = None
            self.or_low = None
            self.or_frozen = False
            self.traded_today = False
            self.long_threshold = 1.0
            self.short_threshold = 1.0
            self.or_range = 0.0
            self.entry_direction = None

    def update_or(self, price: float, ts: datetime) -> None:
        if self.or_frozen:
            return
        if _in_or_window(ts.time()):
            self.or_high = max(self.or_high or price, price)
            self.or_low = min(self.or_low or price, price)

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
    """TA-ORB entry: breakout of an adjusted Opening Range with trend gate."""

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
        stop_or_mult: float = 10.0,
        hard_stop_pts: float = 2000.0,
        trail_or_mult: float = 2.0,
        t1_or_mult: float = 5.0,
    ) -> None:
        self._lots = lots
        self._contract_type = contract_type
        self._latest_entry = latest_entry_time
        self._base_mult = base_threshold_mult
        self._trend_mult = trend_threshold_mult
        self._min_or_pct = min_or_width_pct
        self._max_or_pct = max_or_width_pct
        self._stop_or_mult = stop_or_mult
        self._hard_stop_pts = hard_stop_pts
        self._trail_or_mult = trail_or_mult
        self._t1_mult = t1_or_mult
        self.orb_state = _ORBState()
        self.trend_filter = _TrendFilter(n_days=trend_n_days, min_slope_pct=min_slope_pct)
        self._last_close_update_date: date | None = None
        self.last_entry_or_range: float = 0.0

    def should_enter(
        self,
        snapshot: MarketSnapshot,
        signal: MarketSignal | None,
        engine_state: EngineState,
    ) -> EntryDecision | None:
        if engine_state.mode == "halted":
            return None
        ts = snapshot.timestamp
        t = ts.time()
        price = snapshot.price
        if not _in_day_session(t):
            return None
        self.orb_state.reset_if_new_day(ts)
        self._maybe_update_daily_close(price, ts)
        if _in_or_window(t):
            self.orb_state.update_or(price, ts)
            return None
        if not self.orb_state.or_frozen:
            self.orb_state.freeze_or()
            if not self.orb_state.is_valid(self._min_or_pct, self._max_or_pct, price):
                self.orb_state.traded_today = True
                return None
            self._set_thresholds()
        if self.orb_state.traded_today:
            return None
        if t > self._latest_entry:
            return None
        if _in_force_close(t):
            return None
        trend = self.trend_filter.trend()
        if trend == "neutral":
            return None
        or_high = self.orb_state.or_high
        or_low = self.orb_state.or_low
        or_range = self.orb_state.or_range
        if or_high is None or or_low is None or or_range <= 0:
            return None
        long_trigger = or_high * self.orb_state.long_threshold
        short_trigger = or_low / self.orb_state.short_threshold
        # --- Long breakout ---
        if trend == "bullish" and price > long_trigger:
            stop_pts = min(or_range * self._stop_or_mult, self._hard_stop_pts)
            self.orb_state.traded_today = True
            self.orb_state.entry_direction = "long"
            self.last_entry_or_range = or_range
            return EntryDecision(
                lots=self._lots,
                contract_type=self._contract_type,
                initial_stop=price - stop_pts,
                direction="long",
                metadata={"or_range": or_range},
            )
        # --- Short breakout ---
        if trend == "bearish" and price < short_trigger:
            stop_pts = min(or_range * self._stop_or_mult, self._hard_stop_pts)
            self.orb_state.traded_today = True
            self.orb_state.entry_direction = "short"
            self.last_entry_or_range = or_range
            return EntryDecision(
                lots=self._lots,
                contract_type=self._contract_type,
                initial_stop=price + stop_pts,
                direction="short",
                metadata={"or_range": or_range},
            )
        return None

    def _set_thresholds(self) -> None:
        trend = self.trend_filter.trend()
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
        """Feed the trend filter with the first bar of each day session."""
        d = ts.date()
        if d != self._last_close_update_date and _in_day_session(ts.time()):
            self.trend_filter.update_daily_close(price, d)
            self._last_close_update_date = d


# ---------------------------------------------------------------------------
# Stop policy
# ---------------------------------------------------------------------------

class TAORBStopPolicy(StopPolicy):
    """Trend-reversal + trailing stop for TA-ORB.

    Positions are held until:
    1. The trend filter flips against the position (exit at current price)
    2. T1 is reached → trail activates, ratcheting with the peak
    3. The initial hard stop is hit (disaster protection)
    """

    def __init__(
        self,
        t1_or_mult: float = 5.0,
        trail_or_mult: float = 2.0,
        entry_policy: "TAORBEntryPolicy | None" = None,
    ) -> None:
        self._t1_mult = t1_or_mult
        self._trail_mult = trail_or_mult
        self._entry_policy = entry_policy
        self._t1_target: float | None = None
        self._trail_dist: float = 0.0
        self._t1_hit: bool = False
        self._cached_entry_price: float | None = None
        self._peak: float = 0.0

    def _init_targets(self, entry_price: float, direction: str) -> None:
        or_range = (
            self._entry_policy.last_entry_or_range
            if self._entry_policy is not None and self._entry_policy.last_entry_or_range > 0
            else 200.0
        )
        self._cached_entry_price = entry_price
        self._trail_dist = or_range * self._trail_mult
        self._t1_hit = False
        self._peak = entry_price
        if direction == "long":
            self._t1_target = entry_price + or_range * self._t1_mult
        else:
            self._t1_target = entry_price - or_range * self._t1_mult

    def initial_stop(self, entry_price: float, direction: str, snapshot: MarketSnapshot) -> float:
        self._init_targets(entry_price, direction)
        return snapshot.price

    def update_stop(
        self,
        position: Position,
        snapshot: MarketSnapshot,
        high_history: deque[float],
    ) -> float:
        price = snapshot.price
        current_stop = position.stop_level
        if self._cached_entry_price != position.entry_price:
            self._init_targets(position.entry_price, position.direction)
        # Trend-reversal exit: if trend flips against the position, close
        if self._entry_policy is not None:
            trend = self._entry_policy.trend_filter.trend()
            if position.direction == "long" and trend == "bearish":
                return price
            if position.direction == "short" and trend == "bullish":
                return price
        # Track peak and trail after T1
        if position.direction == "long":
            self._peak = max(self._peak, price)
            if not self._t1_hit and self._t1_target is not None and price >= self._t1_target:
                self._t1_hit = True
            if self._t1_hit:
                trail_stop = self._peak - self._trail_dist
                return max(position.entry_price, trail_stop)
        else:
            self._peak = min(self._peak, price)
            if not self._t1_hit and self._t1_target is not None and price <= self._t1_target:
                self._t1_hit = True
            if self._t1_hit:
                trail_stop = self._peak + self._trail_dist
                return min(position.entry_price, trail_stop)
        return current_stop


# ---------------------------------------------------------------------------
# Convenience factory
# ---------------------------------------------------------------------------

def create_ta_orb_engine(
    max_loss: float = 150_000,
    lots: float = 1.0,
    contract_type: str = "large",
    trend_n_days: int = 8,
    min_slope_pct: float = 0.0003,
    trend_threshold_mult: float = 1.0,
    min_or_width_pct: float = 0.001,
    max_or_width_pct: float = 0.03,
    stop_or_mult: float = 10.0,
    hard_stop_pts: float = 2000.0,
    trail_or_mult: float = 2.0,
    t1_or_mult: float = 5.0,
    latest_entry_time: time = time(10, 30),
) -> "PositionEngine":
    """Build a PositionEngine wired with the TA-ORB strategy."""
    from src.core.position_engine import PositionEngine

    entry = TAORBEntryPolicy(
        lots=lots,
        contract_type=contract_type,
        latest_entry_time=latest_entry_time,
        trend_n_days=trend_n_days,
        min_slope_pct=min_slope_pct,
        trend_threshold_mult=trend_threshold_mult,
        min_or_width_pct=min_or_width_pct,
        max_or_width_pct=max_or_width_pct,
        stop_or_mult=stop_or_mult,
        hard_stop_pts=hard_stop_pts,
        trail_or_mult=trail_or_mult,
        t1_or_mult=t1_or_mult,
    )
    stop = TAORBStopPolicy(
        t1_or_mult=t1_or_mult,
        trail_or_mult=trail_or_mult,
        entry_policy=entry,
    )
    return PositionEngine(
        entry_policy=entry,
        add_policy=NoAddPolicy(),
        stop_policy=stop,
        config=EngineConfig(max_loss=max_loss),
    )