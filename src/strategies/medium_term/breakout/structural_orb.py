"""Medium-Term Structural ORB: Opening Range + Keltner + ADX + VWAP.

Adapted from the short-term structural ORB for multi-session holding.

Entry logic:
  Opening Range from [08:45, 09:00) bars (day session).
  Breakout: price > max(OR_high, KC_upper) for long, mirror for short.
  ADX gate: requires trending market (ADX >= threshold).
  VWAP directional alignment (optional).
  One trade per day.

Exit logic (medium-term pattern):
  Initial stop  : entry ± atr_sl_mult x ATR
  T1 target     : entry ± atr_t1_mult x ATR → move stop to breakeven
  Trail         : tighter of chandelier (peak - trail_atr_mult * ATR) and
                  EMA(slow) ± trail buffer
  Max hold bars : time-exit after N 15m bars
  No forced session close — holds overnight.
"""
from __future__ import annotations

from collections import deque
from datetime import date, datetime, time
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
from src.indicators import ADX, EMA, VWAP, compose_param_schema
from src.strategies import HoldingPeriod, SignalTimeframe, StopArchitecture, StrategyCategory
from src.strategies._session_utils import in_day_session, in_night_session, in_or_window

if TYPE_CHECKING:
    from src.core.position_engine import PositionEngine


def _mean(vals: list[float]) -> float:
    return sum(vals) / len(vals)


_INDICATOR_PARAMS = compose_param_schema({
    "adx_period": (ADX, "period"),
})
_INDICATOR_PARAMS["adx_period"]["min"] = 7
_INDICATOR_PARAMS["adx_period"]["max"] = 21
_INDICATOR_PARAMS["adx_period"]["description"] = "Smoothing period for ADX-like regime strength."

PARAM_SCHEMA: dict[str, dict] = {
    **_INDICATOR_PARAMS,
    "adx_threshold": {
        "type": "float", "default": 25.0, "min": 20.0, "max": 35.0,
        "description": "Minimum ADX score required to permit breakout entries.",
    },
    "keltner_period": {
        "type": "int", "default": 20, "min": 10, "max": 30,
        "description": "EMA smoothing period for Keltner midline.",
    },
    "keltner_mult": {
        "type": "float", "default": 1.5, "min": 1.0, "max": 3.0,
        "description": "ATR multiple for Keltner bands.",
    },
    "vwap_filter": {
        "type": "int", "default": 1, "min": 0, "max": 1,
        "description": "Enable (1) or disable (0) VWAP directional filter.",
    },
    "orb_min_width_pct": {
        "type": "float", "default": 0.0005, "min": 0.0002, "max": 0.005,
        "description": "Minimum OR width as fraction of current price.",
    },
    "orb_max_width_pct": {
        "type": "float", "default": 0.03, "min": 0.005, "max": 0.06,
        "description": "Maximum OR width as fraction of current price.",
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
        "type": "float", "default": 1.2, "min": 0.5, "max": 3.0,
        "description": "ATR multiplier for initial stop loss.",
    },
    "atr_t1_mult": {
        "type": "float", "default": 6.0, "min": 1.5, "max": 10.0,
        "description": "ATR multiplier for T1 target (breakeven trigger).",
    },
    "trail_atr_mult": {
        "type": "float", "default": 2.0, "min": 1.0, "max": 5.0,
        "description": "Chandelier trailing stop distance in ATR units.",
    },
    "ema_trail_buffer_pts": {
        "type": "float", "default": 12.0, "min": 0.0, "max": 30.0,
        "description": "Points buffer for EMA trail stop after breakeven.",
    },
    "max_hold_bars": {
        "type": "int", "default": 200, "min": 4, "max": 300,
        "description": "Max 15m bars to hold before time-exit (200 bars = ~50h).",
    },
    "allow_night": {
        "type": "int", "default": 0, "min": 0, "max": 1,
        "description": "Allow entries during night session (0=day only, 1=day+night).",
    },
}

STRATEGY_META: dict = {
    "category": StrategyCategory.BREAKOUT,
    "signal_timeframe": SignalTimeframe.FIFTEEN_MIN,
    "holding_period": HoldingPeriod.MEDIUM_TERM,
    "stop_architecture": StopArchitecture.SWING,
    "expected_duration_minutes": (120, 720),
    "tradeable_sessions": ["day"],
    "bars_per_day": 70,
    "presets": {
        "quick": {"n_bars": 1400, "note": "~1 month (20 trading days x 70 bars)"},
        "standard": {"n_bars": 4200, "note": "~3 months (60 trading days x 70 bars)"},
        "full_year": {"n_bars": 17640, "note": "~1 year (252 trading days x 70 bars)"},
    },
    "description": (
        "Medium-term Structural ORB: Opening Range + Keltner + ADX composite breakout. "
        "Entries on day session OR breakout confirmed by volatility/regime filters. "
        "Holds overnight. T1 -> breakeven, then chandelier + EMA trail. Pyramid support."
    ),
}

_ATR_SCALE = 1.6


# ---------------------------------------------------------------------------
# Indicators
# ---------------------------------------------------------------------------

class _Indicators:
    """Thin wrapper: centralized EMA/VWAP + custom KC-ADX coupled bands & ATR."""

    def __init__(
        self,
        keltner_period: int,
        keltner_mult: float,
        adx_period: int,
        ema_fast: int,
        ema_slow: int,
        atr_len: int,
    ) -> None:
        self._kc_mult = keltner_mult
        self._atr_len = atr_len
        self._ema_fast_ind = EMA(period=ema_fast)
        self._ema_slow_ind = EMA(period=ema_slow)
        self._vwap_ind = VWAP()
        self._closes: deque[float] = deque(maxlen=atr_len + 2)
        self._last_ts: datetime | None = None
        self.ema_fast: float | None = None
        self.ema_slow: float | None = None
        self.atr: float | None = None
        self.atr_avg: float | None = None
        self._atr_history: deque[float] = deque(maxlen=50)
        self.vwap: float | None = None
        # Custom KC + ADX (coupled via shared alpha/true-range)
        self._kc_alpha = 2.0 / (keltner_period + 1)
        self._dm_alpha = 1.0 / max(adx_period, 1)
        self._kc_ema: float | None = None
        self._kc_atr: float | None = None
        self.kc_mid: float | None = None
        self.kc_upper: float | None = None
        self.kc_lower: float | None = None
        self._last_price: float | None = None
        self._plus_dm: float = 0.0
        self._minus_dm: float = 0.0
        self.adx: float = 0.0

    def update(self, price: float, ts: datetime, volume: float = 0.0) -> None:
        if ts == self._last_ts:
            return
        self._last_ts = ts
        self._closes.append(price)
        self._vwap_ind.update(price, max(volume, 0.0), ts)
        self.vwap = self._vwap_ind.value
        self._update_keltner_adx(price)
        self._ema_fast_ind.update(price)
        self.ema_fast = self._ema_fast_ind.value
        self._ema_slow_ind.update(price)
        self.ema_slow = self._ema_slow_ind.value
        # Custom ATR (SMA of |delta-close| × scale)
        closes = list(self._closes)
        n = len(closes)
        if n >= self._atr_len + 1:
            diffs = [abs(closes[i] - closes[i - 1]) for i in range(n - self._atr_len, n)]
            self.atr = _mean(diffs) * _ATR_SCALE
            self._atr_history.append(self.atr)
            if len(self._atr_history) >= 10:
                self.atr_avg = _mean(list(self._atr_history))

    def _update_keltner_adx(self, price: float) -> None:
        if self._kc_ema is None:
            self._kc_ema = price
            self._kc_atr = 0.0
        else:
            self._kc_ema = self._kc_ema + self._kc_alpha * (price - self._kc_ema)
        self.kc_mid = self._kc_ema
        if self._last_price is None:
            self._last_price = price
            return
        delta = price - self._last_price
        tr = abs(delta)
        up_move = max(delta, 0.0)
        down_move = max(-delta, 0.0)
        self._kc_atr = (self._kc_atr or tr) + self._dm_alpha * (tr - (self._kc_atr or tr))
        self._plus_dm += self._dm_alpha * (up_move - self._plus_dm)
        self._minus_dm += self._dm_alpha * (down_move - self._minus_dm)
        atr_val = max(self._kc_atr or 0.0, 1e-6)
        if self.kc_mid is not None:
            width = self._kc_mult * atr_val
            self.kc_upper = self.kc_mid + width
            self.kc_lower = self.kc_mid - width
        plus_di = 100.0 * (self._plus_dm / atr_val)
        minus_di = 100.0 * (self._minus_dm / atr_val)
        dx = 100.0 * abs(plus_di - minus_di) / max(plus_di + minus_di, 1e-6)
        self.adx = self.adx + self._dm_alpha * (dx - self.adx)
        self._last_price = price

    def snapshot(self) -> dict[str, float | None]:
        return {
            "kc_upper": self.kc_upper, "kc_mid": self.kc_mid,
            "kc_lower": self.kc_lower, "ema_fast": self.ema_fast,
            "ema_slow": self.ema_slow, "vwap": self.vwap,
            "adx": self.adx if self.adx else None,
        }

    def indicator_meta(self) -> dict[str, dict]:
        return {
            "kc_upper":  {"panel": "price", "color": "#FF6B6B", "label": "KC Upper"},
            "kc_mid":    {"panel": "price", "color": "#4ECDC4", "label": "KC Mid"},
            "kc_lower":  {"panel": "price", "color": "#FF6B6B", "label": "KC Lower"},
            "ema_fast":  {"panel": "price", "color": "#FFE66D", "label": "EMA Fast"},
            "ema_slow":  {"panel": "price", "color": "#95E1D3", "label": "EMA Slow"},
            "vwap":      {"panel": "price", "color": "#DDA0DD", "label": "VWAP"},
            "adx":       {"panel": "sub",   "color": "#F38181", "label": "ADX"},
        }


# ---------------------------------------------------------------------------
# Per-day ORB state
# ---------------------------------------------------------------------------

class _DayState:
    def __init__(self) -> None:
        self.current_date: date | None = None
        self.or_high: float | None = None
        self.or_low: float | None = None
        self.or_frozen = False
        self.traded_today = False

    def reset_if_new_day(self, ts: datetime) -> None:
        d = ts.date()
        if d == self.current_date:
            return
        self.current_date = d
        self.or_high = None
        self.or_low = None
        self.or_frozen = False
        self.traded_today = False

    def update_or(self, price: float, ts: datetime) -> None:
        if self.or_frozen:
            return
        if in_or_window(ts.time()):
            self.or_high = max(self.or_high or price, price)
            self.or_low = min(self.or_low or price, price)

    def freeze_or(self) -> None:
        if self.or_high is None or self.or_low is None:
            return
        self.or_frozen = True

    @property
    def or_range(self) -> float:
        if self.or_high is None or self.or_low is None:
            return 0.0
        return self.or_high - self.or_low


# ---------------------------------------------------------------------------
# Entry policy
# ---------------------------------------------------------------------------

class StructuralORBEntryPolicy(EntryPolicy):
    """ORB + Keltner + ADX composite breakout with VWAP alignment."""

    def __init__(
        self,
        lots: float = 1.0,
        contract_type: str = "large",
        latest_entry_time: time = time(11, 0),
        adx_period: int = 14,
        adx_threshold: float = 25.0,
        keltner_period: int = 20,
        keltner_mult: float = 1.5,
        vwap_filter: int = 1,
        orb_min_width_pct: float = 0.0005,
        orb_max_width_pct: float = 0.03,
        ema_fast: int = 5,
        ema_slow: int = 13,
        atr_len: int = 10,
        atr_sl_mult: float = 1.2,
        atr_t1_mult: float = 6.0,
        allow_night: int = 0,
    ) -> None:
        self._lots = lots
        self._contract_type = contract_type
        self._latest_entry_time = latest_entry_time
        self._adx_threshold = adx_threshold
        self._vwap_filter = bool(vwap_filter)
        self._orb_min_width_pct = orb_min_width_pct
        self._orb_max_width_pct = orb_max_width_pct
        self._atr_sl_mult = atr_sl_mult
        self._atr_t1_mult = atr_t1_mult
        self._allow_night = bool(allow_night)
        self._state = _DayState()
        self.ind = _Indicators(
            keltner_period=keltner_period,
            keltner_mult=keltner_mult,
            adx_period=adx_period,
            ema_fast=ema_fast,
            ema_slow=ema_slow,
            atr_len=atr_len,
        )

    def should_enter(
        self,
        snapshot: MarketSnapshot,
        signal: MarketSignal | None,
        engine_state: EngineState,
        account: AccountState | None = None,
    ) -> EntryDecision | None:
        if engine_state.mode in ("halted", "rule_only"):
            return None
        ts = snapshot.timestamp
        t = ts.time()
        price = snapshot.price

        day_ok = in_day_session(t)
        night_ok = self._allow_night and in_night_session(t)
        if not (day_ok or night_ok):
            return None

        self._state.reset_if_new_day(ts)
        self.ind.update(price, ts, snapshot.volume)
        self._state.update_or(price, ts)

        if in_or_window(t):
            return None
        if t > self._latest_entry_time:
            return None
        if not self._state.or_frozen:
            self._state.freeze_or()
        if self._state.traded_today:
            return None
        if self._state.or_high is None or self._state.or_low is None:
            return None

        or_width_pct = self._state.or_range / max(price, 1e-6)
        if not (self._orb_min_width_pct <= or_width_pct <= self._orb_max_width_pct):
            self._state.traded_today = True
            return None

        if self.ind.adx < self._adx_threshold:
            return None

        atr = self.ind.atr
        if atr is None or atr <= 0:
            return None

        kc_upper = self.ind.kc_upper
        kc_lower = self.ind.kc_lower
        if kc_upper is None or kc_lower is None:
            return None

        long_breakout = price > max(self._state.or_high, kc_upper)
        short_breakout = price < min(self._state.or_low, kc_lower)

        vwap = self.ind.vwap
        if self._vwap_filter and vwap is not None:
            long_breakout = long_breakout and price > vwap
            short_breakout = short_breakout and price < vwap

        if not long_breakout and not short_breakout:
            return None

        direction = "long" if long_breakout else "short"
        if direction == "long":
            initial_stop = price - atr * self._atr_sl_mult
            t1_target = price + atr * self._atr_t1_mult
        else:
            initial_stop = price + atr * self._atr_sl_mult
            t1_target = price - atr * self._atr_t1_mult

        self._state.traded_today = True
        return EntryDecision(
            lots=self._lots,
            contract_type=self._contract_type,
            initial_stop=initial_stop,
            direction=direction,
            metadata={
                "adx": self.ind.adx, "vwap": vwap, "atr": atr,
                "or_width_pct": or_width_pct,
                "t1_target": t1_target,
                "strategy": "mt_structural_orb",
            },
        )


# ---------------------------------------------------------------------------
# Stop policy — T1 -> breakeven -> chandelier + EMA trail
# ---------------------------------------------------------------------------

class StructuralORBStopPolicy(StopPolicy):
    """T1 breakeven trigger, then tighter of chandelier and EMA(slow) trail."""

    def __init__(
        self,
        indicators: _Indicators,
        atr_sl_mult: float = 1.2,
        atr_t1_mult: float = 6.0,
        trail_atr_mult: float = 2.0,
        ema_trail_buffer_pts: float = 12.0,
        max_hold_bars: int = 200,
    ) -> None:
        self._ind = indicators
        self._atr_sl_mult = atr_sl_mult
        self._atr_t1_mult = atr_t1_mult
        self._trail_atr_mult = trail_atr_mult
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

        atr = self._ind.atr

        if position.direction == "long":
            # T1 breakeven trigger
            if (not self._at_breakeven
                    and self._t1_target is not None
                    and price >= self._t1_target
                    and stop < entry):
                self._at_breakeven = True
                return entry
            if self._at_breakeven:
                # Chandelier trail
                if high_history and atr is not None:
                    chandelier = max(high_history) - self._trail_atr_mult * atr
                else:
                    chandelier = stop
                # EMA trail
                if self._ind.ema_slow is not None:
                    ema_trail = self._ind.ema_slow - self._trail_buf
                else:
                    ema_trail = stop
                # Use the tighter (higher) of the two
                trail_level = max(chandelier, ema_trail)
                return max(stop, trail_level)
            # Pre-breakeven: move to breakeven if price moved 1 ATR in favor
            if atr is not None and price - entry > atr:
                new_stop = max(stop, entry)
                return new_stop
        else:
            # T1 breakeven trigger
            if (not self._at_breakeven
                    and self._t1_target is not None
                    and price <= self._t1_target
                    and stop > entry):
                self._at_breakeven = True
                return entry
            if self._at_breakeven:
                # Chandelier trail
                if high_history and atr is not None:
                    chandelier = min(high_history) + self._trail_atr_mult * atr
                else:
                    chandelier = stop
                # EMA trail
                if self._ind.ema_slow is not None:
                    ema_trail = self._ind.ema_slow + self._trail_buf
                else:
                    ema_trail = stop
                # Use the tighter (lower) of the two
                trail_level = min(chandelier, ema_trail)
                return min(stop, trail_level)
            # Pre-breakeven: move to breakeven if price moved 1 ATR in favor
            if atr is not None and entry - price > atr:
                new_stop = min(stop, entry)
                return new_stop

        return stop


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def create_structural_orb_engine(
    max_loss: float = 500_000,
    lots: float = 1.0,
    contract_type: str = "large",
    adx_period: int = 14,
    adx_threshold: float = 25.0,
    keltner_period: int = 20,
    keltner_mult: float = 1.5,
    vwap_filter: int = 1,
    orb_min_width_pct: float = 0.0005,
    orb_max_width_pct: float = 0.03,
    ema_fast: int = 5,
    ema_slow: int = 13,
    atr_len: int = 10,
    atr_sl_mult: float = 1.2,
    atr_t1_mult: float = 6.0,
    trail_atr_mult: float = 2.0,
    ema_trail_buffer_pts: float = 12.0,
    max_hold_bars: int = 200,
    allow_night: int = 0,
    pyramid_risk_level: int = 0,
) -> "PositionEngine":
    """Build a PositionEngine wired with the medium-term Structural ORB strategy."""
    from src.core.policies import PyramidAddPolicy
    from src.core.position_engine import PositionEngine
    from src.core.types import pyramid_config_from_risk_level

    entry = StructuralORBEntryPolicy(
        lots=lots,
        contract_type=contract_type,
        adx_period=adx_period,
        adx_threshold=adx_threshold,
        keltner_period=keltner_period,
        keltner_mult=keltner_mult,
        vwap_filter=vwap_filter,
        orb_min_width_pct=orb_min_width_pct,
        orb_max_width_pct=orb_max_width_pct,
        ema_fast=ema_fast,
        ema_slow=ema_slow,
        atr_len=atr_len,
        atr_sl_mult=atr_sl_mult,
        atr_t1_mult=atr_t1_mult,
        allow_night=allow_night,
    )
    stop = StructuralORBStopPolicy(
        indicators=entry.ind,
        atr_sl_mult=atr_sl_mult,
        atr_t1_mult=atr_t1_mult,
        trail_atr_mult=trail_atr_mult,
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
