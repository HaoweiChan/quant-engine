"""Tests for regime classifier: training, state mapping, stability, labels."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from src.prediction.regime import REGIME_LABELS, RegimeClassifier


def _synthetic_regime_data(n: int = 500, seed: int = 42) -> np.ndarray:
    """Generate synthetic data with regime-switching behavior."""
    rng = np.random.default_rng(seed)
    segments = n // 4
    # Trending: positive mean, low vol
    trending = rng.normal(0.5, 0.3, (segments, 3))
    # Choppy: near-zero mean, medium vol
    choppy = rng.normal(0.0, 1.0, (segments, 3))
    # Volatile: large swings
    volatile = rng.normal(-0.2, 2.0, (segments, 3))
    # Uncertain: mixed
    uncertain = rng.normal(0.1, 0.8, (n - 3 * segments, 3))
    return np.vstack([trending, choppy, volatile, uncertain])


class TestRegimeClassifier:
    def test_train_and_predict(self) -> None:
        features = _synthetic_regime_data()
        clf = RegimeClassifier(n_states=4)
        mapping = clf.train(features)
        assert len(mapping.state_to_label) == 4
        states = clf.predict_states(features)
        assert states.shape == (500,)
        assert all(0 <= s < 4 for s in states)

    def test_regime_labels_valid(self) -> None:
        features = _synthetic_regime_data()
        clf = RegimeClassifier(n_states=4)
        clf.train(features)
        regimes = clf.predict_regimes(features)
        for r in regimes:
            assert r in REGIME_LABELS

    def test_trend_strength_range(self) -> None:
        features = _synthetic_regime_data()
        clf = RegimeClassifier(n_states=4)
        clf.train(features)
        strengths = clf.trend_strength(features)
        assert np.all((strengths >= 0) & (strengths <= 1))

    def test_posteriors_sum_to_one(self) -> None:
        features = _synthetic_regime_data()
        clf = RegimeClassifier(n_states=4)
        clf.train(features)
        posteriors = clf.predict_posteriors(features)
        row_sums = posteriors.sum(axis=1)
        np.testing.assert_array_almost_equal(row_sums, 1.0)

    def test_predict_without_training_raises(self) -> None:
        clf = RegimeClassifier()
        with pytest.raises(RuntimeError, match="not trained"):
            clf.predict_states(np.zeros((10, 3)))

    def test_stability_report(self) -> None:
        features = _synthetic_regime_data()
        clf = RegimeClassifier(n_states=4)
        clf.train(features)
        report = clf.evaluate_stability(features)
        assert report.mean_duration > 0
        assert 0 <= report.switching_frequency <= 1
        assert len(report.state_durations) == 4

    def test_3_states(self) -> None:
        features = _synthetic_regime_data(300)
        clf = RegimeClassifier(n_states=3)
        mapping = clf.train(features)
        assert len(mapping.state_to_label) == 3
        regimes = clf.predict_regimes(features)
        for r in regimes:
            assert r in REGIME_LABELS

    def test_save_load_roundtrip(self, tmp_path: Path) -> None:
        features = _synthetic_regime_data()
        clf = RegimeClassifier(n_states=4)
        clf.train(features)
        pred_before = clf.predict_states(features)

        model_path = tmp_path / "regime.pkl"
        clf.save(model_path)
        loaded = RegimeClassifier.load(model_path)
        pred_after = loaded.predict_states(features)

        np.testing.assert_array_equal(pred_before, pred_after)
