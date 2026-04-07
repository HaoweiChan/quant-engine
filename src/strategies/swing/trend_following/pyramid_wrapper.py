"""Pyramid strategy wrapper — keyword-arg factory for the registry.

Bridges the PyramidConfig-based core engine to the standard
create_*_engine(keyword_args) interface used by the registry and facade.

Entry signal: price > SMA(sma_len) → long, price < SMA(sma_len) → short.
Anti-martingale pyramid: add on profit, reduce on stop-loss.
"""
from __future__ import annotations

from collections import deque
from typing import TYPE_CHECKING

import structlog

from src.core.policies import ChandelierStopPolicy, EntryPolicy, PyramidAddPolicy
from src.core.types import (
    AccountState,
    EngineConfig,
    EngineState,
    EntryDecision,
    MarketSignal,
    MarketSnapshot,
    PyramidConfig,
)
from src.strategies import HoldingPeriod, SignalTimeframe, StopArchitecture, StrategyCategory

if TYPE_CHECKING:
    from src.core.position_engine import PositionEngine

logger = structlog.get_logger(__name__)

PARAM_SCHEMA: dict[str, dict] = {
    "sma_len":             {"type": "int",   "default": 20,   "min": 10,  "max": 200,
                            "description": "SMA lookback for trend filter."},
    "max_levels":          {"type": "int",   "default": 1,    "min": 1,   "max": 8,
                            "description": "Maximum pyramid levels (1 = no adds)."},
    "stop_atr_mult":       {"type": "float", "default": 0.5,  "min": 0.5, "max": 4.0,
                            "description": "ATR multiplier for initial stop distance."},
    "trail_atr_mult":      {"type": "float", "default": 3.0,  "min": 1.0, "max": 6.0,
                            "description": "ATR multiplier for chandelier trailing stop."},
    "trail_lookback":      {"type": "int",   "default": 22,   "min": 5,   "max": 60,
                            "description": "Lookback bars for trailing stop high/low."},
    "margin_limit":        {"type": "float", "default": 0.50, "min": 0.1, "max": 1.0,
                            "description": "Margin utilization cap. DO NOT CHANGE."},
    "kelly_fraction":      {"type": "float", "default": 0.25, "min": 0.05, "max": 0.50,
                            "description": "Kelly criterion fraction for position sizing."},
    "entry_conf_threshold": {"type": "float", "default": 0.65, "min": 0.30, "max": 0.90,
                             "description": "Minimum model confidence to enter a trade."},
}

STRATEGY_META: dict = {
    "category": StrategyCategory.TREND_FOLLOWING,
    "signal_timeframe": SignalTimeframe.DAILY,
    "holding_period": HoldingPeriod.SWING,
    "stop_architecture": StopArchitecture.SWING,
    "expected_duration_minutes": (10080, 40320),
    "tradeable_sessions": ["day", "night"],
    "description": "Pyramid trend-following with SMA filter, Kelly sizing and chandelier stops.",
}


_DEFAULT_LOT_SCHEDULE = [[1, 0], [1, 0], [1, 0], [1, 0]]
_DEFAULT_ADD_TRIGGER_ATR = [4.0, 8.0, 12.0]


class SmaPyramidEntryPolicy(EntryPolicy):
    """Enter long when price > SMA, short when price < SMA.

    Reuses PyramidConfig sizing logic (schedule, equity-risk, static cap).
    Uses smoothed ATR (rolling average) instead of raw bar ATR for sizing.
    """

    _ATR_SMOOTH_LEN = 14

    def __init__(self, config: PyramidConfig, sma_len: int = 50) -> None:
        self._config = config
        self._sma_len = sma_len
        self._prices: deque[float] = deque(maxlen=sma_len)
        self._atr_buf: deque[float] = deque(maxlen=self._ATR_SMOOTH_LEN)

    def _sma(self) -> float | None:
        if len(self._prices) < self._sma_len:
            return None
        return sum(self._prices) / self._sma_len

    def _smoothed_atr(self, raw_atr: float) -> float | None:
        self._atr_buf.append(raw_atr)
        if len(self._atr_buf) < self._ATR_SMOOTH_LEN:
            return None
        return sum(self._atr_buf) / len(self._atr_buf)

    def should_enter(
        self,
        snapshot: MarketSnapshot,
        signal: MarketSignal | None,
        engine_state: EngineState,
        account: AccountState | None = None,
    ) -> EntryDecision | None:
        self._prices.append(snapshot.price)

        if engine_state.mode in ("halted", "rule_only"):
            return None

        sma = self._sma()
        if sma is None:
            return None

        # Trend filter: price vs SMA
        if snapshot.price > sma:
            direction = "long"
        elif snapshot.price < sma:
            direction = "short"
        else:
            return None

        raw_atr = snapshot.atr.get("daily", 0.0)
        daily_atr = self._smoothed_atr(raw_atr)
        if daily_atr is None or daily_atr <= 0:
            return None

        stop_distance = self._config.stop_atr_mult * daily_atr
        risk_per_contract = stop_distance * snapshot.point_value
        if risk_per_contract <= 0:
            return None

        # Sizing: 1 lot per entry (anti-martingale starts small, adds on profit)
        lot_spec = self._config.lot_schedule[0]
        schedule_lots = max(float(sum(lot_spec)), snapshot.min_lot)
        static_cap_lots = self._config.max_loss / risk_per_contract
        total_lots = min(schedule_lots, static_cap_lots)

        if total_lots < snapshot.min_lot:
            return None

        stop_level = (
            snapshot.price - stop_distance
            if direction == "long"
            else snapshot.price + stop_distance
        )
        return EntryDecision(
            lots=total_lots,
            contract_type="large",
            initial_stop=stop_level,
            direction=direction,
            metadata={
                "sma": sma,
                "sma_len": self._sma_len,
                "smoothed_atr": daily_atr,
                "price_sma_ratio": snapshot.price / sma,
            },
        )


def create_pyramid_wrapper_engine(
    max_loss: float = 500_000.0,
    max_levels: int = 4,
    sma_len: int = 50,
    stop_atr_mult: float = 1.5,
    trail_atr_mult: float = 3.0,
    trail_lookback: int = 22,
    margin_limit: float = 0.50,
    kelly_fraction: float = 0.25,
    entry_conf_threshold: float = 0.65,
) -> "PositionEngine":
    """Build a PositionEngine with SMA-filtered pyramid strategy."""
    from src.core.position_engine import PositionEngine

    # Auto-adjust array params to match max_levels
    lot_schedule = _DEFAULT_LOT_SCHEDULE[:max_levels]
    while len(lot_schedule) < max_levels:
        lot_schedule.append([1, 0])
    add_trigger_atr = _DEFAULT_ADD_TRIGGER_ATR[: max_levels - 1]
    while len(add_trigger_atr) < max_levels - 1:
        add_trigger_atr.append(add_trigger_atr[-1] + 4.0 if add_trigger_atr else 4.0)

    config = PyramidConfig(
        max_loss=max_loss,
        max_levels=max_levels,
        lot_schedule=lot_schedule,
        add_trigger_atr=add_trigger_atr,
        stop_atr_mult=stop_atr_mult,
        trail_atr_mult=trail_atr_mult,
        trail_lookback=trail_lookback,
        margin_limit=margin_limit,
        kelly_fraction=kelly_fraction,
        entry_conf_threshold=entry_conf_threshold,
    )

    engine_config = EngineConfig(
        max_loss=config.max_loss,
        margin_limit=config.margin_limit,
        trail_lookback=config.trail_lookback,
    )

    return PositionEngine(
        entry_policy=SmaPyramidEntryPolicy(config, sma_len=sma_len),
        add_policy=PyramidAddPolicy(config),
        stop_policy=ChandelierStopPolicy(config),
        config=engine_config,
    )
