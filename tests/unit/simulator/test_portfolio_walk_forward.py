"""Unit tests for PortfolioWalkForward."""
from __future__ import annotations

import numpy as np
import pytest

from src.simulator.portfolio_walk_forward import (
    PortfolioFoldResult,
    PortfolioWalkForward,
    PortfolioWalkForwardResult,
)


def _make_returns(seed: int, n: int, mu: float = 0.001, sigma: float = 0.01) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return rng.normal(mu, sigma, size=n).astype(np.float64)


def _two_strategies(n: int = 300) -> dict[str, np.ndarray]:
    return {
        "strat_a": _make_returns(seed=1, n=n, mu=0.0008, sigma=0.012),
        "strat_b": _make_returns(seed=2, n=n, mu=0.0005, sigma=0.008),
    }


class TestConstruction:
    def test_requires_at_least_two_strategies(self) -> None:
        with pytest.raises(ValueError, match="at least 2 strategies"):
            PortfolioWalkForward({"only": _make_returns(1, 100)})

    def test_rejects_unknown_objective(self) -> None:
        with pytest.raises(ValueError, match="Unknown objective"):
            PortfolioWalkForward(_two_strategies(), objective="yolo")

    def test_rejects_bad_oos_fraction(self) -> None:
        with pytest.raises(ValueError, match="oos_fraction"):
            PortfolioWalkForward(_two_strategies(), oos_fraction=1.5)
        with pytest.raises(ValueError, match="oos_fraction"):
            PortfolioWalkForward(_two_strategies(), oos_fraction=0.0)

    def test_rejects_zero_folds(self) -> None:
        with pytest.raises(ValueError, match="n_folds"):
            PortfolioWalkForward(_two_strategies(), n_folds=0)

    def test_tail_pads_shorter_series(self) -> None:
        returns = {
            "long": np.full(100, 0.001),
            "short": np.full(50, 0.001),
        }
        wf = PortfolioWalkForward(returns, n_folds=2)
        # Aligned buffer should be the max length
        assert wf._max_len == 100
        assert len(wf._aligned["short"]) == 100
        # Tail is zero-padded
        assert np.all(wf._aligned["short"][50:] == 0.0)


class TestRun:
    def test_run_produces_n_folds(self) -> None:
        wf = PortfolioWalkForward(
            _two_strategies(n=300),
            n_folds=3,
            oos_fraction=0.2,
            n_restarts=3,
        )
        result = wf.run()
        assert isinstance(result, PortfolioWalkForwardResult)
        assert result.n_folds_computed == 3
        assert len(result.per_fold) == 3
        for fold in result.per_fold:
            assert isinstance(fold, PortfolioFoldResult)
            # Weights sum to ~1
            assert abs(sum(fold.is_weights.values()) - 1.0) < 0.05
            # OOS indices non-empty
            assert fold.oos_end_idx > fold.oos_start_idx

    def test_aggregate_fields_computed(self) -> None:
        wf = PortfolioWalkForward(_two_strategies(400), n_folds=3, n_restarts=3)
        result = wf.run()
        assert result.aggregate_oos_sharpe == pytest.approx(
            np.mean([f.oos_sharpe for f in result.per_fold]),
            rel=1e-9,
        )
        assert result.worst_fold_oos_mdd == max(
            f.oos_mdd_pct for f in result.per_fold
        )
        assert 0.0 <= result.correlation_stability <= 1.0
        assert result.weight_drift_cv >= 0.0

    def test_dict_serialisation(self) -> None:
        wf = PortfolioWalkForward(_two_strategies(250), n_folds=2, n_restarts=3)
        out = wf.run().as_dict()
        for key in (
            "per_fold",
            "aggregate_oos_sharpe",
            "aggregate_oos_mdd",
            "worst_fold_oos_mdd",
            "weight_drift_cv",
            "correlation_stability",
            "strategy_slugs",
        ):
            assert key in out
        assert len(out["per_fold"]) == 2


class TestEdgeCases:
    def test_strategy_with_zero_returns(self) -> None:
        """A strategy producing no P&L still yields a valid fold (weights may shrink)."""
        returns = {
            "active": _make_returns(seed=1, n=300, mu=0.002, sigma=0.01),
            "dead": np.zeros(300),
        }
        wf = PortfolioWalkForward(returns, n_folds=2, n_restarts=3, min_weight=0.05)
        result = wf.run()
        assert result.n_folds_computed == 2
        # Every fold's weights must still be valid allocations
        for fold in result.per_fold:
            assert 0.0 <= fold.is_weights["active"] <= 1.0
            assert 0.0 <= fold.is_weights["dead"] <= 1.0

    def test_correlation_stability_identity_when_single_fold(self) -> None:
        wf = PortfolioWalkForward(
            _two_strategies(200), n_folds=1, oos_fraction=0.3, n_restarts=3,
        )
        result = wf.run()
        # With only one fold, stability defaults to 1.0 (nothing to diverge)
        assert result.correlation_stability == 1.0


class TestAllocationWeightedCorrelationStability:
    """Directly exercise the allocation-weighted stability metric with
    synthetic PortfolioFoldResult inputs."""

    @staticmethod
    def _fold(
        idx: int,
        weights: dict[str, float],
        corr: list[list[float]],
    ) -> PortfolioFoldResult:
        return PortfolioFoldResult(
            fold_index=idx,
            is_start_idx=0, is_end_idx=100,
            oos_start_idx=100, oos_end_idx=150,
            is_weights=weights,
            is_sharpe=1.0,
            oos_sharpe=1.0, oos_mdd_pct=0.05,
            oos_annual_return=0.1, oos_annual_vol=0.1,
            correlation_matrix=corr,
        )

    def _make_wf(self, slugs: list[str]) -> PortfolioWalkForward:
        """Make a minimal PortfolioWalkForward with fake returns just to
        exercise the _correlation_stability method directly."""
        rng = np.random.default_rng(0)
        returns = {s: rng.normal(0, 0.01, 100).astype(np.float64) for s in slugs}
        return PortfolioWalkForward(returns, n_folds=2, n_restarts=3)

    def test_equal_weight_matches_unweighted_mean(self) -> None:
        """With equal weights, allocation-weighted drift equals the
        unweighted mean of off-diagonal spreads — NOT the max."""
        wf = self._make_wf(["a", "b"])
        # Two folds: correlation (a,b) drifts from 0.0 to 0.4
        # Equal weights → pair weight is 0.25×0.25 (only one off-diag pair)
        # Expected: 1.0 - 0.4 = 0.6
        folds = [
            self._fold(0, {"a": 0.5, "b": 0.5}, [[1.0, 0.0], [0.0, 1.0]]),
            self._fold(1, {"a": 0.5, "b": 0.5}, [[1.0, 0.4], [0.4, 1.0]]),
        ]
        stability = wf._correlation_stability(folds)
        assert stability == pytest.approx(0.6, abs=1e-9)

    def test_tiny_weight_pair_drift_doesnt_move_metric(self) -> None:
        """When the drifting pair has ~0 weight, the metric should be
        near 1.0 even though the raw spread is huge."""
        slugs = ["dominant_a", "dominant_b", "tiny_c", "tiny_d"]
        wf = self._make_wf(slugs)
        # c↔d drifts by 0.9 (correlation from 0 to 0.9) but both have
        # weight 0.01 — product 0.0001. Dominant pair a↔b is stable.
        weights = {"dominant_a": 0.49, "dominant_b": 0.49, "tiny_c": 0.01, "tiny_d": 0.01}
        corr_f0 = [
            [1.0, 0.1, 0.0, 0.0],
            [0.1, 1.0, 0.0, 0.0],
            [0.0, 0.0, 1.0, 0.0],
            [0.0, 0.0, 0.0, 1.0],
        ]
        corr_f1 = [
            [1.0, 0.1, 0.0, 0.0],
            [0.1, 1.0, 0.0, 0.0],
            [0.0, 0.0, 1.0, 0.9],  # big drift on tiny pair
            [0.0, 0.0, 0.9, 1.0],
        ]
        folds = [
            self._fold(0, weights, corr_f0),
            self._fold(1, weights, corr_f1),
        ]
        stability = wf._correlation_stability(folds)
        assert stability > 0.99  # tiny pair's drift barely registers

    def test_dominant_pair_drift_drives_metric(self) -> None:
        """When the DOMINANT pair drifts, the metric drops sharply."""
        slugs = ["dominant_a", "dominant_b", "tiny_c", "tiny_d"]
        wf = self._make_wf(slugs)
        weights = {"dominant_a": 0.49, "dominant_b": 0.49, "tiny_c": 0.01, "tiny_d": 0.01}
        corr_f0 = [
            [1.0, 0.0, 0.0, 0.0],
            [0.0, 1.0, 0.0, 0.0],
            [0.0, 0.0, 1.0, 0.0],
            [0.0, 0.0, 0.0, 1.0],
        ]
        corr_f1 = [
            [1.0, 0.6, 0.0, 0.0],  # big drift on dominant pair
            [0.6, 1.0, 0.0, 0.0],
            [0.0, 0.0, 1.0, 0.0],
            [0.0, 0.0, 0.0, 1.0],
        ]
        folds = [
            self._fold(0, weights, corr_f0),
            self._fold(1, weights, corr_f1),
        ]
        stability = wf._correlation_stability(folds)
        # Dominant pair weight product: 0.49*0.49 = 0.2401
        # Total off-diag weights include 2×0.2401 + ... ≈ dominated by the a,b pair
        # So stability ≈ 1 - 0.6 ≈ 0.40
        assert 0.35 < stability < 0.50

    def test_zero_weights_falls_back_to_unweighted(self) -> None:
        """When all allocation weights collapse to zero, the metric
        falls back to the legacy unweighted max-spread behaviour."""
        wf = self._make_wf(["a", "b"])
        weights = {"a": 0.0, "b": 0.0}
        folds = [
            self._fold(0, weights, [[1.0, 0.0], [0.0, 1.0]]),
            self._fold(1, weights, [[1.0, 0.4], [0.4, 1.0]]),
        ]
        stability = wf._correlation_stability(folds)
        # Fallback = 1 - max_spread = 1 - 0.4 = 0.6
        assert stability == pytest.approx(0.6, abs=1e-9)

    def test_single_fold_returns_one(self) -> None:
        wf = self._make_wf(["a", "b"])
        folds = [self._fold(0, {"a": 0.5, "b": 0.5}, [[1.0, 0.0], [0.0, 1.0]])]
        assert wf._correlation_stability(folds) == 1.0
