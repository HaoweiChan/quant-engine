"""Night Session Long Strategy (5-min).

Structural edge: TX night session (15:00-05:00) delivers +156.7% cumulative
return with Sharpe 1.28 over 2020-2026, while day session is flat (-4.8%).
Night gains are positive every year including 2022 bear market.

Entry:
- Go long at the start of each night session (configurable offset)
- One entry per session maximum
- Optional filters: ATR volatility gate, trend EMA gate, OR momentum (toggleable)

Exit:
- Fixed ATR stop-loss
- Optional breakeven stop (move stop to entry after profit threshold)
- Optional trailing stop (chandelier-style, toggleable)
- Force close before session end (configurable minutes before 05:00)

Leverage:
- Position size via lots parameter (static) or Kelly-based dynamic sizing
- Dynamic sizing uses compute_risk_lots() for contract-agnostic risk exposure
- No pyramiding — leverage comes from initial lot size
"""
from __future__ import annotations

from collections import deque
from datetime import time
from typing import TYPE_CHECKING

from src.core.policies import EntryPolicy, NoAddPolicy, StopPolicy
from src.core.sizing import compute_risk_lots
from src.core.types import (
    AccountState,
    EngineConfig,
    EngineState,
    EntryDecision,
    MarketSignal,
    MarketSnapshot,
    Position,
)
from src.indicators.atr import SmoothedATR
from src.indicators.ema import EMA
from src.indicators.rsi import RSI
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
    "trend_invert": {
        "type": "int", "default": 0, "min": 0, "max": 1,
        "description": "Invert trend filter: 0=require price>EMA (trend), 1=require price<EMA (pullback/mean reversion).",
        "grid": [0, 1],
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
    "or_confirm": {
        "type": "int", "default": 0, "min": 0, "max": 1,
        "description": "Enable opening range momentum confirmation (1=on, 0=off).",
        "grid": [0, 1],
    },
    "or_wait_min": {
        "type": "int", "default": 15, "min": 5, "max": 30,
        "description": "Minutes to wait after session open before checking OR confirmation.",
        "grid": [5, 10, 15, 20, 30],
    },
    "or_threshold_atr": {
        "type": "float", "default": 0.0, "min": 0.0, "max": 1.0,
        "description": "Minimum price rise above session open (in ATR multiples) to confirm entry. 0=any rise.",
        "grid": [0.0, 0.1, 0.2, 0.3, 0.5],
    },
    "breakeven_enabled": {
        "type": "int", "default": 0, "min": 0, "max": 1,
        "description": "Move stop to entry price after profit threshold (1=on, 0=off).",
        "grid": [0, 1],
    },
    "breakeven_trigger_atr": {
        "type": "float", "default": 1.0, "min": 0.3, "max": 2.0,
        "description": "Profit in ATR multiples to trigger breakeven stop.",
        "grid": [0.3, 0.5, 0.75, 1.0, 1.5],
    },
    "tp_enabled": {
        "type": "int", "default": 0, "min": 0, "max": 1,
        "description": "Enable take-profit exit at fixed ATR multiple (1=on, 0=off).",
        "grid": [0, 1],
    },
    "tp_atr_mult": {
        "type": "float", "default": 2.0, "min": 0.5, "max": 5.0,
        "description": "Take-profit distance in ATR multiples above entry.",
        "grid": [1.0, 1.5, 2.0, 2.5, 3.0, 4.0],
    },
    "momentum_filter": {
        "type": "int", "default": 0, "min": 0, "max": 2,
        "description": "Session filter: 0=off, 1=enter only after positive session, 2=enter only after negative session (mean reversion).",
        "grid": [0, 1, 2],
    },
    "mr_min_drop_atr": {
        "type": "float", "default": 0.0, "min": 0.0, "max": 1.0,
        "description": "Min prior session drop (in ATR multiples) to trigger mean reversion entry. 0=any drop. Only used when momentum_filter=2.",
        "grid": [0.0, 0.1, 0.2, 0.3, 0.5],
    },
    "rsi_filter_enabled": {
        "type": "int", "default": 0, "min": 0, "max": 1,
        "description": "Enable RSI filter — skip entry when RSI is overbought (1=on, 0=off).",
        "grid": [0, 1],
    },
    "rsi_max_entry": {
        "type": "float", "default": 70.0, "min": 50.0, "max": 85.0,
        "description": "Max RSI for entry. Skip if RSI is above this level.",
        "grid": [60, 65, 70, 75, 80],
    },
    "rsi_period": {
        "type": "int", "default": 14, "min": 5, "max": 30,
        "description": "RSI lookback period.",
        "grid": [5, 10, 14],
    },
    "sizing_mode": {
        "type": "int", "default": 0, "min": 0, "max": 1,
        "description": "0=static lots, 1=Kelly-based dynamic sizing via compute_risk_lots().",
        "grid": [0, 1],
    },
    "risk_pct": {
        "type": "float", "default": 0.10, "min": 0.01, "max": 0.15,
        "description": "Fraction of equity to risk per trade. TX needs ~0.10 (full Kelly) for 1 lot; MTX works at lower fractions.",
        "grid": [0.056, 0.08, 0.10],
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
    """Indicator state using src/indicators/ modules."""

    def __init__(self, trend_ema_len: int = 20, atr_avg_len: int = 20, rsi_period: int = 14) -> None:
        self._trend_ema = EMA(period=trend_ema_len)
        self._smoothed_atr = SmoothedATR(period=atr_avg_len)
        self._rsi = RSI(period=rsi_period)
        # Per-session high/low tracking for true session range
        self._session_high: float = 0.0
        self._session_low: float = float("inf")
        # Public
        self.trend_ema: float | None = None
        self.avg_atr: float | None = None
        self.daily_atr: float = 0.0
        self.rsi: float | None = None

    def update(self, price: float, daily_atr: float, bar_high: float | None = None, bar_low: float | None = None) -> None:
        self.daily_atr = daily_atr
        self.rsi = self._rsi.update(price)
        # Track session high/low from actual bar data
        if bar_high is not None:
            self._session_high = max(self._session_high, bar_high)
        if bar_low is not None:
            self._session_low = min(self._session_low, bar_low)

    def on_session_close(self, close_price: float, _daily_atr: float) -> None:
        """Called once at the end of each session to update session-level indicators.

        Uses the actual session high-low range instead of the facade's global
        ATR average, which can be inflated by outlier days.
        """
        self.trend_ema = self._trend_ema.update(close_price)
        # Use real session range; fall back to facade ATR only if no bars tracked
        session_range = self._session_high - self._session_low
        atr_input = session_range if session_range > 0 else _daily_atr
        self.avg_atr = self._smoothed_atr.update(atr_input)
        # Reset for next session
        self._session_high = 0.0
        self._session_low = float("inf")


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
        trend_invert: bool = False,
        or_confirm: bool = False,
        or_wait_min: int = 15,
        or_threshold_atr: float = 0.0,
        momentum_filter: int = 0,
        mr_min_drop_atr: float = 0.0,
        rsi_filter_enabled: bool = False,
        rsi_max_entry: float = 70.0,
        sizing_mode: int = 0,
        risk_pct: float = 0.10,
    ) -> None:
        self._ind = indicators
        self._lots = lots
        self._contract_type = contract_type
        self._entry_offset_min = entry_offset_min
        self._entry_time = _night_entry_time(entry_offset_min)
        self._atr_sl_mult = atr_sl_mult
        self._use_atr_filter = use_atr_filter
        self._atr_filter_mult = atr_filter_mult
        self._use_trend_filter = use_trend_filter
        self._trend_invert = trend_invert
        self._or_confirm = or_confirm
        self._or_entry_time = _night_entry_time(or_wait_min) if or_confirm else self._entry_time
        self._or_threshold_atr = or_threshold_atr
        self._rsi_filter_enabled = rsi_filter_enabled
        self._rsi_max_entry = rsi_max_entry
        self._momentum_filter = momentum_filter
        self._mr_min_drop_atr = mr_min_drop_atr
        self._sizing_mode = sizing_mode
        self._risk_pct = risk_pct
        self._entered_this_session = False
        self._last_session_date = None
        self._session_open_price: float | None = None
        self._prev_session_was_positive: bool | None = None
        self._prev_session_drop_atr: float = 0.0
        self._last_price: float = 0.0

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
        self._last_price = snapshot.price

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
            # Close out previous session's indicators so avg_atr gets
            # populated even when no position was opened (avoids the
            # chicken-and-egg: no avg_atr → 0 lots → no position → no
            # session close → no avg_atr).
            if self._last_session_date is not None:
                prev_atr = snapshot.atr.get("daily", 0.0)
                if prev_atr > 0:
                    self._ind.on_session_close(snapshot.price, prev_atr)
                # Track whether the prior session was positive (close > open)
                if self._session_open_price is not None and self._last_price > 0:
                    self._prev_session_was_positive = (
                        self._last_price > self._session_open_price
                    )
                    # Track drop magnitude in ATR multiples
                    if prev_atr > 0:
                        self._prev_session_drop_atr = (
                            self._session_open_price - self._last_price
                        ) / prev_atr
                    else:
                        self._prev_session_drop_atr = 0.0
            self._last_session_date = session_key
            self._entered_this_session = False
            self._session_open_price = snapshot.price

        # Already entered this session
        if self._entered_this_session:
            return None

        # Already in position
        if engine_state.positions:
            return None

        # Determine effective entry time based on OR confirmation
        effective_entry_time = self._or_entry_time if self._or_confirm else self._entry_time

        # Wait for entry time
        if t < effective_entry_time and t >= NIGHT_OPEN:
            return None

        # On the after-midnight side, we've already passed entry_time
        # (entry_time is in the 15:xx range), so we should have entered

        daily_atr = snapshot.atr.get("daily", 0.0)
        if daily_atr <= 0:
            return None

        self._ind.update(snapshot.price, daily_atr, snapshot.bar_high, snapshot.bar_low)

        # OR momentum confirmation: price must be above session open + threshold
        if self._or_confirm and self._session_open_price is not None:
            threshold = self._or_threshold_atr * daily_atr if daily_atr > 0 else 0.0
            if snapshot.price <= self._session_open_price + threshold:
                self._entered_this_session = True
                return None

        # Session momentum filter (1=continuation, 2=mean reversion)
        if self._momentum_filter and self._prev_session_was_positive is not None:
            if self._momentum_filter == 1:
                if not self._prev_session_was_positive:
                    self._entered_this_session = True
                    return None
            elif self._momentum_filter == 2:
                if self._prev_session_was_positive:
                    self._entered_this_session = True
                    return None
                # Require minimum drop size for stronger mean reversion signal
                if self._mr_min_drop_atr > 0 and self._prev_session_drop_atr < self._mr_min_drop_atr:
                    self._entered_this_session = True
                    return None

        # ATR volatility filter
        if self._use_atr_filter and self._ind.avg_atr is not None:
            if daily_atr > self._atr_filter_mult * self._ind.avg_atr:
                return None

        # Trend filter (optionally inverted for mean-reversion pullback entries)
        if self._use_trend_filter and self._ind.trend_ema is not None:
            above_ema = snapshot.price > self._ind.trend_ema
            if self._trend_invert:
                if above_ema:
                    return None
            else:
                if not above_ema:
                    return None

        # RSI filter: skip entry when overbought
        if self._rsi_filter_enabled and self._ind.rsi is not None:
            if self._ind.rsi > self._rsi_max_entry:
                return None

        # Use smoothed ATR when available for more stable stop/sizing;
        # fall back to snapshot ATR during warmup period.
        effective_atr = self._ind.avg_atr if self._ind.avg_atr is not None else daily_atr
        sl_pts = effective_atr * self._atr_sl_mult
        self._entered_this_session = True

        # Dynamic sizing: compute lots from equity and risk fraction
        if self._sizing_mode == 1 and account is not None:
            lots = compute_risk_lots(
                equity=account.equity,
                stop_distance=sl_pts,
                point_value=snapshot.point_value,
                margin_per_unit=snapshot.margin_per_unit,
                max_equity_risk_pct=self._risk_pct,
                margin_limit=0.3,
            )
        else:
            lots = float(self._lots)

        if lots < 1.0:
            return None

        return EntryDecision(
            lots=lots,
            contract_type=self._contract_type,
            initial_stop=snapshot.price - sl_pts,
            direction="long",
            metadata={
                "daily_atr": daily_atr,
                "avg_atr": self._ind.avg_atr,
                "trend_ema": self._ind.trend_ema,
                "rsi": self._ind.rsi,
                "session_open": self._session_open_price,
                "sizing_mode": self._sizing_mode,
                "risk_pct": self._risk_pct,
            },
        )


# ── Stop Policy ──────────────────────────────────────────────────────────────

class NightSessionLongStop(StopPolicy):
    """ATR stop + optional breakeven/trailing stop + force close at session end."""

    def __init__(
        self,
        indicators: _Indicators,
        atr_sl_mult: float = 2.0,
        exit_before_close_min: int = 5,
        trail_enabled: bool = False,
        trail_trigger_atr: float = 1.0,
        trail_atr_mult: float = 1.5,
        breakeven_enabled: bool = False,
        breakeven_trigger_atr: float = 1.0,
        tp_enabled: bool = False,
        tp_atr_mult: float = 2.0,
    ) -> None:
        self._ind = indicators
        self._atr_sl_mult = atr_sl_mult
        self._exit_time = _night_exit_time(exit_before_close_min)
        self._trail_enabled = trail_enabled
        self._trail_trigger_atr = trail_trigger_atr
        self._trail_atr_mult = trail_atr_mult
        self._breakeven_enabled = breakeven_enabled
        self._breakeven_trigger_atr = breakeven_trigger_atr
        self._tp_enabled = tp_enabled
        self._tp_atr_mult = tp_atr_mult
        self._locked_atr: dict[str, float] = {}

    def initial_stop(
        self, entry_price: float, direction: str, snapshot: MarketSnapshot,
    ) -> float:
        daily_atr = max(snapshot.atr.get("daily", 0.0), 1e-6)
        sl_pts = daily_atr * self._atr_sl_mult
        return entry_price - sl_pts

    def update_stop(
        self,
        position: Position,
        snapshot: MarketSnapshot,
        high_history: deque[float],
    ) -> float:
        t = snapshot.timestamp.time()
        daily_atr = max(snapshot.atr.get("daily", 0.0), 1e-6)
        self._ind.update(snapshot.price, daily_atr, snapshot.bar_high, snapshot.bar_low)

        # Force close at session end
        if _past_exit_time(t, self._exit_time):
            self._ind.on_session_close(snapshot.price, daily_atr)
            return snapshot.price

        # Take-profit: exit when profit exceeds target
        if self._tp_enabled:
            pid_tp = position.position_id
            if pid_tp not in self._locked_atr:
                self._locked_atr[pid_tp] = daily_atr
            tp_dist = self._tp_atr_mult * self._locked_atr[pid_tp]
            if snapshot.price - position.entry_price >= tp_dist:
                return snapshot.price

        pid = position.position_id
        if pid not in self._locked_atr:
            self._locked_atr[pid] = daily_atr
        locked = self._locked_atr[pid]
        profit = snapshot.price - position.entry_price

        # Breakeven stop: move stop to entry price after profit threshold
        if self._breakeven_enabled:
            be_trigger = self._breakeven_trigger_atr * locked
            if profit >= be_trigger:
                be_stop = position.entry_price
                if be_stop > position.stop_level:
                    # Trailing stop can further raise from breakeven
                    if self._trail_enabled and high_history:
                        trail_trigger = self._trail_trigger_atr * locked
                        if profit >= trail_trigger:
                            highest = max(high_history)
                            trail_stop = highest - self._trail_atr_mult * locked
                            return max(trail_stop, be_stop)
                    return be_stop

        # Trailing stop logic (without breakeven)
        if self._trail_enabled and high_history:
            trail_trigger = self._trail_trigger_atr * locked
            if profit >= trail_trigger:
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
    trend_invert: int = 0,
    trail_enabled: int = 0,
    trail_trigger_atr: float = 1.0,
    trail_atr_mult: float = 1.5,
    or_confirm: int = 0,
    or_wait_min: int = 15,
    or_threshold_atr: float = 0.0,
    breakeven_enabled: int = 0,
    breakeven_trigger_atr: float = 1.0,
    tp_enabled: int = 0,
    tp_atr_mult: float = 2.0,
    momentum_filter: int = 0,
    mr_min_drop_atr: float = 0.0,
    rsi_filter_enabled: int = 0,
    rsi_max_entry: float = 70.0,
    rsi_period: int = 14,
    sizing_mode: int = 0,
    risk_pct: float = 0.10,
) -> "PositionEngine":
    """Build a PositionEngine for night session long strategy."""
    from src.core.position_engine import PositionEngine

    indicators = _Indicators(
        trend_ema_len=trend_ema_len,
        rsi_period=rsi_period,
    )

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
            trend_invert=bool(trend_invert),
            or_confirm=bool(or_confirm),
            or_wait_min=or_wait_min,
            or_threshold_atr=or_threshold_atr,
            momentum_filter=int(momentum_filter),
            mr_min_drop_atr=mr_min_drop_atr,
            rsi_filter_enabled=bool(rsi_filter_enabled),
            rsi_max_entry=rsi_max_entry,
            sizing_mode=sizing_mode,
            risk_pct=risk_pct,
        ),
        add_policy=NoAddPolicy(),
        stop_policy=NightSessionLongStop(
            indicators=indicators,
            atr_sl_mult=atr_sl_mult,
            exit_before_close_min=exit_before_close_min,
            trail_enabled=bool(trail_enabled),
            trail_trigger_atr=trail_trigger_atr,
            trail_atr_mult=trail_atr_mult,
            breakeven_enabled=bool(breakeven_enabled),
            breakeven_trigger_atr=breakeven_trigger_atr,
            tp_enabled=bool(tp_enabled),
            tp_atr_mult=tp_atr_mult,
        ),
        config=engine_config,
    )
