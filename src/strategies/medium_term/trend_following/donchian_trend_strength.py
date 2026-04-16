"""Donchian Trend-Strength Strategy (medium-term trend following).

Pullback entry within a trending regime identified by Donchian Channels
and VWAP alignment. Designed for multi-hour to multi-day holds on
aggregated bars (5m/15m/1h).

Entry:
- Long when VWAP confirms uptrend (above channel mid), price pulls back
  to/below the Donchian mid, and volume confirms interest.
- Short when VWAP confirms downtrend (below channel mid), price rallies
  to/above the Donchian mid, and volume confirms interest.

Exit:
- ATR-based trailing stop that ratchets favorably
- ATR-based take profit
- Max hold bars timeout

Filters:
- ADX regime filter: only enter when ADX > threshold (trending market)
- VWAP directional alignment (institutional baseline vs channel midline)
- Volume confirmation: entry bar volume > vol_mult * rolling average
- Optional RSI structural filter
- Optional time gate for low-edge windows
"""

from __future__ import annotations

from collections import deque
from datetime import datetime, time
from typing import TYPE_CHECKING

from src.core.policies import AddPolicy, EntryPolicy, NoAddPolicy, StopPolicy
from src.core.types import (
    AccountState,
    AddDecision,
    EngineConfig,
    EngineState,
    EntryDecision,
    MarketSignal,
    MarketSnapshot,
    Position,
)
from src.indicators import ADX, RSI, VWAP, Donchian, compose_param_schema
from src.strategies import HoldingPeriod, SignalTimeframe, StopArchitecture, StrategyCategory
from src.strategies._session_utils import in_day_session, in_night_session

if TYPE_CHECKING:
    from src.core.position_engine import PositionEngine

_INDICATOR_PARAMS = compose_param_schema({
    "lookback_period": (Donchian, "period"),
    "adx_len": (ADX, "period"),
    "rsi_len": (RSI, "period"),
})
# Override defaults/bounds to match this strategy's tuning ranges
_INDICATOR_PARAMS["lookback_period"]["default"] = 20
_INDICATOR_PARAMS["lookback_period"]["description"] = "Donchian Channel lookback period (bars on signal TF)."
_INDICATOR_PARAMS["adx_len"]["default"] = 14
_INDICATOR_PARAMS["rsi_len"]["default"] = 5
_INDICATOR_PARAMS["rsi_len"]["max"] = 14

PARAM_SCHEMA: dict[str, dict] = {
    **_INDICATOR_PARAMS,
    "adx_threshold": {
        "type": "float", "default": 20.0, "min": 0.0, "max": 40.0,
        "description": "ADX above this = trending (0=disabled).",
    },
    "rsi_long_thresh": {
        "type": "float", "default": 55.0, "min": 40.0, "max": 100.0,
        "description": "RSI must be below this for long entries (100=disabled).",
    },
    "rsi_short_thresh": {
        "type": "float", "default": 45.0, "min": 0.0, "max": 60.0,
        "description": "RSI must be above this for short entries (0=disabled).",
    },
    "risk_per_trade": {
        "type": "float", "default": 0.0, "min": 0.0, "max": 1_000_000.0,
        "description": "Target risk per trade in NT$. 0=use fixed lots.",
    },
    "vol_mult": {
        "type": "float", "default": 0.0, "min": 0.0, "max": 3.0,
        "description": "Volume confirmation: bar vol > vol_mult * rolling avg (0=disabled).",
    },
    "atr_sl_multi": {
        "type": "float", "default": 1.5, "min": 0.3, "max": 4.0,
        "description": "Stop loss as fraction of daily ATR.",
    },
    "atr_tp_multi": {
        "type": "float", "default": 3.0, "min": 0.5, "max": 6.0,
        "description": "Take profit as fraction of daily ATR.",
    },
    "trail_atr_multi": {
        "type": "float", "default": 2.0, "min": 0.5, "max": 4.0,
        "description": "Trailing stop distance as fraction of daily ATR.",
    },
    "time_gate": {
        "type": "int", "default": 0, "min": 0, "max": 1,
        "description": "Block entries during low-edge windows (1=enabled, 0=disabled).",
    },
    "max_hold_bars": {
        "type": "int", "default": 120, "min": 20, "max": 500,
        "description": "Max bars to hold before time-exit.",
    },
    "min_channel_atr": {
        "type": "float", "default": 0.0, "min": 0.0, "max": 3.0,
        "description": "Min Donchian width as fraction of daily ATR to enter (0=disabled).",
    },
    "bar_agg": {
        "type": "int", "default": 15, "min": 1, "max": 60,
        "description": "Bar aggregation: 1m->Nm.",
    },
    "profit_lock_atr": {
        "type": "float", "default": 0.0, "min": 0.0, "max": 3.0,
        "description": "Tighten trail when floating profit > this * daily ATR (0=disabled).",
    },
    "locked_trail_ratio": {
        "type": "float", "default": 0.5, "min": 0.2, "max": 1.0,
        "description": "Trail multiplier shrinks to trail_atr_multi * this once profit locked.",
    },
    "breakeven_atr": {
        "type": "float", "default": 0.0, "min": 0.0, "max": 2.0,
        "description": "Move stop to breakeven when profit > this * daily ATR (0=disabled).",
    },
    "entry_slack_atr": {
        "type": "float", "default": 0.0, "min": 0.0, "max": 1.0,
        "description": "Relax pullback: allow entry within this * daily ATR beyond midpoint (0=strict).",
    },
}

STRATEGY_META: dict = {
    "category": StrategyCategory.TREND_FOLLOWING,
    "signal_timeframe": SignalTimeframe.FIFTEEN_MIN,
    "holding_period": HoldingPeriod.MEDIUM_TERM,
    "stop_architecture": StopArchitecture.SWING,
    "force_close_mode": "disabled",
    "expected_duration_minutes": (240, 7200),
    "tradeable_sessions": ["day", "night"],
    "bars_per_day": 70,
    "presets": {
        "quick": {"n_bars": 1400, "note": "~1 month"},
        "standard": {"n_bars": 4200, "note": "~3 months"},
        "full_year": {"n_bars": 17640, "note": "~1 year"},
    },
    "description": (
        "Donchian Trend-Strength: medium-term trend-following on 15m bars. "
        "Donchian Channel pullback entries with VWAP direction + volume "
        "confirmation. Designed for multi-hour to multi-day holds."
    ),
}


def _in_low_edge_window(t: time) -> bool:
    if time(10, 30) <= t < time(12, 0):
        return True
    if t >= time(20, 0) or t < time(1, 0):
        return True
    return False


class _Indicators:
    """Thin wrapper composing centralized indicators (Donchian, ADX, RSI, VWAP)."""

    def __init__(
        self,
        lookback_period: int,
        adx_len: int = 14,
        rsi_len: int = 5,
    ) -> None:
        self._dc = Donchian(period=lookback_period)
        self._adx = ADX(period=adx_len)
        self._rsi = RSI(period=rsi_len)
        self._vwap_ind = VWAP()
        self._volumes: deque[float] = deque(maxlen=lookback_period)
        self._last_ts: datetime | None = None
        self.daily_atr: float = 0.0
        self.donchian_upper: float | None = None
        self.donchian_lower: float | None = None
        self.donchian_mid: float | None = None
        self.vwap: float | None = None
        self.rsi: float | None = None
        self.adx: float = 0.0
        self.bar_volume: float = 0.0
        self.avg_volume: float = 0.0
        self.channel_width: float = 0.0

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
        self.daily_atr = daily_atr
        self.bar_volume = volume
        self._volumes.append(volume)
        self.avg_volume = sum(self._volumes) / len(self._volumes) if self._volumes else 0.0
        self._adx.update(price)
        self.adx = self._adx.value or 0.0
        self._rsi.update(price)
        self.rsi = self._rsi.value
        self._vwap_ind.update(price, max(volume, 1.0), timestamp)
        self.vwap = self._vwap_ind.value
        self._dc.update(price)
        self.donchian_upper = self._dc.upper
        self.donchian_lower = self._dc.lower
        self.donchian_mid = self._dc.mid
        self.channel_width = self._dc.width or 0.0


class DonchianTrendStrengthEntry(EntryPolicy):
    def __init__(
        self,
        indicators: _Indicators,
        lots: float = 1.0,
        risk_per_trade: float = 0.0,
        adx_threshold: float = 20.0,
        rsi_long_thresh: float = 55.0,
        rsi_short_thresh: float = 45.0,
        vol_mult: float = 0.0,
        min_channel_atr: float = 0.0,
        atr_sl_multi: float = 1.5,
        atr_tp_multi: float = 3.0,
        time_gate: bool = False,
        entry_slack_atr: float = 0.0,
    ) -> None:
        self._ind = indicators
        self._lots = lots
        self._risk_per_trade = risk_per_trade
        self._adx_threshold = adx_threshold
        self._rsi_long_thresh = rsi_long_thresh
        self._rsi_short_thresh = rsi_short_thresh
        self._vol_mult = vol_mult
        self._min_channel_atr = min_channel_atr
        self._atr_sl_multi = atr_sl_multi
        self._atr_tp_multi = atr_tp_multi
        self._time_gate = time_gate
        self._entry_slack_atr = entry_slack_atr

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
        if not (in_day_session(t) or in_night_session(t)):
            return None
        if self._time_gate and _in_low_edge_window(t):
            return None
        daily_atr = snapshot.atr.get("daily", 0.0)
        self._ind.update(snapshot.price, snapshot.timestamp, snapshot.volume, daily_atr)
        ind = self._ind
        if ind.donchian_mid is None or ind.vwap is None:
            return None
        if daily_atr <= 0:
            return None
        # ADX filter (0 = disabled)
        if self._adx_threshold > 0 and ind.adx < self._adx_threshold:
            return None
        # Channel width regime filter: only trade when channel is wide (trending)
        if self._min_channel_atr > 0 and daily_atr > 0:
            if ind.channel_width < self._min_channel_atr * daily_atr:
                return None
        # Volume confirmation (0 = disabled)
        if self._vol_mult > 0 and ind.avg_volume > 0:
            if ind.bar_volume < self._vol_mult * ind.avg_volume:
                return None
        price = snapshot.price
        sl_pts = daily_atr * self._atr_sl_multi
        # Risk-based sizing: lots = risk_per_trade / (stop_distance × point_value)
        if self._risk_per_trade > 0 and sl_pts > 0:
            lots = max(1.0, round(self._risk_per_trade / (sl_pts * snapshot.point_value)))
        else:
            lots = self._lots
        uptrend = ind.vwap > ind.donchian_mid
        downtrend = ind.vwap < ind.donchian_mid
        rsi_long_ok = ind.rsi is None or self._rsi_long_thresh >= 100 or ind.rsi < self._rsi_long_thresh
        rsi_short_ok = ind.rsi is None or self._rsi_short_thresh <= 0 or ind.rsi > self._rsi_short_thresh
        meta = {
            "atr_tp_multi": self._atr_tp_multi,
            "adx": round(ind.adx, 1),
            "rsi": round(ind.rsi, 1) if ind.rsi is not None else 0,
            "vol_ratio": round(ind.bar_volume / max(ind.avg_volume, 1), 2),
            "ch_width_atr": round(ind.channel_width / max(daily_atr, 1), 2),
        }
        ct = snapshot.contract_specs.contract_type
        slack = self._entry_slack_atr * daily_atr
        if uptrend and price <= ind.donchian_mid + slack and rsi_long_ok:
            return EntryDecision(
                lots=lots,
                contract_type=ct,
                initial_stop=price - sl_pts,
                direction="long",
                metadata=meta,
            )
        if downtrend and price >= ind.donchian_mid - slack and rsi_short_ok:
            return EntryDecision(
                lots=lots,
                contract_type=ct,
                initial_stop=price + sl_pts,
                direction="short",
                metadata=meta,
            )
        return None


class DonchianTrendStrengthAdd(AddPolicy):
    """Anti-martingale pyramid: add into winners at ATR-based profit thresholds.
    Size_k = base_lots * gamma^k. Existing positions move to breakeven on each add.
    """
    def __init__(
        self,
        indicators: _Indicators,
        max_levels: int = 3,
        trigger_atr: float = 1.0,
        gamma: float = 0.5,
        base_lots: float = 1.0,
    ) -> None:
        self._ind = indicators
        self._max_levels = max_levels
        self._trigger_atr = trigger_atr
        self._gamma = gamma
        self._base_lots = base_lots

    def should_add(
        self,
        snapshot: MarketSnapshot,
        signal: MarketSignal | None,
        engine_state: EngineState,
    ) -> AddDecision | None:
        if engine_state.mode == "halted":
            return None
        if engine_state.pyramid_level >= self._max_levels:
            return None
        if not engine_state.positions:
            return None
        daily_atr = snapshot.atr.get("daily", 0.0)
        if daily_atr <= 0:
            return None
        pos = engine_state.positions[0]
        if pos.direction == "long":
            floating_profit = snapshot.price - pos.entry_price
        else:
            floating_profit = pos.entry_price - snapshot.price
        level = engine_state.pyramid_level
        trigger = level * self._trigger_atr * daily_atr
        if floating_profit < trigger:
            return None
        lots = max(self._base_lots * (self._gamma ** level), 0.25)
        return AddDecision(
            lots=lots,
            contract_type=pos.contract_type,
            move_existing_to_breakeven=True,
        )


class DonchianTrendStrengthStop(StopPolicy):
    def __init__(
        self,
        indicators: _Indicators,
        atr_sl_multi: float = 1.5,
        atr_tp_multi: float = 3.0,
        trail_atr_multi: float = 2.0,
        max_hold_bars: int = 120,
        profit_lock_atr: float = 0.0,
        locked_trail_ratio: float = 0.5,
        breakeven_atr: float = 0.0,
    ) -> None:
        self._ind = indicators
        self._atr_sl_multi = atr_sl_multi
        self._atr_tp_multi = atr_tp_multi
        self._trail_atr_multi = trail_atr_multi
        self._max_hold = max_hold_bars
        self._profit_lock_atr = profit_lock_atr
        self._locked_trail_ratio = locked_trail_ratio
        self._breakeven_atr = breakeven_atr
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
        pid = position.position_id
        self._bar_counts[pid] = self._bar_counts.get(pid, 0) + 1
        if self._bar_counts[pid] >= self._max_hold:
            self._bar_counts.pop(pid, None)
            return price
        entry = position.entry_price
        tp_pts = self._locked_tp_pts
        is_long = position.direction == "long"
        floating = (price - entry) if is_long else (entry - price)
        # Adaptive trail: tighten when profit exceeds threshold
        trail_multi = self._trail_atr_multi
        if self._profit_lock_atr > 0 and floating > self._profit_lock_atr * daily_atr:
            trail_multi *= self._locked_trail_ratio
        # Breakeven floor: ratchet stop to entry when profit exceeds threshold
        be_floor = position.stop_level
        if self._breakeven_atr > 0 and floating > self._breakeven_atr * daily_atr:
            be_floor = entry if is_long else entry
        if is_long:
            if price >= entry + tp_pts:
                return price
            trail = price - daily_atr * trail_multi
            return max(trail, be_floor, position.stop_level)
        else:
            if price <= entry - tp_pts:
                return price
            trail = price + daily_atr * trail_multi
            return min(trail, be_floor, position.stop_level)


def create_donchian_trend_strength_engine(
    max_loss: float = 500_000.0,
    lots: float = 1.0,
    risk_per_trade: float = 0.0,
    lookback_period: int = 20,
    adx_len: int = 14,
    adx_threshold: float = 20.0,
    rsi_len: int = 5,
    rsi_long_thresh: float = 55.0,
    rsi_short_thresh: float = 45.0,
    vol_mult: float = 0.0,
    min_channel_atr: float = 0.0,
    atr_sl_multi: float = 1.5,
    atr_tp_multi: float = 3.0,
    trail_atr_multi: float = 2.0,
    time_gate: int = 0,
    max_hold_bars: int = 120,
    bar_agg: int = 15,
    profit_lock_atr: float = 0.0,
    locked_trail_ratio: float = 0.5,
    breakeven_atr: float = 0.0,
    entry_slack_atr: float = 0.0,
    pyramid_risk_level: int = 0,
    **kwargs,
) -> "PositionEngine":
    from src.core.position_engine import PositionEngine
    from src.core.types import pyramid_config_from_risk_level

    indicators = _Indicators(
        lookback_period=lookback_period,
        adx_len=adx_len,
        rsi_len=rsi_len,
    )
    pcfg = pyramid_config_from_risk_level(pyramid_risk_level, max_loss, lots)
    if pcfg is not None:
        add_policy = DonchianTrendStrengthAdd(
            indicators=indicators,
            max_levels=pcfg.max_levels,
            trigger_atr=pcfg.add_trigger_atr[0] if pcfg.add_trigger_atr else 1.0,
            gamma=pcfg.gamma or 0.5,
            base_lots=lots,
        )
    else:
        add_policy = NoAddPolicy()
    config = EngineConfig(max_loss=max_loss, pyramid_risk_level=pyramid_risk_level)
    return PositionEngine(
        entry_policy=DonchianTrendStrengthEntry(
            indicators=indicators,
            lots=lots,
            risk_per_trade=risk_per_trade,
            adx_threshold=adx_threshold,
            rsi_long_thresh=rsi_long_thresh,
            rsi_short_thresh=rsi_short_thresh,
            vol_mult=vol_mult,
            min_channel_atr=min_channel_atr,
            atr_sl_multi=atr_sl_multi,
            atr_tp_multi=atr_tp_multi,
            time_gate=bool(time_gate),
            entry_slack_atr=entry_slack_atr,
        ),
        add_policy=add_policy,
        stop_policy=DonchianTrendStrengthStop(
            indicators=indicators,
            atr_sl_multi=atr_sl_multi,
            atr_tp_multi=atr_tp_multi,
            trail_atr_multi=trail_atr_multi,
            max_hold_bars=max_hold_bars,
            profit_lock_atr=profit_lock_atr,
            locked_trail_ratio=locked_trail_ratio,
            breakeven_atr=breakeven_atr,
        ),
        config=config,
    )
