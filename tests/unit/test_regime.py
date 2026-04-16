"""Unit tests for HMM regime detection module."""

from __future__ import annotations

import numpy as np

from src.simulator.regime import (
    compute_regime_metrics,
    fit_regime_model,
    label_regimes,
)


def _synthetic_regime_returns(seed: int = 42) -> np.ndarray:
    """Generate synthetic returns with two distinct volatility regimes."""
    rng = np.random.default_rng(seed)
    low_vol = rng.normal(0.0005, 0.005, 200)  # 200 low-vol days
    high_vol = rng.normal(-0.0002, 0.025, 100)  # 100 high-vol days
    return np.concatenate([low_vol, high_vol])


class TestFitRegimeModel:
    def test_two_state_fit(self) -> None:
        returns = _synthetic_regime_returns()
        model = fit_regime_model(returns, n_states=2, seed=42)
        assert model.n_states == 2
        assert model.state_labels == ["low_vol", "high_vol"]
        assert len(model.means) == 2
        assert len(model.variances) == 2
        # Variances should be sorted ascending
        assert model.variances[0] <= model.variances[1]

    def test_three_state_fit(self) -> None:
        rng = np.random.default_rng(42)
        low = rng.normal(0.001, 0.003, 150)
        mid = rng.normal(0.0, 0.010, 100)
        high = rng.normal(-0.002, 0.030, 50)
        returns = np.concatenate([low, mid, high])
        model = fit_regime_model(returns, n_states=3, seed=42)
        assert model.n_states == 3
        assert model.state_labels == ["low_vol", "medium_vol", "high_vol"]
        assert model.variances[0] <= model.variances[1] <= model.variances[2]

    def test_transition_matrix_shape(self) -> None:
        returns = _synthetic_regime_returns()
        model = fit_regime_model(returns, n_states=2, seed=42)
        assert model.transition_matrix.shape == (2, 2)
        # Rows should sum to 1
        for row in model.transition_matrix:
            assert abs(sum(row) - 1.0) < 1e-6

    def test_bic_is_finite(self) -> None:
        returns = _synthetic_regime_returns()
        model = fit_regime_model(returns, n_states=2, seed=42)
        assert np.isfinite(model.bic)


class TestLabelRegimes:
    def test_labels_match_input_length(self) -> None:
        returns = _synthetic_regime_returns()
        model = fit_regime_model(returns, n_states=2, seed=42)
        labels = label_regimes(model, returns)
        assert len(labels) == len(returns)

    def test_labels_are_valid_indices(self) -> None:
        returns = _synthetic_regime_returns()
        model = fit_regime_model(returns, n_states=2, seed=42)
        labels = label_regimes(model, returns)
        assert set(labels).issubset({0, 1})

    def test_low_vol_region_mostly_labeled_0(self) -> None:
        returns = _synthetic_regime_returns()
        model = fit_regime_model(returns, n_states=2, seed=42)
        labels = label_regimes(model, returns)
        # First 200 returns are low-vol; majority should be state 0
        low_vol_labels = labels[:200]
        assert np.mean(low_vol_labels == 0) > 0.5


class TestComputeRegimeMetrics:
    def test_per_regime_metrics(self) -> None:
        returns = _synthetic_regime_returns()
        model = fit_regime_model(returns, n_states=2, seed=42)
        labels = label_regimes(model, returns)
        metrics = compute_regime_metrics(returns, labels, model)
        assert len(metrics) == 2
        for m in metrics:
            assert m.regime_label in ("low_vol", "high_vol")
            assert m.n_sessions > 0

    def test_empty_regime(self) -> None:
        returns = np.array([0.01, 0.02, -0.01])
        model = fit_regime_model(returns, n_states=2, seed=42)
        # Force all labels to state 0
        labels = np.array([0, 0, 0], dtype=np.int64)
        metrics = compute_regime_metrics(returns, labels, model)
        # State 1 should have 0 sessions
        state1 = [m for m in metrics if m.n_sessions == 0]
        assert len(state1) == 1
