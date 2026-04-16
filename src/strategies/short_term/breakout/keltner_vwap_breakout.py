"""Keltner + VWAP + ADX intraday strategy with RSI & volume confirmation.

Based on Seed Strategy Architecture for ML Agents:
- Keltner Channel (EMA ± K * daily_atr) defines volatility bands
- ADX regime filter: trades mean-reversion in chop, breakout in trend
- VWAP directional alignment (institutional baseline)
- RSI oversold/overbought confirmation for entries
- Volume spike confirmation
- Session-aware timing (TAIFEX day + night)
- Force-close at session boundaries
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
from src.indicators import ADX, EMA, RSI, VWAP, compose_param_schema
from src.strategies import HoldingPeriod, SignalTimeframe, StopArchitecture, StrategyCategory
from src.strategies._session_utils import in_day_session, in_force_close, in_night_session

if TYPE_CHECKING:
    from src.core.position_engine import PositionEngine


_INDICATOR_PARAMS = compose_param_schema({
    "adx_period": (ADX, "period"),
    "rsi_len": (RSI, "period"),
})
_INDICATOR_PARAMS["adx_period"]["default"] = 14
_INDICATOR_PARAMS["adx_period"]["min"] = 7
_INDICATOR_PARAMS["adx_period"]["max"] = 30
_INDICATOR_PARAMS["adx_period"]["description"] = "ADX smoothing period."
_INDICATOR_PARAMS["rsi_len"]["default"] = 3
_INDICATOR_PARAMS["rsi_len"]["min"] = 2
_INDICATOR_PARAMS["rsi_len"]["max"] = 30
_INDICATOR_PARAMS["rsi_len"]["description"] = "RSI lookback period."

PARAM_SCHEMA: dict[str, dict] = {
    "kc_len": {
        "type": "int",
        "default": 120,
        "min": 20,
        "max": 300,
        "description": "EMA lookback for Keltner midline (1-min bars).",
    },
    "kc_mult": {
        "type": "float",
        "default": 0.3,
        "min": 0.02,
        "max": 0.5,
        "description": "KC width as fraction of daily ATR.",
    },
    **_INDICATOR_PARAMS,
    "adx_threshold": {
        "type": "float",
        "default": 45.0,
        "min": 10.0,
        "max": 50.0,
        "description": "ADX above this = trending (breakout), below = choppy (reversion).",
    },
    "rsi_oversold": {
        "type": "float",
        "default": 30.0,
        "min": 10.0,
        "max": 45.0,
        "description": "RSI threshold for oversold (mean-reversion long).",
    },
    "rsi_overbought": {
        "type": "float",
        "default": 75.0,
        "min": 55.0,
        "max": 90.0,
        "description": "RSI threshold for overbought (mean-reversion short).",
    },
    "vwap_filter": {
        "type": "int",
        "default": 0,
        "min": 0,
        "max": 1,
        "description": "Require VWAP alignment for entries (1=on, 0=off).",
    },
    "atr_sl_multi": {
        "type": "float",
        "default": 0.6,
        "min": 0.1,
        "max": 2.0,
        "description": "Stop loss as fraction of daily ATR.",
    },
    "atr_tp_multi": {
        "type": "float",
        "default": 1.2,
        "min": 0.1,
        "max": 3.0,
        "description": "Take profit as fraction of daily ATR.",
    },
    "trend_ma_len": {
        "type": "int",
        "default": 200,
        "min": 50,
        "max": 500,
        "description": "Trend EMA lookback for extreme-trend filter.",
    },
    "trend_filter_atr": {
        "type": "float",
        "default": 3.0,
        "min": 0.5,
        "max": 5.0,
        "description": "Block entries when |price - trend_ema| > N * daily_atr.",
    },
    "vol_len": {
        "type": "int",
        "default": 20,
        "min": 5,
        "max": 100,
        "description": "Rolling window for average volume.",
    },
    "vol_mult": {
        "type": "float",
        "default": 1.2,
        "min": 0.5,
        "max": 5.0,
        "description": "Min volume spike vs rolling average for entry.",
    },
    "time_gate": {
        "type": "int",
        "default": 1,
        "min": 0,
        "max": 1,
        "description": "Block low-edge windows (1=on, 0=off).",
    },
    "max_hold_bars": {
        "type": "int",
        "default": 300,
        "min": 10,
        "max": 480,
        "description": "Max bars to hold before time-exit.",
    },
}

STRATEGY_META: dict = {
    "category": StrategyCategory.BREAKOUT,
    "signal_timeframe": SignalTimeframe.ONE_MIN,
    "holding_period": HoldingPeriod.SHORT_TERM,
    "stop_architecture": StopArchitecture.INTRADAY,
    "expected_duration_minutes": (20, 120),
    "tradeable_sessions": ["day", "night"],
    "bars_per_day": 1050,
    "description": "Keltner + VWAP + ADX regime-adaptive strategy with RSI and volume confirmation.",
}

_ENTRY_START_DAY = time(9, 5)
_ENTRY_END_DAY = time(13, 0)


def _in_low_edge_window(t: time) -> bool:
    """Block entries during historically low-edge TAIFEX windows."""
    if time(10, 30) <= t < time(12, 0):
        return True
    if t >= time(20, 0) or t < time(1, 0):
        return True
    return False


def _mean(vals: list[float]) -> float:
    return sum(vals) / len(vals)


class _Indicators:
    """Thin wrapper: centralized ADX/RSI/EMA/VWAP + custom KC bands & volume ratio."""

    def __init__(
        self,
        kc_len: int,
        kc_mult: float,
        rsi_len: int,
        adx_period: int,
        trend_ma_len: int,
        vol_len: int = 20,
    ) -> None:
        self._kc_mult = kc_mult
        self._kc_ema_ind = EMA(period=kc_len)
        self._trend_ema_ind = EMA(period=trend_ma_len)
        self._adx_ind = ADX(period=adx_period)
        self._rsi_ind = RSI(period=rsi_len)
        self._vwap_ind = VWAP()
        self._volumes: deque[float] = deque(maxlen=max(vol_len, 1) + 1)
        self._vol_len = vol_len
        self._last_ts: datetime | None = None
        self.kc_mid: float | None = None
        self.kc_upper: float | None = None
        self.kc_lower: float | None = None
        self.rsi: float | None = None
        self.adx: float = 0.0
        self.daily_atr: float = 0.0
        self.trend_ema: float | None = None
        self.vol_ratio: float | None = None
        self.vwap: float | None = None

    def update(
        self, price: float, timestamp: datetime, volume: float = 0.0, daily_atr: float = 0.0,
    ) -> None:
        if timestamp == self._last_ts:
            return
        self._last_ts = timestamp
        self.daily_atr = daily_atr
        self._vwap_ind.update(price, max(volume, 0.0), timestamp)
        self.vwap = self._vwap_ind.value
        self._adx_ind.update(price)
        self.adx = self._adx_ind.value or 0.0
        self._rsi_ind.update(price)
        self.rsi = self._rsi_ind.value
        self._kc_ema_ind.update(price)
        self.kc_mid = self._kc_ema_ind.value
        if self.kc_mid is not None and daily_atr > 0:
            width = self._kc_mult * daily_atr
            self.kc_upper = self.kc_mid + width
            self.kc_lower = self.kc_mid - width
        self._trend_ema_ind.update(price)
        self.trend_ema = self._trend_ema_ind.value
        # Volume ratio
        self._volumes.append(volume)
        vols = list(self._volumes)
        nv = len(vols)
        if nv >= self._vol_len and self._vol_len > 0:
            avg_vol = _mean(vols[-self._vol_len:])
            self.vol_ratio = vols[-1] / avg_vol if avg_vol > 0 else 0.0
        elif nv > 0 and vols[-1] > 0:
            self.vol_ratio = 1.0
        else:
            self.vol_ratio = None

    def snapshot(self) -> dict[str, float | None]:
        return {
            "kc_upper": self.kc_upper, "kc_mid": self.kc_mid,
            "kc_lower": self.kc_lower, "vwap": self.vwap,
            "trend_ema": self.trend_ema, "rsi": self.rsi,
            "adx": self.adx if self.adx else None,
        }

    def indicator_meta(self) -> dict[str, dict]:
        return {
            "kc_upper":  {"panel": "price", "color": "#FF6B6B", "label": "KC Upper"},
            "kc_mid":    {"panel": "price", "color": "#4ECDC4", "label": "KC Mid"},
            "kc_lower":  {"panel": "price", "color": "#FF6B6B", "label": "KC Lower"},
            "vwap":      {"panel": "price", "color": "#FFE66D", "label": "VWAP"},
            "trend_ema": {"panel": "price", "color": "#95E1D3", "label": "Trend EMA"},
            "rsi":       {"panel": "sub",   "color": "#A8D8EA", "label": "RSI"},
            "adx":       {"panel": "sub",   "color": "#F38181", "label": "ADX"},
        }


class KeltnerVWAPEntryPolicy(EntryPolicy):
    def __init__(
        self,
        indicators: _Indicators,
        lots: float = 1.0,
        contract_type: str = "large",
        adx_threshold: float = 25.0,
        vwap_filter: int = 1,
        atr_sl_multi: float = 0.5,
        atr_tp_multi: float = 0.8,
        rsi_oversold: float = 25.0,
        rsi_overbought: float = 75.0,
        trend_filter_atr: float = 2.0,
        vol_mult: float = 1.2,
        time_gate: bool = True,
    ) -> None:
        self._ind = indicators
        self._lots = lots
        self._contract_type = contract_type
        self._adx_threshold = adx_threshold
        self._use_vwap = bool(vwap_filter)
        self._atr_sl_multi = atr_sl_multi
        self._atr_tp_multi = atr_tp_multi
        self._rsi_oversold = rsi_oversold
        self._rsi_overbought = rsi_overbought
        self._trend_filter_atr = trend_filter_atr
        self._vol_mult = vol_mult
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
        if any(v is None for v in (ind.kc_lower, ind.kc_upper, ind.rsi, ind.trend_ema)):
            return None
        if daily_atr <= 0:
            return None
        # Extreme trend filter
        if abs(snapshot.price - ind.trend_ema) > self._trend_filter_atr * daily_atr:
            return None
        # Volume confirmation
        if ind.vol_ratio is not None and ind.vol_ratio < self._vol_mult:
            return None
        price = snapshot.price
        sl_pts = daily_atr * self._atr_sl_multi
        is_trending = ind.adx >= self._adx_threshold
        if not is_trending:
            # CHOPPY regime: mean reversion at KC extremes + RSI
            if price < ind.kc_lower and ind.rsi < self._rsi_oversold:
                if self._use_vwap and ind.vwap is not None and price > ind.vwap:
                    return None
                return EntryDecision(
                    lots=self._lots,
                    contract_type=self._contract_type,
                    initial_stop=price - sl_pts,
                    direction="long",
                    metadata={"regime": "MR", "adx": round(ind.adx, 1), "rsi": round(ind.rsi, 1), "atr_tp_multi": self._atr_tp_multi},
                )
            if price > ind.kc_upper and ind.rsi > self._rsi_overbought:
                if self._use_vwap and ind.vwap is not None and price < ind.vwap:
                    return None
                return EntryDecision(
                    lots=self._lots,
                    contract_type=self._contract_type,
                    initial_stop=price + sl_pts,
                    direction="short",
                    metadata={"regime": "MR", "adx": round(ind.adx, 1), "rsi": round(ind.rsi, 1), "atr_tp_multi": self._atr_tp_multi},
                )
        else:
            # TRENDING regime: breakout follow at KC extremes
            if price > ind.kc_upper:
                if self._use_vwap and ind.vwap is not None and price < ind.vwap:
                    return None
                return EntryDecision(
                    lots=self._lots,
                    contract_type=self._contract_type,
                    initial_stop=price - sl_pts,
                    direction="long",
                    metadata={"regime": "BO", "adx": round(ind.adx, 1), "rsi": round(ind.rsi, 1), "atr_tp_multi": self._atr_tp_multi},
                )
            if price < ind.kc_lower:
                if self._use_vwap and ind.vwap is not None and price > ind.vwap:
                    return None
                return EntryDecision(
                    lots=self._lots,
                    contract_type=self._contract_type,
                    initial_stop=price + sl_pts,
                    direction="short",
                    metadata={"regime": "BO", "adx": round(ind.adx, 1), "rsi": round(ind.rsi, 1), "atr_tp_multi": self._atr_tp_multi},
                )
        return None


class KeltnerVWAPStopPolicy(StopPolicy):
    """ATR stop + take-profit + force close at session boundaries."""

    def __init__(
        self,
        indicators: _Indicators,
        atr_sl_multi: float = 0.5,
        atr_tp_multi: float = 0.8,
        max_hold_bars: int = 120,
    ) -> None:
        self._ind = indicators
        self._atr_sl_multi = atr_sl_multi
        self._atr_tp_multi = atr_tp_multi
        self._max_hold = max_hold_bars
        self._locked_tp: float = 0.0
        self._bar_counts: dict[str, int] = {}

    def initial_stop(self, entry_price: float, direction: str, snapshot: MarketSnapshot) -> float:
        daily_atr = max(snapshot.atr.get("daily", 0.0), 1e-6)
        self._locked_tp = daily_atr * self._atr_tp_multi
        sl_pts = daily_atr * self._atr_sl_multi
        return entry_price + sl_pts if direction == "short" else entry_price - sl_pts

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
        # Force close: session end or max hold
        if in_force_close(t) or self._bar_counts[pid] >= self._max_hold:
            self._bar_counts.pop(pid, None)
            return price
        entry = position.entry_price
        tp_pts = self._locked_tp
        if position.direction == "long":
            if price >= entry + tp_pts:
                return price
        else:
            if price <= entry - tp_pts:
                return price
        return position.stop_level


def create_keltner_vwap_breakout_engine(
    max_loss: float = 500_000.0,
    lots: float = 1.0,
    contract_type: str = "large",
    kc_len: int = 120,
    kc_mult: float = 0.3,
    adx_period: int = 14,
    adx_threshold: float = 45.0,
    rsi_len: int = 3,
    rsi_oversold: float = 30.0,
    rsi_overbought: float = 75.0,
    vwap_filter: int = 0,
    atr_sl_multi: float = 0.6,
    atr_tp_multi: float = 1.2,
    trend_ma_len: int = 200,
    trend_filter_atr: float = 3.0,
    vol_len: int = 20,
    vol_mult: float = 1.2,
    time_gate: int = 1,
    max_hold_bars: int = 300,
) -> "PositionEngine":
    from src.core.position_engine import PositionEngine

    indicators = _Indicators(
        kc_len=kc_len,
        kc_mult=kc_mult,
        rsi_len=rsi_len,
        adx_period=adx_period,
        trend_ma_len=trend_ma_len,
        vol_len=vol_len,
    )
    config = EngineConfig(max_loss=max_loss)
    engine = PositionEngine(
        entry_policy=KeltnerVWAPEntryPolicy(
            indicators=indicators,
            lots=lots,
            contract_type=contract_type,
            adx_threshold=adx_threshold,
            vwap_filter=vwap_filter,
            atr_sl_multi=atr_sl_multi,
            atr_tp_multi=atr_tp_multi,
            rsi_oversold=rsi_oversold,
            rsi_overbought=rsi_overbought,
            trend_filter_atr=trend_filter_atr,
            vol_mult=vol_mult,
            time_gate=bool(time_gate),
        ),
        add_policy=NoAddPolicy(),
        stop_policy=KeltnerVWAPStopPolicy(
            indicators=indicators,
            atr_sl_multi=atr_sl_multi,
            atr_tp_multi=atr_tp_multi,
            max_hold_bars=max_hold_bars,
        ),
        config=config,
    )
    # Attach indicator provider for backtest chart visualization (duck-typed, no core changes)
    engine.indicator_provider = indicators  # type: ignore[attr-defined]
    return engine
