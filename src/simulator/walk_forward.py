"""Expanding-window walk-forward validation for strategy robustness testing."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import numpy as np


@dataclass
class WalkForwardConfig:
    """Configuration for walk-forward validation."""

    n_folds: int = 3
    oos_fraction: float = 0.2
    optimization_metric: str = "sharpe"
    max_sweep_combinations: int = 50
    session: str = "all"  # "all" | "day" | "night"


@dataclass
class FoldResult:
    """Result for a single walk-forward fold."""

    fold_index: int
    is_start: datetime
    is_end: datetime
    oos_start: datetime
    oos_end: datetime
    is_best_params: dict[str, float]
    is_sharpe: float
    oos_sharpe: float
    oos_mdd_pct: float
    oos_win_rate: float
    oos_n_trades: int
    oos_profit_factor: float
    overfit_ratio: float


@dataclass
class WalkForwardResult:
    """Aggregate walk-forward validation result."""

    folds: list[FoldResult]
    aggregate_oos_sharpe: float
    mean_overfit_ratio: float
    overfit_flag: str  # "none" | "mild" | "severe"
    passed: bool
    failure_reasons: list[str] = field(default_factory=list)


def compute_expanding_folds(
    timestamps: list[datetime],
    n_folds: int = 3,
    oos_fraction: float = 0.2,
) -> list[tuple[list[int], list[int]]]:
    """Compute expanding-window fold splits.

    Returns a list of (is_indices, oos_indices) tuples for each fold.
    Each IS window starts at 0 and expands; OOS windows are consecutive.
    """
    n = len(timestamps)
    oos_size = int(n * oos_fraction)
    if oos_size < 1:
        oos_size = 1

    folds = []
    for fold_idx in range(n_folds):
        # OOS window: from (n - (n_folds - fold_idx) * oos_size) to (n - (n_folds - fold_idx - 1) * oos_size)
        oos_end_offset = (n_folds - fold_idx - 1) * oos_size
        oos_start_idx = n - oos_end_offset - oos_size
        oos_end_idx = n - oos_end_offset

        if oos_start_idx < 1:
            continue

        is_indices = list(range(0, oos_start_idx))
        oos_indices = list(range(oos_start_idx, oos_end_idx))
        folds.append((is_indices, oos_indices))

    return folds


def filter_bars_by_session(
    bars: list[dict[str, Any]],
    timestamps: list[datetime],
    session: str,
) -> tuple[list[dict[str, Any]], list[datetime], list[int]]:
    """Filter bars to only include a specific TAIFEX session.

    Args:
        bars: List of bar dicts.
        timestamps: Corresponding timestamps.
        session: "all", "day" (08:45-13:45), or "night" (15:00-05:00+1d).

    Returns:
        Filtered bars, timestamps, and original indices.
    """
    if session == "all":
        return bars, timestamps, list(range(len(bars)))

    filtered_bars = []
    filtered_ts = []
    original_indices = []
    for i, (bar, ts) in enumerate(zip(bars, timestamps)):
        hour = ts.hour
        minute = ts.minute
        time_val = hour * 60 + minute

        if session == "day":
            # 08:45 - 13:45
            if 8 * 60 + 45 <= time_val < 13 * 60 + 45:
                filtered_bars.append(bar)
                filtered_ts.append(ts)
                original_indices.append(i)
        elif session == "night":
            # 15:00 - 05:00 next day
            if time_val >= 15 * 60 or time_val < 5 * 60:
                filtered_bars.append(bar)
                filtered_ts.append(ts)
                original_indices.append(i)

    return filtered_bars, filtered_ts, original_indices


def _compute_metrics_from_equity(
    equity_curve: list[float],
    trade_log: list,
    periods_per_year: float = 252.0,
) -> dict[str, float]:
    """Extract key metrics from equity curve and trade log."""
    if len(equity_curve) < 2:
        return {
            "sharpe": 0.0,
            "max_drawdown_pct": 0.0,
            "win_rate": 0.0,
            "trade_count": 0,
            "profit_factor": 0.0,
        }

    eq = np.array(equity_curve)
    returns = np.diff(eq) / eq[:-1]
    returns = returns[np.isfinite(returns)]

    # Sharpe
    if len(returns) > 0 and np.std(returns) > 0:
        sharpe = float(np.mean(returns) / np.std(returns) * np.sqrt(periods_per_year))
    else:
        sharpe = 0.0

    # MDD
    running_max = np.maximum.accumulate(eq)
    drawdowns = (running_max - eq) / running_max
    mdd = float(np.max(drawdowns)) * 100.0 if len(drawdowns) > 0 else 0.0

    # Win rate and profit factor from trade pairs
    n_trades = len(trade_log) // 2
    wins = 0
    gross_profit = 0.0
    gross_loss = 0.0
    for i in range(0, len(trade_log) - 1, 2):
        entry = trade_log[i]
        exit_ = trade_log[i + 1]
        if hasattr(entry, "fill_price") and hasattr(exit_, "fill_price"):
            pnl = exit_.fill_price - entry.fill_price
            if hasattr(entry, "side") and entry.side == "sell":
                pnl = -pnl
            if pnl > 0:
                wins += 1
                gross_profit += pnl
            else:
                gross_loss += abs(pnl)

    win_rate = (wins / n_trades * 100.0) if n_trades > 0 else 0.0
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else float("inf")

    return {
        "sharpe": sharpe,
        "max_drawdown_pct": mdd,
        "win_rate": win_rate,
        "trade_count": n_trades,
        "profit_factor": profit_factor,
    }


def classify_overfit(mean_ratio: float) -> str:
    """Classify overfit level from mean OOS/IS Sharpe ratio."""
    if mean_ratio >= 0.7:
        return "none"
    if mean_ratio >= 0.3:
        return "mild"
    return "severe"


def evaluate_quality_gates(
    folds: list[FoldResult],
    aggregate_oos_sharpe: float,
    overfit_flag: str,
) -> tuple[bool, list[str]]:
    """Apply quality gate thresholds from the sign-off checklist.

    Returns:
        (passed, failure_reasons)
    """
    reasons = []

    if aggregate_oos_sharpe < 1.0:
        reasons.append(f"Aggregate OOS Sharpe {aggregate_oos_sharpe:.2f} < 1.0")

    if overfit_flag == "severe":
        reasons.append("Severe overfit detected (OOS/IS ratio < 0.3)")

    for f in folds:
        if f.oos_mdd_pct > 20.0:
            reasons.append(f"Fold {f.fold_index}: MDD {f.oos_mdd_pct:.1f}% > 20%")
        if not (35.0 <= f.oos_win_rate <= 70.0):
            reasons.append(f"Fold {f.fold_index}: Win rate {f.oos_win_rate:.1f}% outside 35-70%")
        if f.oos_n_trades < 30:
            reasons.append(f"Fold {f.fold_index}: {f.oos_n_trades} trades < 30")
        if f.oos_profit_factor < 1.2:
            reasons.append(f"Fold {f.fold_index}: Profit factor {f.oos_profit_factor:.2f} < 1.2")

    passed = len(reasons) == 0
    return passed, reasons


def build_walk_forward_result(folds: list[FoldResult]) -> WalkForwardResult:
    """Build aggregate WalkForwardResult from fold results."""
    if not folds:
        return WalkForwardResult(
            folds=[],
            aggregate_oos_sharpe=0.0,
            mean_overfit_ratio=0.0,
            overfit_flag="severe",
            passed=False,
            failure_reasons=["No folds computed"],
        )

    oos_sharpes = [f.oos_sharpe for f in folds]
    aggregate_oos_sharpe = float(np.mean(oos_sharpes))

    overfit_ratios = [f.overfit_ratio for f in folds]
    mean_overfit_ratio = float(np.mean(overfit_ratios))
    overfit_flag = classify_overfit(mean_overfit_ratio)

    passed, failure_reasons = evaluate_quality_gates(folds, aggregate_oos_sharpe, overfit_flag)

    return WalkForwardResult(
        folds=folds,
        aggregate_oos_sharpe=aggregate_oos_sharpe,
        mean_overfit_ratio=mean_overfit_ratio,
        overfit_flag=overfit_flag,
        passed=passed,
        failure_reasons=failure_reasons,
    )


def compute_overfit_ratio(is_sharpe: float, oos_sharpe: float) -> float:
    """Compute OOS/IS Sharpe ratio, handling edge cases."""
    if oos_sharpe <= 0:
        return 0.0
    if is_sharpe <= 0:
        return 0.0
    return oos_sharpe / is_sharpe
