"""Structural intraday seed strategy: ORB + Keltner + ADX + optional VWAP filter."""
from __future__ import annotations

from collections import deque
from typing import TYPE_CHECKING
from datetime import date, datetime, time

from src.core.types import (
    AccountState,
    EngineConfig,
    EngineState,
    EntryDecision,
    MarketSignal,
    MarketSnapshot,
    Position,
)
from src.core.policies import EntryPolicy, NoAddPolicy, StopPolicy
from src.strategies import StrategyCategory, StrategyTimeframe
from src.strategies._session_utils import in_day_session, in_or_window

if TYPE_CHECKING:
    from src.core.position_engine import PositionEngine


PARAM_SCHEMA: dict[str, dict] = {
    "adx_period": {
        "type": "int",
        "default": 14,
        "min": 7,
        "max": 21,
        "description": "Smoothing period for ADX-like regime strength.",
        "grid": [10, 14, 18],
    },
    "adx_threshold": {
        "type": "float",
        "default": 25.0,
        "min": 20.0,
        "max": 35.0,
        "description": "Minimum ADX-like score required to permit breakout entries.",
        "grid": [22.0, 25.0, 30.0],
    },
    "keltner_period": {
        "type": "int",
        "default": 20,
        "min": 10,
        "max": 30,
        "description": "EMA/ATR smoothing period for Keltner envelope.",
        "grid": [14, 20, 26],
    },
    "keltner_mult": {
        "type": "float",
        "default": 1.5,
        "min": 1.0,
        "max": 3.0,
        "description": "ATR multiple used to compute Keltner bands.",
        "grid": [1.2, 1.5, 2.0],
    },
    "vwap_filter": {
        "type": "int",
        "default": 1,
        "min": 0,
        "max": 1,
        "description": "Enable (1) or disable (0) daily VWAP directional filter.",
    },
    "orb_min_width_pct": {
        "type": "float",
        "default": 0.0005,
        "min": 0.0002,
        "max": 0.005,
        "description": "Minimum OR width as fraction of current price.",
    },
    "orb_max_width_pct": {
        "type": "float",
        "default": 0.03,
        "min": 0.005,
        "max": 0.06,
        "description": "Maximum OR width as fraction of current price.",
    },
    "stop_atr_mult": {
        "type": "float",
        "default": 1.2,
        "min": 0.8,
        "max": 3.0,
        "description": "Initial stop distance in ATR units.",
        "grid": [1.0, 1.2, 1.6],
    },
    "trail_atr_mult": {
        "type": "float",
        "default": 2.0,
        "min": 1.0,
        "max": 5.0,
        "description": "Trailing stop distance in ATR units.",
        "grid": [1.5, 2.0, 3.0],
    },
}

STRATEGY_META: dict = {
    "category": StrategyCategory.BREAKOUT,
    "timeframe": StrategyTimeframe.INTRADAY,
    "session": "day",
    "description": "Structural ORB seed with volatility/regime filters (Keltner + ADX + VWAP).",
}


class _DayState:
    def __init__(self) -> None:
        self.current_date: date | None = None
        self.or_high: float | None = None
        self.or_low: float | None = None
        self.or_frozen = False
        self.traded_today = False
        self.cum_pv = 0.0
        self.cum_vol = 0.0

    def reset_if_new_day(self, ts: datetime) -> None:
        d = ts.date()
        if d == self.current_date:
            return
        self.current_date = d
        self.or_high = None
        self.or_low = None
        self.or_frozen = False
        self.traded_today = False
        self.cum_pv = 0.0
        self.cum_vol = 0.0

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

    @property
    def vwap(self) -> float | None:
        if self.cum_vol <= 0:
            return None
        return self.cum_pv / self.cum_vol


class StructuralORBEntryPolicy(EntryPolicy):
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
        stop_atr_mult: float = 1.2,
    ) -> None:
        self._lots = lots
        self._contract_type = contract_type
        self._latest_entry_time = latest_entry_time
        self._adx_threshold = adx_threshold
        self._vwap_filter = bool(vwap_filter)
        self._orb_min_width_pct = orb_min_width_pct
        self._orb_max_width_pct = orb_max_width_pct
        self._stop_atr_mult = stop_atr_mult
        self._ema_alpha = 2.0 / (keltner_period + 1.0)
        self._dm_alpha = 1.0 / max(adx_period, 1)
        self._keltner_mult = keltner_mult
        self._state = _DayState()
        self._ema: float | None = None
        self._atr: float | None = None
        self._plus_dm: float = 0.0
        self._minus_dm: float = 0.0
        self._adx: float = 0.0
        self._last_price: float | None = None

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
        self._state.reset_if_new_day(ts)
        self._update_indicators(snapshot)
        self._state.update_or(snapshot.price, ts)
        if in_or_window(ts.time()) or not in_day_session(ts.time()):
            return None
        if ts.time() > self._latest_entry_time:
            return None
        if not self._state.or_frozen:
            self._state.freeze_or()
        if self._state.traded_today:
            return None
        if self._state.or_high is None or self._state.or_low is None:
            return None
        or_width_pct = self._state.or_range / max(snapshot.price, 1e-6)
        if not (self._orb_min_width_pct <= or_width_pct <= self._orb_max_width_pct):
            self._state.traded_today = True
            return None
        if self._adx < self._adx_threshold:
            return None
        atr = self._atr_value(snapshot)
        kc_upper = self._ema_value(snapshot.price) + self._keltner_mult * atr
        kc_lower = self._ema_value(snapshot.price) - self._keltner_mult * atr
        long_breakout = snapshot.price > max(self._state.or_high, kc_upper)
        short_breakout = snapshot.price < min(self._state.or_low, kc_lower)
        vwap = self._state.vwap
        if self._vwap_filter and vwap is not None:
            long_breakout = long_breakout and snapshot.price > vwap
            short_breakout = short_breakout and snapshot.price < vwap
        if not long_breakout and not short_breakout:
            return None
        direction = "long" if long_breakout else "short"
        stop_distance = self._stop_atr_mult * atr
        if stop_distance <= 0:
            return None
        stop_level = snapshot.price - stop_distance if direction == "long" else snapshot.price + stop_distance
        self._state.traded_today = True
        return EntryDecision(
            lots=self._lots,
            contract_type=self._contract_type,
            initial_stop=stop_level,
            direction=direction,
            metadata={"adx": self._adx, "vwap": vwap, "or_width_pct": or_width_pct},
        )

    def _update_indicators(self, snapshot: MarketSnapshot) -> None:
        price = snapshot.price
        volume = max(snapshot.volume, 0.0)
        self._state.cum_pv += price * volume
        self._state.cum_vol += volume
        if self._ema is None:
            self._ema = price
            self._atr = snapshot.atr.get("daily", 0.0) / 100.0
            self._last_price = price
            return
        prev_price = self._last_price if self._last_price is not None else price
        delta = price - prev_price
        tr = abs(delta)
        up_move = max(delta, 0.0)
        down_move = max(-delta, 0.0)
        self._ema = self._ema + self._ema_alpha * (price - self._ema)
        self._atr = (self._atr or tr) + self._dm_alpha * (tr - (self._atr or tr))
        self._plus_dm = self._plus_dm + self._dm_alpha * (up_move - self._plus_dm)
        self._minus_dm = self._minus_dm + self._dm_alpha * (down_move - self._minus_dm)
        atr = max(self._atr or 0.0, 1e-6)
        plus_di = 100.0 * (self._plus_dm / atr)
        minus_di = 100.0 * (self._minus_dm / atr)
        dx = 100.0 * abs(plus_di - minus_di) / max(plus_di + minus_di, 1e-6)
        self._adx = self._adx + self._dm_alpha * (dx - self._adx)
        self._last_price = price

    def _atr_value(self, snapshot: MarketSnapshot) -> float:
        intraday_atr = self._atr or 0.0
        daily_proxy = snapshot.atr.get("daily", 0.0) / 100.0
        return max(intraday_atr, daily_proxy, 1e-6)

    def _ema_value(self, fallback_price: float) -> float:
        return self._ema if self._ema is not None else fallback_price


class StructuralORBStopPolicy(StopPolicy):
    def __init__(self, stop_atr_mult: float = 1.2, trail_atr_mult: float = 2.0) -> None:
        self._stop_atr_mult = stop_atr_mult
        self._trail_atr_mult = trail_atr_mult

    def initial_stop(self, entry_price: float, direction: str, snapshot: MarketSnapshot) -> float:
        atr = max(snapshot.atr.get("daily", 0.0) / 100.0, 1e-6)
        distance = atr * self._stop_atr_mult
        if direction == "short":
            return entry_price + distance
        return entry_price - distance

    def update_stop(
        self,
        position: Position,
        snapshot: MarketSnapshot,
        high_history: deque[float],
    ) -> float:
        atr = max(snapshot.atr.get("daily", 0.0) / 100.0, 1e-6)
        new_stop = position.stop_level
        if position.direction == "long":
            if snapshot.price - position.entry_price > atr:
                new_stop = max(new_stop, position.entry_price)
            if high_history:
                chandelier = max(high_history) - self._trail_atr_mult * atr
                new_stop = max(new_stop, chandelier)
        else:
            if position.entry_price - snapshot.price > atr:
                new_stop = min(new_stop, position.entry_price)
            if high_history:
                chandelier = min(high_history) + self._trail_atr_mult * atr
                new_stop = min(new_stop, chandelier)
        return new_stop


def create_structural_orb_engine(
    max_loss: float = 500_000.0,
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
    stop_atr_mult: float = 1.2,
    trail_atr_mult: float = 2.0,
) -> "PositionEngine":
    from src.core.position_engine import PositionEngine

    engine_config = EngineConfig(max_loss=max_loss)
    return PositionEngine(
        entry_policy=StructuralORBEntryPolicy(
            lots=lots,
            contract_type=contract_type,
            latest_entry_time=latest_entry_time,
            adx_period=adx_period,
            adx_threshold=adx_threshold,
            keltner_period=keltner_period,
            keltner_mult=keltner_mult,
            vwap_filter=vwap_filter,
            orb_min_width_pct=orb_min_width_pct,
            orb_max_width_pct=orb_max_width_pct,
            stop_atr_mult=stop_atr_mult,
        ),
        add_policy=NoAddPolicy(),
        stop_policy=StructuralORBStopPolicy(
            stop_atr_mult=stop_atr_mult,
            trail_atr_mult=trail_atr_mult,
        ),
        config=engine_config,
    )
