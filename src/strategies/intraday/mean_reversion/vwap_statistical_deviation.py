"""VWAP Statistical-Deviation Mean Reversion Strategy (intraday mean reversion).

The "Quant's" mean reversion strategy. Focuses on the current session's
Volume Weighted Average Price (VWAP) rather than historical bars.

Entry:
- Calculate daily VWAP and its Standard Deviation bands
- When price hits the +N StdDev band AND Volume begins to taper (exhaustion),
  short the contract back to VWAP mean
- ADX regime filter: only enter when ADX < threshold (range-bound market)

Why it works:
Institutional algorithms use VWAP as "Fair Value". If the price is N standard
deviations away, it is mathematically "expensive" relative to every dollar
traded so far that day.

Exit:
- VWAP mean exit
- ATR stop loss
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
from src.strategies import StrategyCategory, StrategyTimeframe
from src.strategies._session_utils import in_day_session, in_force_close, in_night_session

if TYPE_CHECKING:
    from src.core.position_engine import PositionEngine


PARAM_SCHEMA: dict[str, dict] = {
    "entry_std": {
        "type": "float",
        "default": 3.0,
        "min": 2.5,
        "max": 4.0,
        "description": "VWAP StdDev band for entry (exhaustion point).",
        "grid": [2.5, 3.0, 3.5, 4.0],
    },
    "volume_taper_pct": {
        "type": "float",
        "default": 0.5,
        "min": 0.2,
        "max": 0.8,
        "description": "Volume taper fraction vs rolling avg to confirm reversal.",
        "grid": [0.3, 0.5, 0.7],
    },
    "vwap_len": {
        "type": "int",
        "default": 20,
        "min": 10,
        "max": 50,
        "description": "Rolling window for VWAP StdDev calculation.",
        "grid": [10, 20, 30],
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
        "default": 2.0,
        "min": 0.5,
        "max": 4.0,
        "description": "Take profit as fraction of daily ATR.",
        "grid": [1.5, 2.0, 2.5, 3.0],
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
    "timeframe": StrategyTimeframe.INTRADAY,
    "session": "both",
    "bars_per_day": 1050,
    "presets": {
        "quick": {"n_bars": 21000, "note": "~1 month"},
        "standard": {"n_bars": 63000, "note": "~3 months"},
        "full_year": {"n_bars": 264600, "note": "~1 year"},
    },
    "description": (
        "VWAP Statistical-Deviation is an intraday mean-reversion strategy. "
        "Uses VWAP + StdDev bands with volume taper confirmation and ADX regime filter. "
        "Enters when price reaches extreme StdDev deviation with volume exhaustion."
    ),
}


def _in_low_edge_window(t: time) -> bool:
    if time(10, 30) <= t < time(12, 0):
        return True
    if t >= time(20, 0) or t < time(1, 0):
        return True
    return False


class _Indicators:
    """Rolling indicators: VWAP, VWAP StdDev, ADX, Volume Taper."""

    def __init__(
        self,
        vwap_len: int,
        entry_std: float,
        volume_taper_pct: float,
        adx_len: int = 14,
    ) -> None:
        self._vwap_len = vwap_len
        self._entry_std = entry_std
        self._volume_taper_pct = volume_taper_pct
        self._adx_len = adx_len
        self._adx_alpha = 2.0 / (adx_len + 1)
        max_buf = max(vwap_len, adx_len)
        self._vwap_devs: deque[float] = deque(maxlen=max_buf + 1)
        self._volumes: deque[float] = deque(maxlen=vwap_len + 1)
        self._last_ts: datetime | None = None
        self._bar_count: int = 0
        self._prev_price: float | None = None
        self._plus_dm_ema: float | None = None
        self._minus_dm_ema: float | None = None
        self._atr_ema: float | None = None
        self._adx_ema: float | None = None
        self.daily_atr: float = 0.0
        self.vwap: float | None = None
        self.vwap_upper: float | None = None
        self.vwap_lower: float | None = None
        self.adx: float = 0.0
        self.vol_taper: float | None = None
        self._vwap_date = None
        self._cum_pv = 0.0
        self._cum_vol = 0.0

    def update(
        self,
        price: float,
        timestamp: datetime,
        volume: float = 0.0,
        daily_atr: float = 0.0,
    ) -> None:
        if timestamp == self._last_ts:
            return
        self._last_ts = timestamp
        self._volumes.append(max(volume, 0.0))
        self.daily_atr = daily_atr
        self._bar_count += 1
        self._update_vwap(timestamp, price, volume)
        self._update_adx(price)
        self._compute_devs()
        self._compute_vol_taper()

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

    def _compute_devs(self) -> None:
        if self.vwap is None:
            return
        self._vwap_devs.append(self.vwap)
        devs = list(self._vwap_devs)
        n = len(devs)
        if n < self._vwap_len:
            return
        recent = devs[-self._vwap_len :]
        avg_dev = mean(recent)
        sd = stdev(recent) if len(recent) > 1 else 0.0
        self.vwap_upper = self.vwap + self._entry_std * sd
        self.vwap_lower = self.vwap - self._entry_std * sd

    def _compute_vol_taper(self) -> None:
        vols = list(self._volumes)
        nv = len(vols)
        if nv < self._vwap_len:
            return
        window = vols[-self._vwap_len :]
        avg_vol = mean(window)
        latest_vol = vols[-1]
        if avg_vol > 0:
            self.vol_taper = latest_vol / avg_vol
        else:
            self.vol_taper = None


class VWAPStatisticalDeviationEntry(EntryPolicy):
    def __init__(
        self,
        indicators: _Indicators,
        lots: float = 1.0,
        contract_type: str = "large",
        entry_std: float = 3.0,
        volume_taper_pct: float = 0.5,
        adx_threshold: float = 25.0,
        atr_sl_multi: float = 2.0,
        atr_tp_multi: float = 2.0,
        time_gate: bool = True,
    ) -> None:
        self._ind = indicators
        self._lots = lots
        self._contract_type = contract_type
        self._entry_std = entry_std
        self._volume_taper_pct = volume_taper_pct
        self._adx_threshold = adx_threshold
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
        if ind.vwap_upper is None or ind.vwap_lower is None:
            return None
        if daily_atr <= 0:
            return None
        if ind.adx >= self._adx_threshold:
            return None
        vol_taper = ind.vol_taper
        if vol_taper is not None and vol_taper > self._volume_taper_pct:
            return None
        price = snapshot.price
        sl_pts = daily_atr * self._atr_sl_multi
        if price >= ind.vwap_upper:
            return EntryDecision(
                lots=self._lots,
                contract_type=self._contract_type,
                initial_stop=price - sl_pts,
                direction="short",
                metadata={
                    "atr_tp_multi": self._atr_tp_multi,
                    "adx": round(ind.adx, 1),
                    "vol_taper": round(vol_taper, 3) if vol_taper else None,
                },
            )
        if price <= ind.vwap_lower:
            return EntryDecision(
                lots=self._lots,
                contract_type=self._contract_type,
                initial_stop=price + sl_pts,
                direction="long",
                metadata={
                    "atr_tp_multi": self._atr_tp_multi,
                    "adx": round(ind.adx, 1),
                    "vol_taper": round(vol_taper, 3) if vol_taper else None,
                },
            )
        return None


class VWAPStatisticalDeviationStop(StopPolicy):
    def __init__(
        self,
        indicators: _Indicators,
        atr_sl_multi: float = 2.0,
        atr_tp_multi: float = 2.0,
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
        self._ind.update(snapshot.price, snapshot.timestamp, snapshot.volume, daily_atr)
        price = snapshot.price
        t = snapshot.timestamp.time()
        pid = position.position_id
        self._bar_counts[pid] = self._bar_counts.get(pid, 0) + 1
        if in_force_close(t) or self._bar_counts[pid] >= self._max_hold:
            self._bar_counts.pop(pid, None)
            return price
        vwap = self._ind.vwap
        if vwap is not None:
            if position.direction == "long" and price >= vwap:
                return price
            if position.direction == "short" and price <= vwap:
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


def create_vwap_statistical_deviation_engine(
    max_loss: float = 500_000.0,
    lots: float = 1.0,
    contract_type: str = "large",
    entry_std: float = 3.0,
    volume_taper_pct: float = 0.5,
    vwap_len: int = 20,
    adx_len: int = 14,
    adx_threshold: float = 25.0,
    atr_sl_multi: float = 2.0,
    atr_tp_multi: float = 2.0,
    time_gate: int = 1,
    max_hold_bars: int = 120,
) -> "PositionEngine":
    from src.core.position_engine import PositionEngine

    indicators = _Indicators(
        vwap_len=vwap_len,
        entry_std=entry_std,
        volume_taper_pct=volume_taper_pct,
        adx_len=adx_len,
    )
    config = EngineConfig(max_loss=max_loss)
    return PositionEngine(
        entry_policy=VWAPStatisticalDeviationEntry(
            indicators=indicators,
            lots=lots,
            contract_type=contract_type,
            entry_std=entry_std,
            volume_taper_pct=volume_taper_pct,
            adx_threshold=adx_threshold,
            atr_sl_multi=atr_sl_multi,
            atr_tp_multi=atr_tp_multi,
            time_gate=bool(time_gate),
        ),
        add_policy=NoAddPolicy(),
        stop_policy=VWAPStatisticalDeviationStop(
            indicators=indicators,
            atr_sl_multi=atr_sl_multi,
            atr_tp_multi=atr_tp_multi,
            max_hold_bars=max_hold_bars,
        ),
        config=config,
    )
