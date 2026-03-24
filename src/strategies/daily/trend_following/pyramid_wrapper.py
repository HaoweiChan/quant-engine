"""Pyramid strategy wrapper — exposes PARAM_SCHEMA for the registry.

The actual engine factory lives in src.core.position_engine; this module
re-exports it alongside the parameter metadata so the strategy registry
can discover it uniformly.
"""
from __future__ import annotations

from src.core.position_engine import create_pyramid_engine  # noqa: F401
from src.strategies import StrategyCategory, StrategyTimeframe

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
