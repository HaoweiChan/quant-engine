"""Portfolio weight optimizer using scipy constrained optimization.

Finds optimal capital allocation across N strategies by optimizing
different objectives (max Sharpe, max return, min drawdown, risk parity)
subject to weight constraints (sum-to-1, min allocation per strategy).

Supports Pareto front generation across Sharpe vs Return vs Drawdown.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy import optimize

from src.core.portfolio_merger import PortfolioMerger, PortfolioMergerInput


@dataclass
class OptimalAllocation:
    """Single optimal weight vector with its metrics."""
    objective: str
    weights: dict[str, float]
    sharpe: float
    total_return: float
    annual_return: float
    max_drawdown_pct: float
    sortino: float
    calmar: float
    annual_vol: float


@dataclass
class ParetoPoint:
    """A point on the Pareto frontier."""
    weights: dict[str, float]
    sharpe: float
    total_return: float
    max_drawdown_pct: float
    annual_return: float
    annual_vol: float


@dataclass
class PortfolioOptimizationResult:
    """Full result from portfolio optimization."""
    strategy_slugs: list[str]
    max_sharpe: OptimalAllocation
    max_return: OptimalAllocation
    min_drawdown: OptimalAllocation
    risk_parity: OptimalAllocation
    equal_weight: OptimalAllocation
    pareto_front: list[ParetoPoint]
    correlation_matrix: list[list[float]]
    individual_metrics: dict[str, dict[str, float]]
    n_days: int


class PortfolioOptimizer:
    """Find optimal weight allocations across multiple strategies.

    Uses scipy.optimize.minimize with SLSQP for constrained optimization.
    Constraints: weights sum to 1.0, each weight >= min_weight.
    """

    def __init__(
        self,
        daily_returns: dict[str, np.ndarray],
        initial_capital: float = 2_000_000.0,
        min_weight: float = 0.10,
    ) -> None:
        if len(daily_returns) < 2:
            raise ValueError("Need at least 2 strategies for portfolio optimization")
        self._slugs = list(daily_returns.keys())
        self._n = len(self._slugs)
        self._min_weight = min_weight
        self._initial_capital = initial_capital
        self._merger = PortfolioMerger(initial_capital=initial_capital)
        # Align all return series to the same length
        max_len = max(len(r) for r in daily_returns.values())
        self._aligned: dict[str, np.ndarray] = {}
        for slug, r in daily_returns.items():
            arr = np.asarray(r, dtype=np.float64)
            if len(arr) < max_len:
                arr = np.concatenate([arr, np.zeros(max_len - len(arr))])
            self._aligned[slug] = arr
        self._max_len = max_len
        self._returns_matrix = np.stack([self._aligned[s] for s in self._slugs])

    def _portfolio_metrics(self, weights: np.ndarray) -> dict[str, float]:
        """Compute portfolio metrics for a given weight vector."""
        merged = weights @ self._returns_matrix
        cap = self._initial_capital
        eq = [cap]
        for r in merged:
            cap *= 1.0 + r
            eq.append(cap)
        return PortfolioMerger._compute_metrics(merged, eq)

    def _neg_sharpe(self, weights: np.ndarray) -> float:
        """Negative Sharpe (for minimization)."""
        m = self._portfolio_metrics(weights)
        return -m["sharpe"]

    def _neg_return(self, weights: np.ndarray) -> float:
        """Negative total return (for minimization)."""
        m = self._portfolio_metrics(weights)
        return -m["total_return"]

    def _max_drawdown(self, weights: np.ndarray) -> float:
        """Max drawdown (for minimization)."""
        m = self._portfolio_metrics(weights)
        return m["max_drawdown_pct"]

    def _risk_parity_objective(self, weights: np.ndarray) -> float:
        """Risk parity: minimize variance of individual risk contributions.

        Each strategy's marginal risk contribution should be equal.
        """
        w = weights
        merged = w @ self._returns_matrix
        port_vol = float(np.std(merged, ddof=1))
        if port_vol < 1e-12:
            return 0.0
        # Marginal risk contribution: w_i * cov(r_i, r_port) / port_vol
        mrc = np.zeros(self._n)
        for i in range(self._n):
            cov_i = float(np.cov(self._returns_matrix[i], merged)[0, 1])
            mrc[i] = w[i] * cov_i / port_vol
        # Target: equal risk contribution = port_vol / n
        target = port_vol / self._n
        return float(np.sum((mrc - target) ** 2))

    def _constraints(self) -> list[dict]:
        return [{"type": "eq", "fun": lambda w: np.sum(w) - 1.0}]

    def _bounds(self) -> list[tuple[float, float]]:
        return [(self._min_weight, 1.0 - self._min_weight * (self._n - 1))] * self._n

    def _optimize(
        self,
        objective_fn,
        objective_name: str,
        n_restarts: int = 20,
    ) -> OptimalAllocation:
        """Run optimization with multiple random restarts."""
        bounds = self._bounds()
        constraints = self._constraints()
        best_val = float("inf")
        best_weights: np.ndarray | None = None
        rng = np.random.default_rng(42)
        for _ in range(n_restarts):
            # Random initial weights respecting min_weight
            raw = rng.dirichlet(np.ones(self._n))
            x0 = np.clip(raw, self._min_weight, None)
            x0 /= x0.sum()
            res = optimize.minimize(
                objective_fn,
                x0,
                method="SLSQP",
                bounds=bounds,
                constraints=constraints,
                options={"maxiter": 500, "ftol": 1e-10},
            )
            if res.success and res.fun < best_val:
                best_val = res.fun
                best_weights = res.x
        if best_weights is None:
            # Fallback to equal weights
            best_weights = np.full(self._n, 1.0 / self._n)
        # Snap to 1% precision and renormalize
        best_weights = np.round(best_weights, 2)
        best_weights /= best_weights.sum()
        metrics = self._portfolio_metrics(best_weights)
        return OptimalAllocation(
            objective=objective_name,
            weights={s: round(float(w), 4) for s, w in zip(self._slugs, best_weights)},
            sharpe=metrics["sharpe"],
            total_return=metrics["total_return"],
            annual_return=metrics["annual_return"],
            max_drawdown_pct=metrics["max_drawdown_pct"],
            sortino=metrics["sortino"],
            calmar=metrics["calmar"],
            annual_vol=metrics["annual_vol"],
        )

    def _equal_weight(self) -> OptimalAllocation:
        w = np.full(self._n, 1.0 / self._n)
        metrics = self._portfolio_metrics(w)
        return OptimalAllocation(
            objective="equal_weight",
            weights={s: round(1.0 / self._n, 4) for s in self._slugs},
            sharpe=metrics["sharpe"],
            total_return=metrics["total_return"],
            annual_return=metrics["annual_return"],
            max_drawdown_pct=metrics["max_drawdown_pct"],
            sortino=metrics["sortino"],
            calmar=metrics["calmar"],
            annual_vol=metrics["annual_vol"],
        )

    def _build_pareto_front(self, step: float = 0.05) -> list[ParetoPoint]:
        """Generate Pareto front via weight grid sampling.

        Enumerates weight combinations at `step` increments, computes metrics
        for each, then filters to non-dominated points on (Sharpe, -Drawdown).
        """
        from itertools import product
        grid_vals = np.arange(self._min_weight, 1.0 - self._min_weight * (self._n - 1) + step / 2, step)
        candidates: list[ParetoPoint] = []
        for combo in product(grid_vals, repeat=self._n):
            w = np.array(combo)
            if abs(w.sum() - 1.0) > step / 2:
                continue
            if np.any(w < self._min_weight - 1e-9):
                continue
            w = w / w.sum()
            m = self._portfolio_metrics(w)
            candidates.append(ParetoPoint(
                weights={s: round(float(v), 4) for s, v in zip(self._slugs, w)},
                sharpe=m["sharpe"],
                total_return=m["total_return"],
                max_drawdown_pct=m["max_drawdown_pct"],
                annual_return=m["annual_return"],
                annual_vol=m["annual_vol"],
            ))
        if not candidates:
            return []
        # Non-dominated filter: a point is dominated if another has both
        # higher Sharpe AND lower drawdown
        pareto: list[ParetoPoint] = []
        for pt in candidates:
            dominated = False
            for other in candidates:
                if other is pt:
                    continue
                if other.sharpe >= pt.sharpe and other.max_drawdown_pct <= pt.max_drawdown_pct:
                    if other.sharpe > pt.sharpe or other.max_drawdown_pct < pt.max_drawdown_pct:
                        dominated = True
                        break
            if not dominated:
                pareto.append(pt)
        pareto.sort(key=lambda p: p.sharpe, reverse=True)
        return pareto

    def optimize(self, n_restarts: int = 20) -> PortfolioOptimizationResult:
        """Run all optimization objectives and return full results."""
        max_sharpe = self._optimize(self._neg_sharpe, "max_sharpe", n_restarts)
        max_ret = self._optimize(self._neg_return, "max_return", n_restarts)
        min_dd = self._optimize(self._max_drawdown, "min_drawdown", n_restarts)
        risk_par = self._optimize(self._risk_parity_objective, "risk_parity", n_restarts)
        equal = self._equal_weight()
        pareto = self._build_pareto_front()
        # Correlation
        mat = np.stack([self._aligned[s] for s in self._slugs])
        with np.errstate(divide="ignore", invalid="ignore"):
            corr = np.corrcoef(mat)
        corr = np.nan_to_num(corr, nan=0.0).tolist()
        # Individual strategy metrics
        ind_metrics: dict[str, dict[str, float]] = {}
        for i, slug in enumerate(self._slugs):
            w = np.zeros(self._n)
            w[i] = 1.0
            ind_metrics[slug] = self._portfolio_metrics(w)
        return PortfolioOptimizationResult(
            strategy_slugs=self._slugs,
            max_sharpe=max_sharpe,
            max_return=max_ret,
            min_drawdown=min_dd,
            risk_parity=risk_par,
            equal_weight=equal,
            pareto_front=pareto,
            correlation_matrix=corr,
            individual_metrics=ind_metrics,
            n_days=self._max_len,
        )
