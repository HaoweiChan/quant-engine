"""Donchian Trend-Strength Strategy (intraday trend following).

Pullback entry within a trending regime identified by Donchian Channels
and VWAP alignment, with structural RSI/ADX confirmation per the
Seed Strategy Architecture.

Entry:
- Long when VWAP confirms uptrend (above channel mid), price pulls back
  to/below the Donchian mid, and RSI shows cooling momentum (< 55).
- Short when VWAP confirms downtrend (below channel mid), price rallies
  to/above the Donchian mid, and RSI shows elevated momentum (> 45).

Exit:
- ATR-based trailing stop that ratchets favorably
- ATR-based take profit
- Force close at session boundaries / max hold bars

Filters:
- ADX regime filter: only enter when ADX > threshold (trending market)
- VWAP directional alignment (institutional baseline vs channel midline)
- RSI structural filter (momentum direction, period <= 7)
- Day session (09:00-13:15) or night session (15:15-04:30)
- Time gate for low-edge windows
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


PARAM_SCHEMA: dict[str, dict] = {
    "lookback_period": {
        "type": "int",
        "default": 15,
        "min": 10,
        "max": 30,
        "description": "Donchian Channel lookback period (bars).",
        "grid": [10, 15, 20, 25, 30],
    },
    "adx_len": {
        "type": "int",
        "default": 14,
        "min": 7,
        "max": 30,
        "description": "ADX smoothing period.",
        "grid": [10, 14, 20],
    },
    "adx_threshold": {
        "type": "float",
        "default": 20.0,
        "min": 15.0,
        "max": 40.0,
        "description": "ADX above this = trending (allow entries).",
        "grid": [15, 20, 25, 30],
    },
    "rsi_len": {
        "type": "int",
        "default": 5,
        "min": 2,
        "max": 7,
        "description": "RSI period for structural momentum filter.",
        "grid": [3, 4, 5],
    },
    "rsi_long_thresh": {
        "type": "float",
        "default": 55.0,
        "min": 40.0,
        "max": 65.0,
        "description": "RSI must be below this for long entries (cooling pullback).",
        "grid": [45, 50, 55, 60],
    },
    "rsi_short_thresh": {
        "type": "float",
        "default": 45.0,
        "min": 35.0,
        "max": 60.0,
        "description": "RSI must be above this for short entries (heated rally).",
        "grid": [40, 45, 50, 55],
    },
    "atr_sl_multi": {
        "type": "float",
        "default": 0.5,
        "min": 0.1,
        "max": 2.0,
        "description": "Stop loss as fraction of daily ATR.",
        "grid": [0.3, 0.5, 0.8, 1.0],
    },
    "atr_tp_multi": {
        "type": "float",
        "default": 1.0,
        "min": 0.3,
        "max": 3.0,
        "description": "Take profit as fraction of daily ATR.",
        "grid": [0.8, 1.0, 1.5, 2.0],
    },
    "trail_atr_multi": {
        "type": "float",
        "default": 1.5,
        "min": 0.3,
        "max": 2.5,
        "description": "Trailing stop distance as fraction of daily ATR.",
        "grid": [0.8, 1.0, 1.5, 2.0],
    },
    "time_gate": {
        "type": "int",
        "default": 1,
        "min": 0,
        "max": 1,
        "description": "Block entries during low-edge windows (1=enabled, 0=disabled).",
    },
    "max_hold_bars": {
        "type": "int",
        "default": 60,
        "min": 30,
        "max": 300,
        "description": "Max bars to hold before time-exit.",
        "grid": [30, 45, 60, 90, 120],
    },
}

STRATEGY_META: dict = {
    "category": StrategyCategory.TREND_FOLLOWING,
    "timeframe": StrategyTimeframe.INTRADAY,
    "session": "both",
    "bars_per_day": 1050,
    "presets": {
        "quick": {"n_bars": 21000, "note": "~1 month"},
        "standard": {"n_bars": 63000, "note": "~3 months"},
        "full_year": {"n_bars": 264600, "note": "~1 year"},
    },
    "description": (
        "Donchian Trend-Strength is an intraday trend-following strategy. "
        "Uses Donchian Channels with VWAP-based trend detection and pullback "
        "entries at the channel midline. RSI and ADX structural confirmation."
    ),
}


def _in_low_edge_window(t: time) -> bool:
    if time(10, 30) <= t < time(12, 0):
        return True
    if t >= time(20, 0) or t < time(1, 0):
        return True
    return False


class _Indicators:
    """Rolling indicators: Donchian, VWAP, RSI, ADX."""

    def __init__(
        self,
        lookback_period: int,
        adx_len: int = 14,
        rsi_len: int = 5,
    ) -> None:
        self._lb = lookback_period
        self._adx_len = adx_len
        self._rsi_len = rsi_len
        self._adx_alpha = 2.0 / (adx_len + 1)
        self._closes: deque[float] = deque(maxlen=lookback_period + 1)
        self._last_ts: datetime | None = None
        self._bar_count: int = 0
        self._prev_price: float | None = None
        self._plus_dm_ema: float | None = None
        self._minus_dm_ema: float | None = None
        self._atr_ema: float | None = None
        self._adx_ema: float | None = None
        self._gains: deque[float] = deque(maxlen=rsi_len)
        self._losses: deque[float] = deque(maxlen=rsi_len)
        self._vwap_pv_sum: float = 0.0
        self._vwap_v_sum: float = 0.0
        self._vwap_session_date: datetime | None = None
        self.daily_atr: float = 0.0
        self.donchian_upper: float | None = None
        self.donchian_lower: float | None = None
        self.donchian_mid: float | None = None
        self.vwap: float | None = None
        self.rsi: float | None = None
        self.adx: float = 0.0

    def update(
        self,
        price: float,
        timestamp: datetime,
        volume: float,
        daily_atr: float = 0.0,
    ) -> None:
        if timestamp == self._last_ts:
            return
        self._last_ts = timestamp
        self._closes.append(price)
        self.daily_atr = daily_atr
        self._bar_count += 1
        self._update_adx(price)
        self._update_rsi(price)
        self._update_vwap(price, volume, timestamp)
        self._compute_donchian()

    def _update_adx(self, price: float) -> None:
        if self._prev_price is None:
            self._prev_price = price
            return
        tr = abs(price - self._prev_price)
        delta = price - self._prev_price
        pdm = max(delta, 0.0)
        mdm = max(-delta, 0.0)
        a = self._adx_alpha
        if self._atr_ema is None:
            self._atr_ema = tr
            self._plus_dm_ema = pdm
            self._minus_dm_ema = mdm
        else:
            self._atr_ema = a * tr + (1 - a) * self._atr_ema
            self._plus_dm_ema = a * pdm + (1 - a) * self._plus_dm_ema
            self._minus_dm_ema = a * mdm + (1 - a) * self._minus_dm_ema
        if self._atr_ema and self._atr_ema > 1e-9:
            pdi = 100.0 * (self._plus_dm_ema / self._atr_ema)
            mdi = 100.0 * (self._minus_dm_ema / self._atr_ema)
            denom = pdi + mdi
            if denom > 1e-9:
                dx = 100.0 * abs(pdi - mdi) / denom
                if self._adx_ema is None:
                    self._adx_ema = dx
                else:
                    self._adx_ema = a * dx + (1 - a) * self._adx_ema
                self.adx = self._adx_ema
        self._prev_price = price

    def _update_rsi(self, price: float) -> None:
        if len(self._closes) < 2:
            return
        prev = list(self._closes)[-2]
        delta = price - prev
        self._gains.append(max(delta, 0.0))
        self._losses.append(max(-delta, 0.0))
        if len(self._gains) < self._rsi_len:
            return
        avg_gain = sum(self._gains) / self._rsi_len
        avg_loss = sum(self._losses) / self._rsi_len
        if avg_loss < 1e-9:
            self.rsi = 100.0
        else:
            rs = avg_gain / avg_loss
            self.rsi = 100.0 - 100.0 / (1.0 + rs)

    def _update_vwap(self, price: float, volume: float, timestamp: datetime) -> None:
        session_key = timestamp.date()
        if self._vwap_session_date != session_key:
            self._vwap_pv_sum = 0.0
            self._vwap_v_sum = 0.0
            self._vwap_session_date = session_key
        self._vwap_pv_sum += price * max(volume, 1.0)
        self._vwap_v_sum += max(volume, 1.0)
        if self._vwap_v_sum > 0:
            self.vwap = self._vwap_pv_sum / self._vwap_v_sum

    def _compute_donchian(self) -> None:
        n = len(self._closes)
        if n < self._lb:
            return
        window = list(self._closes)[-self._lb:]
        self.donchian_upper = max(window)
        self.donchian_lower = min(window)
        self.donchian_mid = (self.donchian_upper + self.donchian_lower) / 2.0


class DonchianTrendStrengthEntry(EntryPolicy):
    def __init__(
        self,
        indicators: _Indicators,
        lots: float = 1.0,
        contract_type: str = "large",
        adx_threshold: float = 20.0,
        rsi_long_thresh: float = 55.0,
        rsi_short_thresh: float = 45.0,
        atr_sl_multi: float = 0.5,
        atr_tp_multi: float = 1.0,
        time_gate: bool = True,
    ) -> None:
        self._ind = indicators
        self._lots = lots
        self._contract_type = contract_type
        self._adx_threshold = adx_threshold
        self._rsi_long_thresh = rsi_long_thresh
        self._rsi_short_thresh = rsi_short_thresh
        self._atr_sl_multi = atr_sl_multi
        self._atr_tp_multi = atr_tp_multi
        self._time_gate = time_gate

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
        if in_force_close(t):
            return None
        if not (in_day_session(t) or in_night_session(t)):
            return None
        if self._time_gate and _in_low_edge_window(t):
            return None
        daily_atr = snapshot.atr.get("daily", 0.0)
        self._ind.update(snapshot.price, snapshot.timestamp, snapshot.volume, daily_atr)
        ind = self._ind
        if ind.donchian_mid is None or ind.vwap is None or ind.rsi is None:
            return None
        if daily_atr <= 0:
            return None
        if ind.adx < self._adx_threshold:
            return None
        price = snapshot.price
        sl_pts = daily_atr * self._atr_sl_multi
        uptrend = ind.vwap > ind.donchian_mid
        downtrend = ind.vwap < ind.donchian_mid
        if uptrend and price <= ind.donchian_mid and ind.rsi < self._rsi_long_thresh:
            return EntryDecision(
                lots=self._lots,
                contract_type=self._contract_type,
                initial_stop=price - sl_pts,
                direction="long",
                metadata={
                    "atr_tp_multi": self._atr_tp_multi,
                    "adx": round(ind.adx, 1),
                    "rsi": round(ind.rsi, 1),
                },
            )
        if downtrend and price >= ind.donchian_mid and ind.rsi > self._rsi_short_thresh:
            return EntryDecision(
                lots=self._lots,
                contract_type=self._contract_type,
                initial_stop=price + sl_pts,
                direction="short",
                metadata={
                    "atr_tp_multi": self._atr_tp_multi,
                    "adx": round(ind.adx, 1),
                    "rsi": round(ind.rsi, 1),
                },
            )
        return None


class DonchianTrendStrengthStop(StopPolicy):
    def __init__(
        self,
        indicators: _Indicators,
        atr_sl_multi: float = 0.5,
        atr_tp_multi: float = 1.0,
        trail_atr_multi: float = 1.5,
        max_hold_bars: int = 60,
    ) -> None:
        self._ind = indicators
        self._atr_sl_multi = atr_sl_multi
        self._atr_tp_multi = atr_tp_multi
        self._trail_atr_multi = trail_atr_multi
        self._max_hold = max_hold_bars
        self._locked_tp_pts: float = 0.0
        self._bar_counts: dict[str, int] = {}

    def initial_stop(
        self,
        entry_price: float,
        direction: str,
        snapshot: MarketSnapshot,
    ) -> float:
        daily_atr = max(snapshot.atr.get("daily", 0.0), 1e-6)
        self._locked_tp_pts = daily_atr * self._atr_tp_multi
        sl_pts = daily_atr * self._atr_sl_multi
        if direction == "short":
            return entry_price + sl_pts
        return entry_price - sl_pts

    def update_stop(
        self,
        position: Position,
        snapshot: MarketSnapshot,
        high_history: deque[float],
    ) -> float:
        daily_atr = max(snapshot.atr.get("daily", 0.0), 1e-6)
        self._ind.update(
            snapshot.price,
            snapshot.timestamp,
            snapshot.volume,
            daily_atr,
        )
        price = snapshot.price
        t = snapshot.timestamp.time()
        pid = position.position_id
        self._bar_counts[pid] = self._bar_counts.get(pid, 0) + 1
        if in_force_close(t) or self._bar_counts[pid] >= self._max_hold:
            self._bar_counts.pop(pid, None)
            return price
        entry = position.entry_price
        tp_pts = self._locked_tp_pts
        if position.direction == "long":
            if price >= entry + tp_pts:
                return price
            trail = price - daily_atr * self._trail_atr_multi
            return max(trail, position.stop_level)
        else:
            if price <= entry - tp_pts:
                return price
            trail = price + daily_atr * self._trail_atr_multi
            return min(trail, position.stop_level)


def create_donchian_trend_strength_engine(
    max_loss: float = 500_000.0,
    lots: float = 1.0,
    contract_type: str = "large",
    lookback_period: int = 15,
    adx_len: int = 14,
    adx_threshold: float = 20.0,
    rsi_len: int = 5,
    rsi_long_thresh: float = 55.0,
    rsi_short_thresh: float = 45.0,
    atr_sl_multi: float = 0.5,
    atr_tp_multi: float = 1.0,
    trail_atr_multi: float = 1.5,
    time_gate: int = 1,
    max_hold_bars: int = 60,
) -> "PositionEngine":
    from src.core.position_engine import PositionEngine

    indicators = _Indicators(
        lookback_period=lookback_period,
        adx_len=adx_len,
        rsi_len=rsi_len,
    )
    config = EngineConfig(max_loss=max_loss)
    return PositionEngine(
        entry_policy=DonchianTrendStrengthEntry(
            indicators=indicators,
            lots=lots,
            contract_type=contract_type,
            adx_threshold=adx_threshold,
            rsi_long_thresh=rsi_long_thresh,
            rsi_short_thresh=rsi_short_thresh,
            atr_sl_multi=atr_sl_multi,
            atr_tp_multi=atr_tp_multi,
            time_gate=bool(time_gate),
        ),
        add_policy=NoAddPolicy(),
        stop_policy=DonchianTrendStrengthStop(
            indicators=indicators,
            atr_sl_multi=atr_sl_multi,
            atr_tp_multi=atr_tp_multi,
            trail_atr_multi=trail_atr_multi,
            max_hold_bars=max_hold_bars,
        ),
        config=config,
    )
