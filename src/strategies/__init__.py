"""User-editable strategy implementations.

This directory is the sandbox for custom trading strategies, organized
by holding period (short_term / medium_term / swing) and entry logic
(breakout / mean_reversion / trend_following). Each strategy file
implements one or more policy classes that plug into PositionEngine:

- EntryPolicy  — decides when and how to open a new position
- AddPolicy    — decides when to pyramid / add to a winning position
- StopPolicy   — sets initial stop-loss and trailing stop logic

Core system modules (src/core/) are NOT editable from the dashboard.
"""
from enum import Enum
from typing import Protocol, runtime_checkable


class StrategyCategory(str, Enum):
    BREAKOUT = "breakout"
    MEAN_REVERSION = "mean_reversion"
    TREND_FOLLOWING = "trend_following"


class SignalTimeframe(str, Enum):
    """Bar timeframe used for signal generation."""
    ONE_MIN = "1min"
    FIVE_MIN = "5min"
    FIFTEEN_MIN = "15min"
    ONE_HOUR = "1hour"
    DAILY = "daily"


class HoldingPeriod(str, Enum):
    """Expected duration of a position."""
    SHORT_TERM = "short_term"      # < 4 hours
    MEDIUM_TERM = "medium_term"    # 4 hours - 5 days
    SWING = "swing"                # 1-4 weeks


class StopArchitecture(str, Enum):
    """Session-close behavior for the strategy."""
    INTRADAY = "intraday"    # Must flatten before session end
    SWING = "swing"          # Can hold multiple days


def get_quality_thresholds(period: HoldingPeriod) -> dict[str, tuple[float, float]]:
    """Return expected metric ranges (min, max) for a holding period.

    Keys: win_rate, profit_factor, max_drawdown
    """
    _thresholds: dict[HoldingPeriod, dict[str, tuple[float, float]]] = {
        HoldingPeriod.SHORT_TERM: {
            "win_rate": (0.55, 0.65),
            "profit_factor": (1.3, 1.8),
            "max_drawdown": (0.0, 0.05),
        },
        HoldingPeriod.MEDIUM_TERM: {
            "win_rate": (0.45, 0.55),
            "profit_factor": (1.8, 2.5),
            "max_drawdown": (0.05, 0.08),
        },
        HoldingPeriod.SWING: {
            "win_rate": (0.35, 0.45),
            "profit_factor": (2.5, float("inf")),
            "max_drawdown": (0.08, 0.15),
        },
    }
    return _thresholds[period]


@runtime_checkable
class IndicatorProvider(Protocol):
    """Protocol for strategies that expose per-bar indicator values for chart visualization.

    Implement on the strategy's _Indicators class, then attach the instance to the
    PositionEngine as `engine.indicator_provider = indicators` in the factory function.
    The BacktestRunner will detect and collect snapshots automatically.
    """

    def snapshot(self) -> dict[str, float | None]:
        """Return current indicator values keyed by indicator name.

        Called once per bar after on_snapshot() completes. Values are collected
        into parallel lists aligned with the bar series.
        """
        ...

    def indicator_meta(self) -> dict[str, dict]:
        """Return rendering metadata for each indicator key.

        Each key maps to a dict with:
          - "panel": "price" | "sub"  — price overlays go on OHLC chart; "sub" gets a separate panel
          - "color": str              — CSS hex color (e.g. "#FF6B6B")
          - "label": str              — Human-readable name shown in legend
        """
        ...
