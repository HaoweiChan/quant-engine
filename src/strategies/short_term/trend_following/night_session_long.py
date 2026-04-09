"""Night Session Long Strategy (5-min).

Structural edge: TX night session (15:00-05:00) delivers +156.7% cumulative
return with Sharpe 1.28 over 2020-2026, while day session is flat (-4.8%).
Night gains are positive every year including 2022 bear market.

Entry:
- Go long at the start of each night session (configurable offset)
- One entry per session maximum
- Optional filters: ATR volatility gate, trend EMA gate (toggleable)

Exit:
- Fixed ATR stop-loss
- Optional trailing stop (chandelier-style, toggleable)
- Force close before session end (configurable minutes before 05:00)

Leverage:
- Position size via lots parameter (1-10 contracts)
- No pyramiding — leverage comes from initial lot size
"""
from __future__ import annotations

from collections import deque
from datetime import time
from statistics import mean
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

if TYPE_CHECKING:
    from src.core.position_engine import PositionEngine


PARAM_SCHEMA: dict[str, dict] = {
    "lots": {
        "type": "int", "default": 1, "min": 1, "max": 10,
        "description": "Contracts per entry (primary leverage lever).",
        "grid": [1, 2, 3, 4, 5, 6, 8, 10],
    },
    "entry_offset_min": {
        "type": "int", "default": 5, "min": 0, "max": 30,
        "description": "Minutes after 15:00 to enter (0=session open, 15=after OR window).",
        "grid": [5, 10, 15],
    },
    "exit_before_close_min": {
        "type": "int", "default": 5, "min": 5, "max": 15,
        "description": "Minutes before 05:00 to force close.",
        "grid": [5, 10],
    },
    "atr_sl_mult": {
        "type": "float", "default": 2.0, "min": 0.5, "max": 4.0,
        "description": "Stop-loss distance as multiplier of daily ATR.",
        "grid": [1.0, 1.5, 2.0, 2.5, 3.0],
    },
    "use_atr_filter": {
        "type": "int", "default": 0, "min": 0, "max": 1,
        "description": "Enable ATR volatility filter (1=on, 0=off).",
        "grid": [0, 1],
    },
    "atr_filter_mult": {
        "type": "float", "default": 2.0, "min": 1.2, "max": 3.0,
        "description": "Skip entry if daily ATR > this * rolling avg ATR.",
        "grid": [1.5, 2.0, 2.5],
    },
    "use_trend_filter": {
        "type": "int", "default": 0, "min": 0, "max": 1,
        "description": "Enable trend EMA filter (1=on, 0=off).",
        "grid": [0, 1],
    },
    "trend_ema_len": {
        "type": "int", "default": 20, "min": 5, "max": 60,
        "description": "EMA lookback for trend filter (in sessions, ~1 session/day).",
        "grid": [10, 20, 40],
    },
    "trail_enabled": {
        "type": "int", "default": 0, "min": 0, "max": 1,
        "description": "Enable trailing stop (1=on, 0=off).",
        "grid": [0, 1],
    },
    "trail_trigger_atr": {
        "type": "float", "default": 1.0, "min": 0.5, "max": 3.0,
        "description": "Profit in ATR multiples to activate trailing stop.",
        "grid": [0.5, 1.0, 1.5],
    },
    "trail_atr_mult": {
        "type": "float", "default": 1.5, "min": 0.5, "max": 3.0,
        "description": "Trailing stop distance in ATR multiples.",
        "grid": [1.0, 1.5, 2.0],
    },
}

STRATEGY_META: dict = {
    "category": StrategyCategory.TREND_FOLLOWING,
    "signal_timeframe": SignalTimeframe.FIVE_MIN,
    "holding_period": HoldingPeriod.SHORT_TERM,
    "stop_architecture": StopArchitecture.INTRADAY,
    "expected_duration_minutes": (120, 840),
    "tradeable_sessions": ["night"],
    "bars_per_day": 168,
    "presets": {
        "quick": {"n_bars": 3360, "note": "~1 month (20 nights × 168 bars)"},
        "standard": {"n_bars": 10080, "note": "~3 months"},
        "full_year": {"n_bars": 43680, "note": "~1 year (260 nights)"},
    },
    "description": (
        "Night Session Long exploits the structural bias of TX futures "
        "gaining primarily during night sessions (15:00-05:00). "
        "Enters long at session open, exits at session close with ATR-based risk control."
    ),
}


# ── Session boundary helpers (night-session specific) ────────────────────────

NIGHT_OPEN = time(15, 0)
NIGHT_CLOSE = time(5, 0)


def _night_entry_time(offset_min: int) -> time:
    """Compute entry time as NIGHT_OPEN + offset minutes."""
    h, m = divmod(15 * 60 + offset_min, 60)
    return time(h, m)


def _night_exit_time(before_close_min: int) -> time:
    """Compute force-close time as NIGHT_CLOSE - before_close_min."""
    total = 5 * 60 - before_close_min
    h, m = divmod(total, 60)
    return time(h, m)


def _in_night_session(t: time) -> bool:
    """15:00 <= t or t < 05:00 (spans midnight)."""
    return t >= NIGHT_OPEN or t < NIGHT_CLOSE


def _past_exit_time(t: time, exit_time: time) -> bool:
    """Check if current time is at or past exit_time (pre-dawn)."""
    # exit_time is always in the 04:xx range
    return time(0, 0) <= t <= NIGHT_CLOSE and t >= exit_time


# ── Indicators ───────────────────────────────────────────────────────────────

class _Indicators:
    """Lightweight indicator state for night session strategy."""

    def __init__(self, trend_ema_len: int = 20, atr_avg_len: int = 20) -> None:
        self._trend_alpha = 2.0 / (trend_ema_len + 1)
        self._atr_avg_len = atr_avg_len
        self._trend_ema: float | None = None
        self._atr_history: deque[float] = deque(maxlen=atr_avg_len)
        self._session_closes: deque[float] = deque(maxlen=max(trend_ema_len, 1))
        self._bar_count = 0
        # Public
        self.trend_ema: float | None = None
        self.avg_atr: float | None = None
        self.daily_atr: float = 0.0

    def update(self, price: float, daily_atr: float) -> None:
        self._bar_count += 1
        self.daily_atr = daily_atr

    def on_session_close(self, close_price: float, daily_atr: float) -> None:
        """Called once at the end of each session to update session-level indicators."""
        self._session_closes.append(close_price)
        self._atr_history.append(daily_atr)
        # Update trend EMA on session closes
        if self._trend_ema is None:
            self._trend_ema = close_price
        else:
            self._trend_ema = self._trend_alpha * close_price + (1 - self._trend_alpha) * self._trend_ema
        self.trend_ema = self._trend_ema
        # Rolling average ATR
        if len(self._atr_history) >= 5:
            self.avg_atr = mean(self._atr_history)


# ── Entry Policy ─────────────────────────────────────────────────────────────

class NightSessionLongEntry(EntryPolicy):
    """Enter long at the start of each night session."""

    def __init__(
        self,
        indicators: _Indicators,
        lots: int = 1,
        contract_type: str = "large",
        entry_offset_min: int = 5,
        atr_sl_mult: float = 2.0,
        use_atr_filter: bool = False,
        atr_filter_mult: float = 2.0,
        use_trend_filter: bool = False,
    ) -> None:
        self._ind = indicators
        self._lots = lots
        self._contract_type = contract_type
        self._entry_time = _night_entry_time(entry_offset_min)
        self._atr_sl_mult = atr_sl_mult
        self._use_atr_filter = use_atr_filter
        self._atr_filter_mult = atr_filter_mult
        self._use_trend_filter = use_trend_filter
        self._entered_this_session = False
        self._last_session_date = None

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

        # Only trade night session
        if not _in_night_session(t):
            return None

        # Reset session tracking when a new night begins
        d = snapshot.timestamp.date()
        if t >= NIGHT_OPEN:
            session_key = d
        else:
            # After midnight — same session as previous calendar day
            from datetime import timedelta
            session_key = (snapshot.timestamp - timedelta(days=1)).date()

        if session_key != self._last_session_date:
            self._last_session_date = session_key
            self._entered_this_session = False

        # Already entered this session
        if self._entered_this_session:
            return None

        # Already in position
        if engine_state.positions:
            return None

        # Wait for entry time
        if t < self._entry_time and t >= NIGHT_OPEN:
            return None

        # On the after-midnight side, we've already passed entry_time
        # (entry_time is in the 15:xx range), so we should have entered

        daily_atr = snapshot.atr.get("daily", 0.0)
        if daily_atr <= 0:
            return None

        self._ind.update(snapshot.price, daily_atr)

        # ATR volatility filter
        if self._use_atr_filter and self._ind.avg_atr is not None:
            if daily_atr > self._atr_filter_mult * self._ind.avg_atr:
                return None

        # Trend filter
        if self._use_trend_filter and self._ind.trend_ema is not None:
            if snapshot.price < self._ind.trend_ema:
                return None

        sl_pts = daily_atr * self._atr_sl_mult
        self._entered_this_session = True

        return EntryDecision(
            lots=float(self._lots),
            contract_type=self._contract_type,
            initial_stop=snapshot.price - sl_pts,
            direction="long",
            metadata={
                "daily_atr": daily_atr,
                "avg_atr": self._ind.avg_atr,
                "trend_ema": self._ind.trend_ema,
            },
        )


# ── Stop Policy ──────────────────────────────────────────────────────────────

class NightSessionLongStop(StopPolicy):
    """ATR stop + optional trailing stop + force close at session end."""

    def __init__(
        self,
        indicators: _Indicators,
        atr_sl_mult: float = 2.0,
        exit_before_close_min: int = 5,
        trail_enabled: bool = False,
        trail_trigger_atr: float = 1.0,
        trail_atr_mult: float = 1.5,
    ) -> None:
        self._ind = indicators
        self._atr_sl_mult = atr_sl_mult
        self._exit_time = _night_exit_time(exit_before_close_min)
        self._trail_enabled = trail_enabled
        self._trail_trigger_atr = trail_trigger_atr
        self._trail_atr_mult = trail_atr_mult
        self._locked_atr: dict[str, float] = {}

    def initial_stop(
        self, entry_price: float, direction: str, snapshot: MarketSnapshot,
    ) -> float:
        daily_atr = max(snapshot.atr.get("daily", 0.0), 1e-6)
        sl_pts = daily_atr * self._atr_sl_mult
        # Lock ATR at entry for trailing stop calculations
        # Use price as a makeshift position key (will be overwritten in update_stop)
        return entry_price - sl_pts

    def update_stop(
        self,
        position: Position,
        snapshot: MarketSnapshot,
        high_history: deque[float],
    ) -> float:
        t = snapshot.timestamp.time()
        daily_atr = max(snapshot.atr.get("daily", 0.0), 1e-6)
        self._ind.update(snapshot.price, daily_atr)

        # Force close at session end
        if _past_exit_time(t, self._exit_time):
            # Record session close for indicator updates
            self._ind.on_session_close(snapshot.price, daily_atr)
            return snapshot.price

        # Trailing stop logic
        if self._trail_enabled and high_history:
            pid = position.position_id
            if pid not in self._locked_atr:
                self._locked_atr[pid] = daily_atr

            locked = self._locked_atr[pid]
            profit = snapshot.price - position.entry_price
            trigger = self._trail_trigger_atr * locked

            if profit >= trigger:
                highest = max(high_history)
                trail_stop = highest - self._trail_atr_mult * locked
                return max(trail_stop, position.stop_level)

        return position.stop_level


# ── Factory ──────────────────────────────────────────────────────────────────

def create_night_session_long_engine(
    max_loss: float = 500_000.0,
    lots: int = 1,
    contract_type: str = "large",
    entry_offset_min: int = 5,
    exit_before_close_min: int = 5,
    atr_sl_mult: float = 2.0,
    use_atr_filter: int = 0,
    atr_filter_mult: float = 2.0,
    use_trend_filter: int = 0,
    trend_ema_len: int = 20,
    trail_enabled: int = 0,
    trail_trigger_atr: float = 1.0,
    trail_atr_mult: float = 1.5,
) -> "PositionEngine":
    """Build a PositionEngine for night session long strategy."""
    from src.core.position_engine import PositionEngine

    indicators = _Indicators(trend_ema_len=trend_ema_len)

    engine_config = EngineConfig(max_loss=max_loss)
    return PositionEngine(
        entry_policy=NightSessionLongEntry(
            indicators=indicators,
            lots=lots,
            contract_type=contract_type,
            entry_offset_min=entry_offset_min,
            atr_sl_mult=atr_sl_mult,
            use_atr_filter=bool(use_atr_filter),
            atr_filter_mult=atr_filter_mult,
            use_trend_filter=bool(use_trend_filter),
        ),
        add_policy=NoAddPolicy(),
        stop_policy=NightSessionLongStop(
            indicators=indicators,
            atr_sl_mult=atr_sl_mult,
            exit_before_close_min=exit_before_close_min,
            trail_enabled=bool(trail_enabled),
            trail_trigger_atr=trail_trigger_atr,
            trail_atr_mult=trail_atr_mult,
        ),
        config=engine_config,
    )
