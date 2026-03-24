"""User-editable strategy implementations.

This directory is the sandbox for custom trading strategies, organized
by timeframe (intraday / daily) and type (breakout / mean_reversion /
trend_following).  Each strategy file implements one or more policy
classes that plug into PositionEngine:

- EntryPolicy  — decides when and how to open a new position
- AddPolicy    — decides when to pyramid / add to a winning position
- StopPolicy   — sets initial stop-loss and trailing stop logic

Core system modules (src/core/) are NOT editable from the dashboard.
"""
from enum import Enum


class StrategyCategory(str, Enum):
    BREAKOUT = "breakout"
    MEAN_REVERSION = "mean_reversion"
    TREND_FOLLOWING = "trend_following"


class StrategyTimeframe(str, Enum):
    INTRADAY = "intraday"
    DAILY = "daily"
    MULTI_DAY = "multi_day"
