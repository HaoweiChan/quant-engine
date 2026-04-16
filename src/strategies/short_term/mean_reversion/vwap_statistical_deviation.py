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
from src.indicators import ADX, VWAP, compose_param_schema
from src.strategies import HoldingPeriod, SignalTimeframe, StopArchitecture, StrategyCategory
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
    },
    "volume_taper_pct": {
        "type": "float",
        "default": 0.5,
        "min": 0.2,
        "max": 0.8,
        "description": "Volume taper fraction vs rolling avg to confirm reversal.",
    },
    "vwap_len": {
        "type": "int",
        "default": 20,
        "min": 10,
        "max": 50,
        "description": "Rolling window for VWAP StdDev calculation.",
    },
    **compose_param_schema({"adx_len": (ADX, "period")}),
    "adx_threshold": {
        "type": "float",
        "default": 25.0,
        "min": 20.0,
        "max": 35.0,
        "description": "ADX below this = range-bound (allow MR entries).",
    },
    "atr_sl_multi": {
        "type": "float",
        "default": 2.0,
        "min": 0.5,
        "max": 4.0,
        "description": "Stop loss as fraction of daily ATR.",
    },
    "atr_tp_multi": {
        "type": "float",
        "default": 2.0,
        "min": 0.5,
        "max": 4.0,
        "description": "Take profit as fraction of daily ATR.",
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
    """Thin wrapper: centralized VWAP/ADX + custom std-dev bands and volume taper."""

    def __init__(
        self,
        vwap_len: int,
        entry_std: float,
        volume_taper_pct: float,
        adx_len: int = 14,
    ) -> None:
        self._vwap_len = vwap_len
        self._entry_std = entry_std
        self._vwap_ind = VWAP()
        self._adx_ind = ADX(period=adx_len)
        self._vwap_devs: deque[float] = deque(maxlen=vwap_len + 1)
        self._volumes: deque[float] = deque(maxlen=vwap_len + 1)
        self._last_ts: datetime | None = None
        self.daily_atr: float = 0.0
        self.vwap: float | None = None
        self.vwap_upper: float | None = None
        self.vwap_lower: float | None = None
        self.adx: float = 0.0
        self.vol_taper: float | None = None

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
        self._vwap_ind.update(price, max(volume, 0.0), timestamp)
        self.vwap = self._vwap_ind.value
        self._adx_ind.update(price)
        self.adx = self._adx_ind.value or 0.0
        self._compute_devs()
        self._compute_vol_taper()

    def _compute_devs(self) -> None:
        if self.vwap is None:
            return
        self._vwap_devs.append(self.vwap)
        devs = list(self._vwap_devs)
        if len(devs) < self._vwap_len:
            return
        recent = devs[-self._vwap_len:]
        sd = stdev(recent) if len(recent) > 1 else 0.0
        self.vwap_upper = self.vwap + self._entry_std * sd
        self.vwap_lower = self.vwap - self._entry_std * sd

    def _compute_vol_taper(self) -> None:
        vols = list(self._volumes)
        if len(vols) < self._vwap_len:
            return
        window = vols[-self._vwap_len:]
        avg_vol = mean(window)
        self.vol_taper = vols[-1] / avg_vol if avg_vol > 0 else None


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
