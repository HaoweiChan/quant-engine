"""Bollinger Pinbar Mean Reversion Strategy (intraday mean reversion).

Mean Reversion strategy using Bollinger Bands + Pinbar (Snap-back) pattern with
ADX regime filter to ensure entries only in range-bound markets.

Entry (Trigger + Confirmation):
1. STRETCH: Price must close OUTSIDE the Bollinger Band (2.0 StdDev)
2. SNAP: The next bar must close INSIDE the band (the "Pinbar" / snap-back signal)
3. FILTER: ADX < threshold (market is in a range-bound regime)

Why it works:
Trading mean reversion in a trending market is dangerous. The ADX filter ensures
entries only when the market is sideways (typically ~70% of the time).

Exit:
- ATR stop loss
- ATR take profit
- Force close at session boundaries
"""

from __future__ import annotations

from collections import deque
from datetime import datetime, time
from statistics import mean, stdev
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
from src.strategies._session_utils import in_day_session, in_force_close, in_night_session

if TYPE_CHECKING:
    from src.core.position_engine import PositionEngine


PARAM_SCHEMA: dict[str, dict] = {
    "bb_len": {
        "type": "int",
        "default": 20,
        "min": 10,
        "max": 50,
        "description": "Bollinger Bands lookback period.",
        "grid": [10, 15, 20, 30],
    },
    "bb_std_dev": {
        "type": "float",
        "default": 2.0,
        "min": 1.5,
        "max": 3.0,
        "description": "Bollinger Bands standard deviation multiplier.",
        "grid": [1.5, 2.0, 2.5, 3.0],
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
        "default": 25.0,
        "min": 20.0,
        "max": 35.0,
        "description": "ADX below this = range-bound (allow MR entries).",
        "grid": [20, 25, 30, 35],
    },
    "atr_sl_multi": {
        "type": "float",
        "default": 2.0,
        "min": 0.5,
        "max": 4.0,
        "description": "Stop loss as fraction of daily ATR.",
        "grid": [1.5, 2.0, 2.5, 3.0],
    },
    "atr_tp_multi": {
        "type": "float",
        "default": 3.0,
        "min": 1.0,
        "max": 6.0,
        "description": "Take profit as fraction of daily ATR.",
        "grid": [2.0, 3.0, 4.0, 5.0],
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
        "default": 120,
        "min": 30,
        "max": 300,
        "description": "Max bars to hold before time-exit.",
        "grid": [60, 90, 120, 180],
    },
}

STRATEGY_META: dict = {
    "category": StrategyCategory.MEAN_REVERSION,
    "signal_timeframe": SignalTimeframe.ONE_MIN,
    "holding_period": HoldingPeriod.SHORT_TERM,
    "stop_architecture": StopArchitecture.INTRADAY,
    "expected_duration_minutes": (20, 60),
    "tradeable_sessions": ["day", "night"],
    "bars_per_day": 1050,
    "presets": {
        "quick": {"n_bars": 21000, "note": "~1 month"},
        "standard": {"n_bars": 63000, "note": "~3 months"},
        "full_year": {"n_bars": 264600, "note": "~1 year"},
    },
    "description": (
        "Bollinger Pinbar is an intraday mean-reversion strategy. "
        "Uses Bollinger Bands + Pinbar snap-back pattern with ADX regime filter. "
        "Enters when price snaps back inside BB after being outside; ADX must be low."
    ),
}


def _in_low_edge_window(t: time) -> bool:
    if time(10, 30) <= t < time(12, 0):
        return True
    if t >= time(20, 0) or t < time(1, 0):
        return True
    return False


class _Indicators:
    """Rolling indicators: Bollinger Bands, ADX."""

    def __init__(
        self,
        bb_len: int,
        bb_std_dev: float,
        adx_len: int = 14,
    ) -> None:
        self._bb_len = bb_len
        self._bb_std_dev = bb_std_dev
        self._adx_len = adx_len
        self._adx_alpha = 2.0 / (adx_len + 1)
        max_buf = max(bb_len, adx_len)
        self._closes: deque[float] = deque(maxlen=max_buf + 1)
        self._last_ts: datetime | None = None
        self._bar_count: int = 0
        self._prev_price: float | None = None
        self._plus_dm_ema: float | None = None
        self._minus_dm_ema: float | None = None
        self._atr_ema: float | None = None
        self._adx_ema: float | None = None
        self.daily_atr: float = 0.0
        self.bb_upper: float | None = None
        self.bb_mid: float | None = None
        self.bb_lower: float | None = None
        self.adx: float = 0.0
        self._prev_close: float | None = None
        self._outside_band: bool = False

    def update(
        self,
        price: float,
        timestamp: datetime,
        daily_atr: float = 0.0,
    ) -> None:
        if timestamp == self._last_ts:
            return
        self._last_ts = timestamp
        prev = self._prev_close
        self._closes.append(price)
        self._prev_close = price
        self.daily_atr = daily_atr
        self._bar_count += 1
        self._update_adx(price)
        self._compute()

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

    def _compute(self) -> None:
        closes = list(self._closes)
        n = len(closes)
        if n < self._bb_len:
            return
        window = closes[-self._bb_len :]
        self.bb_mid = mean(window)
        sd = stdev(window) if len(window) > 1 else 0.0
        self.bb_upper = self.bb_mid + self._bb_std_dev * sd
        self.bb_lower = self.bb_mid - self._bb_std_dev * sd


class BollingerPinbarEntry(EntryPolicy):
    def __init__(
        self,
        indicators: _Indicators,
        lots: float = 1.0,
        contract_type: str = "large",
        bb_std_dev: float = 2.0,
        adx_threshold: float = 25.0,
        atr_sl_multi: float = 2.0,
        atr_tp_multi: float = 3.0,
        time_gate: bool = True,
    ) -> None:
        self._ind = indicators
        self._lots = lots
        self._contract_type = contract_type
        self._bb_std_dev = bb_std_dev
        self._adx_threshold = adx_threshold
        self._atr_sl_multi = atr_sl_multi
        self._atr_tp_multi = atr_tp_multi
        self._time_gate = time_gate
        self._prev_price: float | None = None
        self._was_outside_upper: bool = False
        self._was_outside_lower: bool = False

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
        self._ind.update(snapshot.price, snapshot.timestamp, daily_atr)
        ind = self._ind
        if ind.bb_upper is None or ind.bb_lower is None:
            return None
        if daily_atr <= 0:
            return None
        if ind.adx >= self._adx_threshold:
            return None
        price = snapshot.price
        sl_pts = daily_atr * self._atr_sl_multi
        outside_upper = price > ind.bb_upper
        outside_lower = price < ind.bb_lower
        inside_upper = price <= ind.bb_upper
        inside_lower = price >= ind.bb_lower
        long_signal = self._was_outside_lower and inside_lower
        short_signal = self._was_outside_upper and inside_upper
        self._was_outside_upper = outside_upper
        self._was_outside_lower = outside_lower
        if long_signal:
            return EntryDecision(
                lots=self._lots,
                contract_type=self._contract_type,
                initial_stop=price - sl_pts,
                direction="long",
                metadata={
                    "atr_tp_multi": self._atr_tp_multi,
                    "adx": round(ind.adx, 1),
                },
            )
        if short_signal:
            return EntryDecision(
                lots=self._lots,
                contract_type=self._contract_type,
                initial_stop=price + sl_pts,
                direction="short",
                metadata={
                    "atr_tp_multi": self._atr_tp_multi,
                    "adx": round(ind.adx, 1),
                },
            )
        return None


class BollingerPinbarStop(StopPolicy):
    def __init__(
        self,
        indicators: _Indicators,
        atr_sl_multi: float = 2.0,
        atr_tp_multi: float = 3.0,
        max_hold_bars: int = 120,
    ) -> None:
        self._ind = indicators
        self._atr_sl_multi = atr_sl_multi
        self._atr_tp_multi = atr_tp_multi
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
        self._ind.update(snapshot.price, snapshot.timestamp, daily_atr)
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
        else:
            if price <= entry - tp_pts:
                return price
        return position.stop_level


def create_bollinger_pinbar_engine(
    max_loss: float = 500_000.0,
    lots: float = 1.0,
    contract_type: str = "large",
    bb_len: int = 20,
    bb_std_dev: float = 2.0,
    adx_len: int = 14,
    adx_threshold: float = 25.0,
    atr_sl_multi: float = 2.0,
    atr_tp_multi: float = 3.0,
    time_gate: int = 1,
    max_hold_bars: int = 120,
) -> "PositionEngine":
    from src.core.position_engine import PositionEngine

    indicators = _Indicators(
        bb_len=bb_len,
        bb_std_dev=bb_std_dev,
        adx_len=adx_len,
    )
    config = EngineConfig(max_loss=max_loss)
    return PositionEngine(
        entry_policy=BollingerPinbarEntry(
            indicators=indicators,
            lots=lots,
            contract_type=contract_type,
            bb_std_dev=bb_std_dev,
            adx_threshold=adx_threshold,
            atr_sl_multi=atr_sl_multi,
            atr_tp_multi=atr_tp_multi,
            time_gate=bool(time_gate),
        ),
        add_policy=NoAddPolicy(),
        stop_policy=BollingerPinbarStop(
            indicators=indicators,
            atr_sl_multi=atr_sl_multi,
            atr_tp_multi=atr_tp_multi,
            max_hold_bars=max_hold_bars,
        ),
        config=config,
    )
