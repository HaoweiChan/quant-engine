"""Portfolio-level expanding-window walk-forward validation.

Tests whether a multi-strategy portfolio's weight allocation is stable and
OOS-robust. For each fold the portfolio weights are re-optimized on the
in-sample (IS) slice and applied unchanged to the out-of-sample (OOS) slice.
Aggregate OOS Sharpe, worst-fold MDD, weight drift CV, and correlation
stability are reported.

This operates on PRE-COMPUTED per-strategy daily returns — individual
strategy params stay frozen. It is the L2 acid-test for a portfolio: if
weights drift wildly across folds or OOS Sharpe collapses, the combined
allocation is overfit even though each strategy individually is not.

Reuses ``src.simulator.walk_forward.compute_expanding_folds`` for fold
construction so IS/OOS semantics stay identical to per-strategy walk-forward.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from src.core.portfolio_merger import PortfolioMerger, PortfolioMergerInput
from src.core.portfolio_optimizer import PortfolioOptimizer
from src.simulator.walk_forward import compute_expanding_folds


@dataclass
class PortfolioFoldResult:
    """Single fold of portfolio walk-forward."""

    fold_index: int
    is_start_idx: int
    is_end_idx: int
    oos_start_idx: int
    oos_end_idx: int
    is_weights: dict[str, float]
    is_sharpe: float
    oos_sharpe: float
    oos_mdd_pct: float
    oos_annual_return: float
    oos_annual_vol: float
    correlation_matrix: list[list[float]]


@dataclass
class PortfolioWalkForwardResult:
    """Aggregate portfolio walk-forward result."""

    per_fold: list[PortfolioFoldResult]
    aggregate_oos_sharpe: float
    aggregate_oos_mdd: float
    worst_fold_oos_mdd: float
    weight_drift_cv: float
    correlation_stability: float
    strategy_slugs: list[str]
    objective: str = "max_sharpe"
    n_folds_computed: int = 0
    thresholds_applied: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "per_fold": [
                {
                    "fold_index": f.fold_index,
                    "is_start_idx": f.is_start_idx,
                    "is_end_idx": f.is_end_idx,
                    "oos_start_idx": f.oos_start_idx,
                    "oos_end_idx": f.oos_end_idx,
                    "is_weights": f.is_weights,
                    "is_sharpe": f.is_sharpe,
                    "oos_sharpe": f.oos_sharpe,
                    "oos_mdd_pct": f.oos_mdd_pct,
                    "oos_annual_return": f.oos_annual_return,
                    "oos_annual_vol": f.oos_annual_vol,
                    "correlation_matrix": f.correlation_matrix,
                }
                for f in self.per_fold
            ],
            "aggregate_oos_sharpe": self.aggregate_oos_sharpe,
            "aggregate_oos_mdd": self.aggregate_oos_mdd,
            "worst_fold_oos_mdd": self.worst_fold_oos_mdd,
            "weight_drift_cv": self.weight_drift_cv,
            "correlation_stability": self.correlation_stability,
            "strategy_slugs": self.strategy_slugs,
            "objective": self.objective,
            "n_folds_computed": self.n_folds_computed,
            "thresholds_applied": self.thresholds_applied,
        }


_VALID_OBJECTIVES = frozenset({"max_sharpe", "max_return", "min_drawdown", "risk_parity"})


class PortfolioWalkForward:
    """Expanding-window walk-forward validator for portfolios.

    Args:
        daily_returns: Dict of {strategy_slug: ndarray of per-day returns}.
        initial_capital: Capital base for equity curve reconstruction.
        min_weight: Minimum allocation per strategy in each fold.
        n_folds: Number of expanding-window folds.
        oos_fraction: Fraction of total window used per OOS slice.
        objective: Which allocation objective to optimize IS
            (``max_sharpe`` default; also ``max_return``, ``min_drawdown``,
            ``risk_parity``).
        n_restarts: SLSQP restart count for PortfolioOptimizer IS solve.
    """

    def __init__(
        self,
        daily_returns: dict[str, np.ndarray],
        initial_capital: float = 2_000_000.0,
        min_weight: float = 0.05,
        n_folds: int = 3,
        oos_fraction: float = 0.2,
        objective: str = "max_sharpe",
        n_restarts: int = 10,
    ) -> None:
        if len(daily_returns) < 2:
            raise ValueError("Need at least 2 strategies for portfolio walk-forward")
        if objective not in _VALID_OBJECTIVES:
            raise ValueError(
                f"Unknown objective {objective!r}; must be one of {sorted(_VALID_OBJECTIVES)}",
            )
        if not 0.0 < oos_fraction < 1.0:
            raise ValueError(f"oos_fraction must be in (0, 1); got {oos_fraction}")
        if n_folds < 1:
            raise ValueError(f"n_folds must be >= 1; got {n_folds}")

        self._slugs = list(daily_returns.keys())
        self._initial_capital = initial_capital
        self._min_weight = min_weight
        self._n_folds = n_folds
        self._oos_fraction = oos_fraction
        self._objective = objective
        self._n_restarts = n_restarts

        # Align to longest series (tail-pad short ones with zeros)
        max_len = max(len(r) for r in daily_returns.values())
        self._aligned: dict[str, np.ndarray] = {}
        for slug, r in daily_returns.items():
            arr = np.asarray(r, dtype=np.float64)
            if len(arr) < max_len:
                arr = np.concatenate([arr, np.zeros(max_len - len(arr))])
            self._aligned[slug] = arr
        self._max_len = max_len

    # ------------------------------------------------------------------ helpers
    def _slice_returns(self, indices: list[int]) -> dict[str, np.ndarray]:
        return {slug: arr[indices] for slug, arr in self._aligned.items()}

    def _combined_metrics(
        self,
        weights: dict[str, float],
        returns: dict[str, np.ndarray],
    ) -> dict[str, float]:
        inputs = [
            PortfolioMergerInput(
                daily_returns=list(returns[slug]),
                strategy_slug=slug,
                weight=weights[slug],
            )
            for slug in self._slugs
        ]
        merger = PortfolioMerger(initial_capital=self._initial_capital)
        result = merger.merge(inputs)
        return result.metrics

    def _correlation_matrix(self, returns: dict[str, np.ndarray]) -> list[list[float]]:
        arrays = [returns[s] for s in self._slugs]
        mat = np.stack(arrays)
        with np.errstate(divide="ignore", invalid="ignore"):
            corr = np.corrcoef(mat)
        return np.nan_to_num(corr, nan=0.0).tolist()

    # --------------------------------------------------------------------- run
    def run(self) -> PortfolioWalkForwardResult:
        """Execute the full walk-forward. Returns aggregate result."""
        # compute_expanding_folds expects list of timestamps but operates on
        # indices only — we pass arbitrary placeholders of the right length.
        timestamps = [i for i in range(self._max_len)]
        fold_indices = compute_expanding_folds(
            timestamps=timestamps,  # type: ignore[arg-type]
            n_folds=self._n_folds,
            oos_fraction=self._oos_fraction,
        )

        per_fold: list[PortfolioFoldResult] = []
        for fold_idx, (is_indices, oos_indices) in enumerate(fold_indices):
            if not is_indices or not oos_indices:
                continue
            is_returns = self._slice_returns(is_indices)
            oos_returns = self._slice_returns(oos_indices)

            opt = PortfolioOptimizer(
                daily_returns=is_returns,
                initial_capital=self._initial_capital,
                min_weight=self._min_weight,
            )
            is_result = opt.optimize(n_restarts=self._n_restarts)
            is_allocation = getattr(is_result, self._objective)
            is_weights = dict(is_allocation.weights)

            oos_metrics = self._combined_metrics(is_weights, oos_returns)
            oos_corr = self._correlation_matrix(oos_returns)

            per_fold.append(PortfolioFoldResult(
                fold_index=fold_idx,
                is_start_idx=is_indices[0],
                is_end_idx=is_indices[-1] + 1,
                oos_start_idx=oos_indices[0],
                oos_end_idx=oos_indices[-1] + 1,
                is_weights=is_weights,
                is_sharpe=float(is_allocation.sharpe),
                oos_sharpe=float(oos_metrics.get("sharpe", 0.0)),
                oos_mdd_pct=float(oos_metrics.get("max_drawdown_pct", 0.0)),
                oos_annual_return=float(oos_metrics.get("annual_return", 0.0)),
                oos_annual_vol=float(oos_metrics.get("annual_vol", 0.0)),
                correlation_matrix=oos_corr,
            ))

        return self._aggregate(per_fold)

    # --------------------------------------------------------------- aggregate
    def _aggregate(
        self,
        per_fold: list[PortfolioFoldResult],
    ) -> PortfolioWalkForwardResult:
        # Record the portfolio L2 gate thresholds in every result so the
        # artifact is self-describing for downstream audit.
        from src.simulator.portfolio_promotion import (
            GATE_THRESHOLDS,
            PortfolioOptimizationLevel,
        )
        l2_thresholds = dict(GATE_THRESHOLDS.get(
            PortfolioOptimizationLevel.L2_VALIDATED, {},
        ))

        if not per_fold:
            return PortfolioWalkForwardResult(
                per_fold=[],
                aggregate_oos_sharpe=0.0,
                aggregate_oos_mdd=0.0,
                worst_fold_oos_mdd=0.0,
                weight_drift_cv=float("inf"),
                correlation_stability=0.0,
                strategy_slugs=self._slugs,
                objective=self._objective,
                n_folds_computed=0,
                thresholds_applied=l2_thresholds,
            )

        oos_sharpes = np.array([f.oos_sharpe for f in per_fold])
        oos_mdds = np.array([f.oos_mdd_pct for f in per_fold])

        aggregate_oos_sharpe = float(np.mean(oos_sharpes))
        aggregate_oos_mdd = float(np.mean(oos_mdds))
        worst_fold_oos_mdd = float(np.max(oos_mdds))

        weight_drift_cv = self._weight_drift_cv(per_fold)
        correlation_stability = self._correlation_stability(per_fold)

        return PortfolioWalkForwardResult(
            per_fold=per_fold,
            aggregate_oos_sharpe=aggregate_oos_sharpe,
            aggregate_oos_mdd=aggregate_oos_mdd,
            worst_fold_oos_mdd=worst_fold_oos_mdd,
            weight_drift_cv=weight_drift_cv,
            correlation_stability=correlation_stability,
            strategy_slugs=self._slugs,
            objective=self._objective,
            n_folds_computed=len(per_fold),
            thresholds_applied=l2_thresholds,
        )

    def _weight_drift_cv(self, per_fold: list[PortfolioFoldResult]) -> float:
        """Mean CV across strategies of their per-fold weight series."""
        if len(per_fold) < 2:
            return 0.0
        matrix = np.array([
            [f.is_weights[slug] for slug in self._slugs] for f in per_fold
        ])  # shape (n_folds, n_strategies)
        mean = matrix.mean(axis=0)
        std = matrix.std(axis=0, ddof=1)
        per_strategy_cv = np.where(mean > 1e-9, std / mean, 0.0)
        return float(np.mean(per_strategy_cv))

    def _correlation_stability(
        self,
        per_fold: list[PortfolioFoldResult],
    ) -> float:
        """Allocation-weighted correlation stability across folds.

        For each strategy pair (i, j) compute the fold-to-fold spread
        of its pairwise correlation ρ_ij, then aggregate by weighting
        each pair with its allocation product w_i × w_j (averaged
        across folds). This reflects the first-order sensitivity of
        portfolio variance to a correlation drift:

            Var(portfolio) = Σ_ij w_i w_j σ_i σ_j ρ_ij

        so a pair's correlation only matters in proportion to its joint
        weight in the portfolio. Pairs with small joint weight (e.g.
        two strategies each at 5% min_weight) contribute negligibly
        even if their correlation is noisy, while a 57%-weighted
        dominant strategy's pairs drive the metric.

        Returns a value in [0, 1] where 1.0 = correlations identical
        across folds (under the current allocation) and 0.0 =
        allocation-weighted drift is at its theoretical maximum.

        Degenerate cases:
          - Fewer than 2 folds: 1.0 (nothing to compare).
          - Zero total pair weight: falls back to unweighted max-spread
            (legacy behaviour; happens when allocations degenerate).
        """
        if len(per_fold) < 2:
            return 1.0
        n = len(self._slugs)
        if n < 2:
            return 1.0

        corrs = np.array([f.correlation_matrix for f in per_fold])  # (F, n, n)
        # Per-pair across-fold spread (max - min)
        pair_spread = corrs.max(axis=0) - corrs.min(axis=0)  # (n, n)

        # Across-fold average weight per strategy
        mean_weights = np.array([
            float(np.mean([f.is_weights[slug] for f in per_fold]))
            for slug in self._slugs
        ])  # (n,)
        # Pair joint weight w_i * w_j, symmetric
        pair_weight = np.outer(mean_weights, mean_weights)  # (n, n)

        # Mask off the diagonal — self-correlation is always 1.0 and
        # drift is meaningless (PortfolioMerger guarantees it).
        mask = ~np.eye(n, dtype=bool)
        weights_off = pair_weight[mask]
        spreads_off = pair_spread[mask]

        total_weight = float(weights_off.sum())
        if total_weight <= 1e-12:
            # Fallback to unweighted max if weights degenerate
            max_spread = float(spreads_off.max()) if spreads_off.size > 0 else 0.0
            return max(0.0, 1.0 - max_spread)

        weighted_drift = float((spreads_off * weights_off).sum() / total_weight)
        return max(0.0, 1.0 - weighted_drift)
