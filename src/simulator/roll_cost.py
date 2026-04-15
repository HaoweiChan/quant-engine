"""Roll cost estimator for backtesting multi-month strategies.

For strategies with holding periods that span settlement dates (MEDIUM_TERM,
SWING), the backtester must account for the cost of rolling R1→R2. This module
computes estimated roll costs based on historical spread data or a configurable
fixed spread assumption.

Roll cost = spread_points × point_value × lots × n_rolls_in_period
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta


@dataclass(frozen=True)
class RollCostEstimate:
    """Summary of estimated roll costs over a backtest period."""
    n_rolls: int
    avg_spread_pts: float
    total_roll_cost: float
    roll_dates: list[date]
    cost_per_roll: list[float]


def count_settlements_in_range(start: date, end: date) -> list[date]:
    """Return all settlement dates that fall within [start, end]."""
    from src.data.settlement_calendar import get_settlement_date

    settlements: list[date] = []
    y, m = start.year, start.month
    for _ in range(200):
        sd = get_settlement_date(y, m)
        if sd > end:
            break
        if sd >= start:
            settlements.append(sd)
        m += 1
        if m > 12:
            m = 1
            y += 1
    return settlements


def estimate_roll_costs(
    holding_period: str,
    start_date: date,
    end_date: date,
    lots: float = 1.0,
    point_value: float = 200.0,
    avg_spread_pts: float = 15.0,
) -> RollCostEstimate:
    """Estimate total roll costs for a backtest period.

    Args:
        holding_period: "short_term", "medium_term", or "swing"
        start_date: backtest start
        end_date: backtest end
        lots: average position size in contracts
        point_value: NT$ per index point (TX=200, MTX=50)
        avg_spread_pts: average R1-R2 spread in index points
    """
    if holding_period == "short_term":
        return RollCostEstimate(
            n_rolls=0,
            avg_spread_pts=0.0,
            total_roll_cost=0.0,
            roll_dates=[],
            cost_per_roll=[],
        )
    settlements = count_settlements_in_range(start_date, end_date)
    n_rolls = len(settlements)
    cost_per = abs(avg_spread_pts) * point_value * lots
    return RollCostEstimate(
        n_rolls=n_rolls,
        avg_spread_pts=avg_spread_pts,
        total_roll_cost=cost_per * n_rolls,
        roll_dates=settlements,
        cost_per_roll=[cost_per] * n_rolls,
    )


def inject_roll_costs_into_metrics(
    metrics: dict[str, float],
    holding_period: str,
    start_date: date,
    end_date: date,
    lots: float = 1.0,
    point_value: float = 200.0,
    avg_spread_pts: float = 15.0,
) -> dict[str, float]:
    """Add roll cost fields to a backtest metrics dict."""
    est = estimate_roll_costs(
        holding_period, start_date, end_date,
        lots, point_value, avg_spread_pts,
    )
    metrics["roll_count"] = float(est.n_rolls)
    metrics["roll_avg_spread_pts"] = est.avg_spread_pts
    metrics["roll_total_cost"] = est.total_roll_cost
    if est.total_roll_cost > 0 and metrics.get("net_pnl", 0) != 0:
        metrics["roll_cost_pct_of_pnl"] = (
            est.total_roll_cost / abs(metrics["net_pnl"]) * 100.0
        )
    else:
        metrics["roll_cost_pct_of_pnl"] = 0.0
    return metrics
