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
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

import structlog

logger = structlog.get_logger(__name__)

_TAIPEI_TZ = timezone(timedelta(hours=8))
_CONFIG_STRATEGIES_DIR = Path(__file__).resolve().parent.parent.parent / "config" / "strategies"


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


class OptimizationLevel(int, Enum):
    """Progressive optimization stage a strategy has achieved."""
    L0_UNOPTIMIZED = 0   # No optimization done
    L1_EXPLORATORY = 1   # Basic viability confirmed (MC on 2+ scenarios)
    L2_VALIDATED = 2     # Walk-forward + sensitivity pass
    L3_PRODUCTION = 3    # Full risk report + slippage stress + paper trade verified


@dataclass(frozen=True)
class StageThresholds:
    """Quality gate thresholds for a (HoldingPeriod, OptimizationLevel) pair."""
    holding_period: HoldingPeriod
    optimization_level: OptimizationLevel
    sharpe_floor: float
    min_trade_count: int
    mdd_max_pct: float | None          # None = no hard gate
    win_rate: tuple[float, float]       # (min, max) as fractions
    profit_factor_floor: float
    sensitivity_cv_max: float | None    # None = not checked at this level
    wf_train_months: int
    wf_validate_months: int
    wf_step_months: int
    n_paths_default: int
    slippage_stress_sharpe: float | None  # None = not checked at this level

    def to_dict(self) -> dict[str, Any]:
        return {
            "holding_period": self.holding_period.value,
            "optimization_level": self.optimization_level.value,
            "optimization_level_name": self.optimization_level.name,
            "sharpe_floor": self.sharpe_floor,
            "min_trade_count": self.min_trade_count,
            "mdd_max_pct": self.mdd_max_pct,
            "win_rate_min": self.win_rate[0],
            "win_rate_max": self.win_rate[1],
            "profit_factor_floor": self.profit_factor_floor,
            "sensitivity_cv_max": self.sensitivity_cv_max,
            "wf_train_months": self.wf_train_months,
            "wf_validate_months": self.wf_validate_months,
            "wf_step_months": self.wf_step_months,
            "n_paths_default": self.n_paths_default,
            "slippage_stress_sharpe": self.slippage_stress_sharpe,
        }


# ---------------------------------------------------------------------------
# Full threshold matrix: 3 holding periods × 3 optimization levels = 9 configs
# ---------------------------------------------------------------------------
_STAGE_THRESHOLDS: dict[tuple[HoldingPeriod, OptimizationLevel], StageThresholds] = {
    # ── SHORT_TERM ──────────────────────────────────────────────
    (HoldingPeriod.SHORT_TERM, OptimizationLevel.L1_EXPLORATORY): StageThresholds(
        holding_period=HoldingPeriod.SHORT_TERM,
        optimization_level=OptimizationLevel.L1_EXPLORATORY,
        sharpe_floor=0.6, min_trade_count=30, mdd_max_pct=None,
        win_rate=(0.40, 0.75), profit_factor_floor=1.0,
        sensitivity_cv_max=None,
        wf_train_months=3, wf_validate_months=1, wf_step_months=1,
        n_paths_default=200, slippage_stress_sharpe=None,
    ),
    (HoldingPeriod.SHORT_TERM, OptimizationLevel.L2_VALIDATED): StageThresholds(
        holding_period=HoldingPeriod.SHORT_TERM,
        optimization_level=OptimizationLevel.L2_VALIDATED,
        sharpe_floor=1.0, min_trade_count=100, mdd_max_pct=10.0,
        win_rate=(0.45, 0.70), profit_factor_floor=1.3,
        sensitivity_cv_max=0.15,
        wf_train_months=3, wf_validate_months=1, wf_step_months=1,
        n_paths_default=200, slippage_stress_sharpe=None,
    ),
    (HoldingPeriod.SHORT_TERM, OptimizationLevel.L3_PRODUCTION): StageThresholds(
        holding_period=HoldingPeriod.SHORT_TERM,
        optimization_level=OptimizationLevel.L3_PRODUCTION,
        sharpe_floor=1.0, min_trade_count=100, mdd_max_pct=10.0,
        win_rate=(0.45, 0.70), profit_factor_floor=1.3,
        sensitivity_cv_max=0.15,
        wf_train_months=3, wf_validate_months=1, wf_step_months=1,
        n_paths_default=200, slippage_stress_sharpe=0.5,
    ),
    # ── MEDIUM_TERM ─────────────────────────────────────────────
    (HoldingPeriod.MEDIUM_TERM, OptimizationLevel.L1_EXPLORATORY): StageThresholds(
        holding_period=HoldingPeriod.MEDIUM_TERM,
        optimization_level=OptimizationLevel.L1_EXPLORATORY,
        sharpe_floor=0.5, min_trade_count=15, mdd_max_pct=None,
        win_rate=(0.35, 0.70), profit_factor_floor=1.0,
        sensitivity_cv_max=None,
        wf_train_months=6, wf_validate_months=2, wf_step_months=1,
        n_paths_default=200, slippage_stress_sharpe=None,
    ),
    (HoldingPeriod.MEDIUM_TERM, OptimizationLevel.L2_VALIDATED): StageThresholds(
        holding_period=HoldingPeriod.MEDIUM_TERM,
        optimization_level=OptimizationLevel.L2_VALIDATED,
        sharpe_floor=0.8, min_trade_count=30, mdd_max_pct=15.0,
        win_rate=(0.40, 0.65), profit_factor_floor=1.2,
        sensitivity_cv_max=0.20,
        wf_train_months=6, wf_validate_months=2, wf_step_months=1,
        n_paths_default=200, slippage_stress_sharpe=None,
    ),
    (HoldingPeriod.MEDIUM_TERM, OptimizationLevel.L3_PRODUCTION): StageThresholds(
        holding_period=HoldingPeriod.MEDIUM_TERM,
        optimization_level=OptimizationLevel.L3_PRODUCTION,
        sharpe_floor=0.8, min_trade_count=30, mdd_max_pct=15.0,
        win_rate=(0.40, 0.65), profit_factor_floor=1.2,
        sensitivity_cv_max=0.20,
        wf_train_months=6, wf_validate_months=2, wf_step_months=1,
        n_paths_default=200, slippage_stress_sharpe=0.5,
    ),
    # ── SWING ───────────────────────────────────────────────────
    (HoldingPeriod.SWING, OptimizationLevel.L1_EXPLORATORY): StageThresholds(
        holding_period=HoldingPeriod.SWING,
        optimization_level=OptimizationLevel.L1_EXPLORATORY,
        sharpe_floor=0.4, min_trade_count=10, mdd_max_pct=None,
        win_rate=(0.25, 0.60), profit_factor_floor=1.0,
        sensitivity_cv_max=None,
        wf_train_months=12, wf_validate_months=3, wf_step_months=2,
        n_paths_default=100, slippage_stress_sharpe=None,
    ),
    (HoldingPeriod.SWING, OptimizationLevel.L2_VALIDATED): StageThresholds(
        holding_period=HoldingPeriod.SWING,
        optimization_level=OptimizationLevel.L2_VALIDATED,
        sharpe_floor=0.7, min_trade_count=20, mdd_max_pct=20.0,
        win_rate=(0.35, 0.55), profit_factor_floor=1.2,
        sensitivity_cv_max=0.25,
        wf_train_months=12, wf_validate_months=3, wf_step_months=2,
        n_paths_default=100, slippage_stress_sharpe=None,
    ),
    (HoldingPeriod.SWING, OptimizationLevel.L3_PRODUCTION): StageThresholds(
        holding_period=HoldingPeriod.SWING,
        optimization_level=OptimizationLevel.L3_PRODUCTION,
        sharpe_floor=0.7, min_trade_count=20, mdd_max_pct=20.0,
        win_rate=(0.35, 0.55), profit_factor_floor=1.2,
        sensitivity_cv_max=0.25,
        wf_train_months=12, wf_validate_months=3, wf_step_months=2,
        n_paths_default=100, slippage_stress_sharpe=0.4,
    ),
}


def get_stage_thresholds(
    period: HoldingPeriod,
    level: OptimizationLevel,
) -> StageThresholds:
    """Return quality gate thresholds for a (holding_period, optimization_level) pair."""
    key = (period, level)
    if key not in _STAGE_THRESHOLDS:
        raise ValueError(
            f"No thresholds defined for ({period.value}, {level.name}). "
            f"L0_UNOPTIMIZED has no gates — use L1+ for threshold queries."
        )
    return _STAGE_THRESHOLDS[key]


def get_quality_thresholds(period: HoldingPeriod) -> dict[str, tuple[float, float]]:
    """Return expected metric ranges (min, max) for a holding period.

    Keys: win_rate, profit_factor, max_drawdown

    .. deprecated:: Use get_stage_thresholds(period, level) for level-aware gates.
       This wrapper returns L2 thresholds for backward compatibility.
    """
    st = get_stage_thresholds(period, OptimizationLevel.L2_VALIDATED)
    return {
        "win_rate": st.win_rate,
        "profit_factor": (st.profit_factor_floor, float("inf")),
        "max_drawdown": (0.0, (st.mdd_max_pct or 20.0) / 100.0),
    }


# ---------------------------------------------------------------------------
# TOML persistence for optimization level
# ---------------------------------------------------------------------------

def _toml_path_for_slug(slug: str) -> Path:
    """Return the TOML config path for a strategy slug.

    Slug examples: 'short_term/breakout/ta_orb' → 'config/strategies/st_ta_orb.toml'
    Also accepts already-flattened names like 'st_ta_orb'.
    """
    # If slug contains '/', flatten using tier prefix
    if "/" in slug:
        parts = slug.split("/")
        tier = parts[0]
        name = parts[-1]
        _tier_prefix = {"short_term": "st", "medium_term": "mt", "swing": "sw"}
        prefix = _tier_prefix.get(tier, tier[:2])
        flat = f"{prefix}_{name}"
    else:
        flat = slug
    return _CONFIG_STRATEGIES_DIR / f"{flat}.toml"


def read_optimization_level(slug: str) -> tuple[OptimizationLevel, dict[str, Any]]:
    """Read current optimization level from config/strategies/<slug>.toml.

    Returns (level, gate_results_dict). If no TOML exists, returns (L0, {}).
    """
    path = _toml_path_for_slug(slug)
    if not path.exists():
        return OptimizationLevel.L0_UNOPTIMIZED, {}

    try:
        import tomllib
    except ModuleNotFoundError:
        import tomli as tomllib  # type: ignore[no-redef]

    with open(path, "rb") as f:
        data = tomllib.load(f)

    opt = data.get("optimization", {})
    level_val = opt.get("level", 0)
    try:
        level = OptimizationLevel(level_val)
    except ValueError:
        level = OptimizationLevel.L0_UNOPTIMIZED

    gate_results = opt.get("gate_results", {})
    return level, gate_results


def write_optimization_level(
    slug: str,
    level: OptimizationLevel,
    gate_results: dict[str, Any],
    holding_period: HoldingPeriod | None = None,
) -> Path:
    """Write optimization level + gate snapshot to config/strategies/<slug>.toml.

    Creates or updates the [optimization] section. Preserves any other sections
    that may exist in the file (e.g., parameter overrides).

    Returns the path written.
    """
    try:
        import tomllib
    except ModuleNotFoundError:
        import tomli as tomllib  # type: ignore[no-redef]

    try:
        import tomli_w
    except ModuleNotFoundError as exc:
        raise ImportError(
            "tomli_w is required to write TOML files. Install with: pip install tomli-w"
        ) from exc

    path = _toml_path_for_slug(slug)
    path.parent.mkdir(parents=True, exist_ok=True)

    # Read existing content to preserve non-optimization sections
    existing: dict[str, Any] = {}
    if path.exists():
        with open(path, "rb") as f:
            existing = tomllib.load(f)

    now = datetime.now(_TAIPEI_TZ).isoformat(timespec="seconds")
    existing["optimization"] = {
        "level": level.value,
        "level_name": level.name,
        "achieved_at": now,
    }
    if holding_period is not None:
        existing["optimization"]["holding_period"] = holding_period.value
    if gate_results:
        existing["optimization"]["gate_results"] = gate_results

    with open(path, "wb") as f:
        tomli_w.dump(existing, f)

    logger.info(
        "optimization_level_written",
        slug=slug,
        level=level.name,
        path=str(path),
    )
    return path


def get_thresholds_for_strategy(
    slug: str,
    level: OptimizationLevel | None = None,
) -> StageThresholds:
    """Resolve quality thresholds from registry metadata and optimization state.

    If level is None, reads current level from TOML and returns thresholds
    for the *next* level (what the strategy needs to pass to advance).

    Falls back to SHORT_TERM / L1 for unclassified strategies.

    Mean-reversion strategies get a widened win_rate_max (0.96) since they
    structurally produce many small wins and fewer large losses.
    """
    from src.strategies.registry import get_info

    # Resolve holding period and category from strategy metadata
    period = HoldingPeriod.SHORT_TERM  # safe default
    category: StrategyCategory | None = None
    try:
        info = get_info(slug)
        if info.holding_period is not None:
            period = info.holding_period
        category = info.category
    except (KeyError, AttributeError):
        logger.debug("thresholds_fallback_short_term", slug=slug)

    # Resolve target level
    if level is not None:
        target_level = level
    else:
        current_level, _ = read_optimization_level(slug)
        next_val = min(current_level.value + 1, OptimizationLevel.L3_PRODUCTION.value)
        target_level = OptimizationLevel(next_val)

    if target_level == OptimizationLevel.L0_UNOPTIMIZED:
        target_level = OptimizationLevel.L1_EXPLORATORY

    base = get_stage_thresholds(period, target_level)

    # Mean-reversion strategies structurally have high win rates (many small
    # wins, few large losses).  Widen the upper bound to avoid false rejections.
    if category == StrategyCategory.MEAN_REVERSION:
        from dataclasses import replace
        base = replace(base, win_rate=(base.win_rate[0], 0.96))

    return base


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
