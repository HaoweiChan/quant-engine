"""Performance metrics: pure functions operating on equity curves and trade logs."""
from __future__ import annotations

import math
from datetime import datetime

import numpy as np

from src.simulator.types import Fill


def sharpe_ratio(equity_curve: list[float], periods_per_year: float = 252.0) -> float:
    if len(equity_curve) < 2:
        return 0.0
    returns = np.diff(equity_curve) / np.array(equity_curve[:-1])
    if np.std(returns) == 0:
        return 0.0
    return float(np.mean(returns) / np.std(returns) * math.sqrt(periods_per_year))


def sortino_ratio(equity_curve: list[float], periods_per_year: float = 252.0) -> float:
    if len(equity_curve) < 2:
        return 0.0
    returns = np.diff(equity_curve) / np.array(equity_curve[:-1])
    downside = returns[returns < 0]
    if len(downside) == 0 or np.std(downside) == 0:
        return 0.0
    return float(np.mean(returns) / np.std(downside) * math.sqrt(periods_per_year))


def calmar_ratio(equity_curve: list[float], periods_per_year: float = 252.0) -> float:
    if len(equity_curve) < 2:
        return 0.0
    total_return = (equity_curve[-1] - equity_curve[0]) / equity_curve[0]
    n_periods = len(equity_curve) - 1
    annualized_return = total_return * (periods_per_year / n_periods) if n_periods > 0 else 0.0
    mdd = max_drawdown_pct(equity_curve)
    if mdd == 0.0:
        return 0.0
    return annualized_return / mdd


def max_drawdown_abs(equity_curve: list[float]) -> float:
    if len(equity_curve) < 2:
        return 0.0
    peak = equity_curve[0]
    max_dd = 0.0
    for v in equity_curve:
        if v > peak:
            peak = v
        dd = peak - v
        if dd > max_dd:
            max_dd = dd
    return max_dd


def max_drawdown_pct(equity_curve: list[float]) -> float:
    if len(equity_curve) < 2:
        return 0.0
    peak = equity_curve[0]
    max_dd = 0.0
    for v in equity_curve:
        if v > peak:
            peak = v
        if peak > 0:
            dd = (peak - v) / peak
            if dd > max_dd:
                max_dd = dd
    return max_dd


def drawdown_series(equity_curve: list[float]) -> list[float]:
    result: list[float] = []
    peak = equity_curve[0] if equity_curve else 0.0
    for v in equity_curve:
        if v > peak:
            peak = v
        result.append((peak - v) / peak if peak > 0 else 0.0)
    return result


def win_rate(trade_log: list[Fill]) -> float:
    pnls = _trade_pnls(trade_log)
    if not pnls:
        return 0.0
    return sum(1 for p in pnls if p > 0) / len(pnls)


def profit_factor(trade_log: list[Fill]) -> float:
    pnls = _trade_pnls(trade_log)
    gross_profit = sum(p for p in pnls if p > 0)
    gross_loss = abs(sum(p for p in pnls if p < 0))
    if gross_loss == 0:
        return float("inf") if gross_profit > 0 else 0.0
    return gross_profit / gross_loss


def avg_win_loss(trade_log: list[Fill]) -> tuple[float, float]:
    pnls = _trade_pnls(trade_log)
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    avg_w = sum(wins) / len(wins) if wins else 0.0
    avg_l = sum(losses) / len(losses) if losses else 0.0
    return avg_w, avg_l


def trade_count(trade_log: list[Fill]) -> int:
    return len([t for t in trade_log if t.reason == "entry"])


def avg_holding_period(trade_log: list[Fill]) -> float:
    entries: dict[str, datetime] = {}
    durations: list[float] = []
    for fill in trade_log:
        if fill.reason == "entry":
            entries[fill.symbol] = fill.timestamp
        elif fill.symbol in entries and not fill.reason.startswith("add_level"):
            dt = (fill.timestamp - entries[fill.symbol]).total_seconds() / 3600
            durations.append(dt)
            del entries[fill.symbol]
    return sum(durations) / len(durations) if durations else 0.0


def monthly_returns(
    equity_curve: list[float], timestamps: list[datetime]
) -> dict[str, float]:
    result: dict[str, float] = {}
    if len(equity_curve) < 2:
        return result
    for i in range(1, len(equity_curve)):
        key = timestamps[i].strftime("%Y-%m")
        if key not in result:
            prev_idx = i - 1
            for j in range(i - 1, -1, -1):
                if timestamps[j].strftime("%Y-%m") != key:
                    prev_idx = j
                    break
            if equity_curve[prev_idx] > 0:
                result[key] = (equity_curve[i] - equity_curve[prev_idx]) / equity_curve[prev_idx]
    return result


def yearly_returns(
    equity_curve: list[float], timestamps: list[datetime]
) -> dict[str, float]:
    result: dict[str, float] = {}
    if len(equity_curve) < 2:
        return result
    for i in range(1, len(equity_curve)):
        key = timestamps[i].strftime("%Y")
        if key not in result:
            prev_idx = i - 1
            for j in range(i - 1, -1, -1):
                if timestamps[j].strftime("%Y") != key:
                    prev_idx = j
                    break
            if equity_curve[prev_idx] > 0:
                result[key] = (equity_curve[i] - equity_curve[prev_idx]) / equity_curve[prev_idx]
    return result


def composite_fitness(
    equity_curve: list[float],
    trade_log: list[Fill],
    periods_per_year: float = 252.0,
    min_trades: int = 100,
    min_expectancy: float = 0.0,
    holding_penalty_divisor: float = 10.0,
) -> float:
    """Risk-adjusted composite fitness from Seed Strategy Architecture.
    Formula: (calmar * profit_factor) / duration_penalty
    Returns -9999.0 if disqualified by min_trades or min_expectancy gates.
    """
    tc = trade_count(trade_log)
    if tc < min_trades:
        return -9999.0
    avg_w, avg_l = avg_win_loss(trade_log)
    wr = win_rate(trade_log)
    expectancy = (wr * avg_w) + ((1.0 - wr) * avg_l)
    if expectancy < min_expectancy:
        return -9999.0
    cal = calmar_ratio(equity_curve, periods_per_year)
    pf = profit_factor(trade_log)
    ahp = avg_holding_period(trade_log)
    duration_penalty = max(1.0, ahp / holding_penalty_divisor)
    return (cal * pf) / duration_penalty


def compute_all_metrics(
    equity_curve: list[float],
    trade_log: list[Fill],
    periods_per_year: float = 252.0,
) -> dict[str, float]:
    avg_w, avg_l = avg_win_loss(trade_log)
    return {
        "sharpe": sharpe_ratio(equity_curve, periods_per_year),
        "sortino": sortino_ratio(equity_curve, periods_per_year),
        "calmar": calmar_ratio(equity_curve, periods_per_year),
        "max_drawdown_abs": max_drawdown_abs(equity_curve),
        "max_drawdown_pct": max_drawdown_pct(equity_curve),
        "win_rate": win_rate(trade_log),
        "profit_factor": profit_factor(trade_log),
        "avg_win": avg_w,
        "avg_loss": avg_l,
        "trade_count": float(trade_count(trade_log)),
        "avg_holding_period": avg_holding_period(trade_log),
        "composite_fitness": composite_fitness(equity_curve, trade_log, periods_per_year),
    }


def _trade_pnls(trade_log: list[Fill]) -> list[float]:
    pnls: list[float] = []
    # Track ALL entry/add fills per symbol to correctly handle pyramid positions.
    open_fills: dict[str, list[tuple[float, float, str]]] = {}  # symbol -> [(price, lots, side)]
    for fill in trade_log:
        if fill.reason == "entry" or fill.reason.startswith("add_level"):
            open_fills.setdefault(fill.symbol, []).append(
                (fill.fill_price, fill.lots, fill.side)
            )
        elif fill.symbol in open_fills:
            entries = open_fills.pop(fill.symbol)
            total_pnl = 0.0
            for ep, elots, eside in entries:
                if eside == "buy":
                    total_pnl += (fill.fill_price - ep) * elots
                else:
                    total_pnl += (ep - fill.fill_price) * elots
            pnls.append(total_pnl)
    return pnls
