"""Pyramid strategy wrapper — keyword-arg factory for the registry.

Bridges the PyramidConfig-based core engine to the standard
create_*_engine(keyword_args) interface used by the registry and facade.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from src.core.types import PyramidConfig
from src.strategies import StrategyCategory, StrategyTimeframe

if TYPE_CHECKING:
    from src.core.position_engine import PositionEngine

PARAM_SCHEMA: dict[str, dict] = {
    "max_levels":          {"type": "int",   "default": 4,    "min": 1,   "max": 8,
                            "description": "Maximum pyramid levels."},
    "stop_atr_mult":       {"type": "float", "default": 1.5,  "min": 0.5, "max": 4.0,
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
    "timeframe": StrategyTimeframe.DAILY,
    "description": "Pyramid trend-following with Kelly sizing and chandelier stops.",
}


_DEFAULT_LOT_SCHEDULE = [[3, 4], [2, 0], [1, 4], [1, 4]]
_DEFAULT_ADD_TRIGGER_ATR = [4.0, 8.0, 12.0]


def create_pyramid_wrapper_engine(
    max_loss: float = 500_000.0,
    max_levels: int = 4,
    stop_atr_mult: float = 1.5,
    trail_atr_mult: float = 3.0,
    trail_lookback: int = 22,
    margin_limit: float = 0.50,
    kelly_fraction: float = 0.25,
    entry_conf_threshold: float = 0.65,
) -> "PositionEngine":
    """Build a PositionEngine with pyramid strategy via keyword args."""
    from src.core.position_engine import create_pyramid_engine

    # Auto-adjust array params to match max_levels so callers
    # (grid search, optimizer) can freely sweep max_levels without
    # providing explicit lot_schedule / add_trigger_atr.
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
    return create_pyramid_engine(config)
