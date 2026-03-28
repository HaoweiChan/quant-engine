"""Merge multiple strategy backtest results into a combined portfolio equity curve."""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


@dataclass
class PortfolioMergerInput:
    daily_returns: list[float]
    strategy_slug: str
    weight: float = 1.0


@dataclass
class PortfolioMergeResult:
    merged_daily_returns: list[float]
    merged_equity_curve: list[float]
    individual_equity_curves: dict[str, list[float]]
    correlation_matrix: list[list[float]]
    metrics: dict[str, float] = field(default_factory=dict)


class PortfolioMerger:
    """Combine N strategy daily return series into a portfolio equity curve."""

    def __init__(self, initial_capital: float = 2_000_000.0) -> None:
        self._initial_capital = initial_capital

    def merge(self, inputs: list[PortfolioMergerInput]) -> PortfolioMergeResult:
        if not inputs:
            raise ValueError("At least one strategy input required")
        for inp in inputs:
            if len(inp.daily_returns) == 0:
                raise ValueError(f"Empty daily_returns for {inp.strategy_slug}")

        # Normalize weights to sum=1
        total_w = sum(inp.weight for inp in inputs)
        if total_w <= 0:
            raise ValueError("Weights must be positive")
        weights = [inp.weight / total_w for inp in inputs]

        # Align series to the longest length (pad shorter with 0.0)
        max_len = max(len(inp.daily_returns) for inp in inputs)
        aligned: list[np.ndarray] = []
        for inp in inputs:
            arr = np.array(inp.daily_returns, dtype=np.float64)
            if len(arr) < max_len:
                arr = np.concatenate([arr, np.zeros(max_len - len(arr))])
            aligned.append(arr)

        # Weighted merge
        merged = np.zeros(max_len, dtype=np.float64)
        for w, arr in zip(weights, aligned):
            merged += w * arr
        merged_returns = merged.tolist()

        # Build equity curves
        cap = self._initial_capital
        merged_eq = [cap]
        for r in merged_returns:
            cap *= 1.0 + r
            merged_eq.append(cap)

        individual_eq: dict[str, list[float]] = {}
        for inp in inputs:
            eq = [self._initial_capital]
            c = self._initial_capital
            for r in inp.daily_returns:
                c *= 1.0 + r
                eq.append(c)
            individual_eq[inp.strategy_slug] = eq

        # Correlation matrix
        corr = self._compute_correlation(aligned)

        # Portfolio metrics
        metrics = self._compute_metrics(np.array(merged_returns), merged_eq)

        return PortfolioMergeResult(
            merged_daily_returns=merged_returns,
            merged_equity_curve=merged_eq,
            individual_equity_curves=individual_eq,
            correlation_matrix=corr,
            metrics=metrics,
        )

    @staticmethod
    def _compute_correlation(aligned: list[np.ndarray]) -> list[list[float]]:
        n = len(aligned)
        if n < 2:
            return [[1.0]]
        mat = np.stack(aligned)
        # If any series has zero variance, corrcoef returns NaN → replace with 0
        with np.errstate(divide="ignore", invalid="ignore"):
            corr = np.corrcoef(mat)
        corr = np.nan_to_num(corr, nan=0.0)
        return corr.tolist()

    @staticmethod
    def _compute_metrics(
        returns: np.ndarray,
        equity_curve: list[float],
    ) -> dict[str, float]:
        n_days = len(returns)
        if n_days == 0:
            return {
                "total_return": 0.0,
                "sharpe": 0.0,
                "sortino": 0.0,
                "max_drawdown_pct": 0.0,
                "calmar": 0.0,
                "annual_return": 0.0,
                "annual_vol": 0.0,
                "n_days": 0,
            }

        total_return = (equity_curve[-1] - equity_curve[0]) / equity_curve[0]
        ann_factor = 252.0 / n_days
        annual_return = (1.0 + total_return) ** ann_factor - 1.0
        vol = float(np.std(returns, ddof=1)) if n_days > 1 else 0.0
        annual_vol = vol * np.sqrt(252.0)

        # Sharpe (risk-free = 0)
        mean_r = float(np.mean(returns))
        sharpe = (mean_r / vol * np.sqrt(252.0)) if vol > 1e-12 else 0.0

        # Sortino
        downside = returns[returns < 0]
        down_vol = float(np.std(downside, ddof=1)) if len(downside) > 1 else 0.0
        sortino = (mean_r / down_vol * np.sqrt(252.0)) if down_vol > 1e-12 else 0.0

        # Max drawdown
        eq = np.array(equity_curve)
        peak = np.maximum.accumulate(eq)
        dd = (peak - eq) / np.where(peak > 0, peak, 1.0)
        max_dd = float(np.max(dd))

        calmar = annual_return / max_dd if max_dd > 1e-12 else 0.0

        return {
            "total_return": round(total_return, 6),
            "sharpe": round(sharpe, 4),
            "sortino": round(sortino, 4),
            "max_drawdown_pct": round(max_dd, 6),
            "calmar": round(calmar, 4),
            "annual_return": round(annual_return, 6),
            "annual_vol": round(annual_vol, 6),
            "n_days": n_days,
        }
