"""Unit tests for Kelly-fractional sizer."""
from __future__ import annotations

import numpy as np
import pytest

from src.core.kelly_sizer import (
    compute_kelly_fractions,
    covariance_from_returns,
)


class TestClosedForm:
    """For diagonal Sigma, Kelly reduces to w_i = f * mu_i / sigma_ii."""

    def test_diagonal_two_asset(self) -> None:
        mu = {"a": 0.10, "b": 0.04}
        sigma = {"a": {"a": 0.04, "b": 0.0}, "b": {"a": 0.0, "b": 0.01}}
        # Raw Kelly: a = 0.10/0.04 = 2.5, b = 0.04/0.01 = 4.0
        # Quarter-Kelly: a = 0.625, b = 1.0 → total 1.625 > 1 → renormalize
        # Renormalized: a = 0.625/1.625 ≈ 0.385, b = 1.0/1.625 ≈ 0.615
        result = compute_kelly_fractions(mu, sigma, fraction=0.25)
        assert result.method == "kelly"
        assert abs(result.weights["a"] - 0.625 / 1.625) < 1e-4
        assert abs(result.weights["b"] - 1.0 / 1.625) < 1e-4
        assert sum(result.weights.values()) == pytest.approx(1.0, rel=1e-6)

    def test_diagonal_small_fraction_no_renormalize(self) -> None:
        """When raw sum is already <= 1, Kelly weights passed through unchanged."""
        mu = {"a": 0.02, "b": 0.02}
        sigma = {"a": {"a": 1.0, "b": 0.0}, "b": {"a": 0.0, "b": 1.0}}
        # Raw Kelly: a=0.02, b=0.02. Quarter-Kelly: a=0.005, b=0.005. Sum 0.01 < 1.
        result = compute_kelly_fractions(mu, sigma, fraction=0.25)
        assert result.method == "kelly"
        assert abs(result.weights["a"] - 0.005) < 1e-6
        assert abs(result.weights["b"] - 0.005) < 1e-6
        assert not any("renormalized" in w for w in result.warnings)


class TestRobustness:
    def test_singular_matrix_fallback(self) -> None:
        mu = {"a": 0.1, "b": 0.1}
        # Perfectly singular
        sigma = {"a": {"a": 0.01, "b": 0.01}, "b": {"a": 0.01, "b": 0.01}}
        result = compute_kelly_fractions(mu, sigma, fraction=0.25)
        assert result.method == "fallback_equal"
        assert result.weights["a"] == pytest.approx(0.25 / 2)
        assert result.weights["b"] == pytest.approx(0.25 / 2)
        assert any("Singular" in w for w in result.warnings)

    def test_negative_mu_clipped_in_long_only(self) -> None:
        """Long-only: negative expected return strategies get weight 0."""
        mu = {"a": 0.10, "b": -0.05}
        sigma = {"a": {"a": 0.01, "b": 0.0}, "b": {"a": 0.0, "b": 0.01}}
        # Raw Kelly b = -0.05/0.01 = -5.0 → clipped to 0
        result = compute_kelly_fractions(mu, sigma, fraction=0.25, long_only=True)
        assert result.weights["b"] == 0.0
        assert result.weights["a"] > 0.0
        assert any("negative Kelly weight" in w for w in result.warnings)

    def test_negative_mu_allowed_when_long_only_false(self) -> None:
        """With long_only=False, negative weights survive (but total must stay > 0)."""
        mu = {"a": 0.10, "b": -0.05}
        sigma = {"a": {"a": 0.01, "b": 0.0}, "b": {"a": 0.0, "b": 0.01}}
        result = compute_kelly_fractions(mu, sigma, fraction=0.25, long_only=False)
        # Either 'kelly' (if total is still positive and finite) or 'fallback_equal'
        assert result.method in {"kelly", "fallback_equal"}

    def test_all_non_positive_fallback(self) -> None:
        mu = {"a": -0.01, "b": -0.02}
        sigma = {"a": {"a": 0.01, "b": 0.0}, "b": {"a": 0.0, "b": 0.01}}
        result = compute_kelly_fractions(mu, sigma, fraction=0.25, long_only=True)
        assert result.method == "fallback_equal"
        assert any("non-positive" in w for w in result.warnings)


class TestInputValidation:
    def test_fraction_out_of_range(self) -> None:
        mu = {"a": 0.1, "b": 0.1}
        sigma = {"a": {"a": 0.01, "b": 0.0}, "b": {"a": 0.0, "b": 0.01}}
        with pytest.raises(ValueError, match="fraction"):
            compute_kelly_fractions(mu, sigma, fraction=1.5)
        with pytest.raises(ValueError, match="fraction"):
            compute_kelly_fractions(mu, sigma, fraction=0.0)

    def test_shape_mismatch(self) -> None:
        mu = np.array([0.1, 0.1])
        sigma = np.array([[0.01, 0.0, 0.0], [0.0, 0.01, 0.0], [0.0, 0.0, 0.01]])
        with pytest.raises(ValueError, match="sigma shape"):
            compute_kelly_fractions(
                mu, sigma, strategy_slugs=["a", "b"], fraction=0.25,
            )

    def test_array_without_slugs(self) -> None:
        mu = np.array([0.1, 0.1])
        sigma = np.eye(2) * 0.01
        with pytest.raises(ValueError, match="strategy_slugs is required"):
            compute_kelly_fractions(mu, sigma, fraction=0.25)


class TestCovarianceFromReturns:
    def test_annualization(self) -> None:
        rng = np.random.default_rng(42)
        returns = {
            "a": rng.normal(0.001, 0.01, 252),
            "b": rng.normal(0.0005, 0.008, 252),
        }
        mu_daily, sigma_daily = covariance_from_returns(returns, annualize=False)
        mu_ann, sigma_ann = covariance_from_returns(returns, annualize=True)
        # Annualized mu ~ 252x daily
        assert abs(mu_ann["a"] - mu_daily["a"] * 252) < 1e-9
        assert abs(sigma_ann["a"]["a"] - sigma_daily["a"]["a"] * 252) < 1e-9

    def test_requires_two_strategies(self) -> None:
        returns = {"only": np.array([0.01, 0.02])}
        with pytest.raises(ValueError, match="at least 2 strategies"):
            covariance_from_returns(returns)


class TestEndToEnd:
    def test_four_strategies_realistic(self) -> None:
        """Simulate 4 uncorrelated strategies with varying Sharpes → Kelly assigns
        higher weight to higher-Sharpe names."""
        rng = np.random.default_rng(123)
        returns = {
            "high_sharpe": rng.normal(0.003, 0.005, 500),
            "med_sharpe": rng.normal(0.001, 0.007, 500),
            "low_sharpe": rng.normal(0.0003, 0.01, 500),
            "tiny": rng.normal(0.0001, 0.015, 500),
        }
        mu, sigma = covariance_from_returns(returns)
        result = compute_kelly_fractions(mu, sigma, fraction=0.25)
        # high_sharpe should dominate
        assert result.weights["high_sharpe"] > result.weights["tiny"]
        assert result.weights["high_sharpe"] > result.weights["low_sharpe"]
        # All weights in [0, 1]
        for w in result.weights.values():
            assert 0.0 <= w <= 1.0
