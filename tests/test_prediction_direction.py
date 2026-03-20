"""Tests for direction classifier: training, output ranges, walk-forward, serialization."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from src.prediction.direction import (
    DirectionClassifier,
    compute_metrics,
    walk_forward_validate,
)


def _synthetic_data(
    n: int = 500, n_features: int = 10, seed: int = 42,
) -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(seed)
    x = rng.standard_normal((n, n_features))
    # Label depends on weighted sum of first 3 features + noise
    logit = 0.5 * x[:, 0] + 0.3 * x[:, 1] - 0.2 * x[:, 2] + rng.standard_normal(n) * 0.5
    y = (logit > 0).astype(np.float64)
    return x, y


class TestComputeMetrics:
    def test_perfect_predictions(self) -> None:
        y_true = np.array([0, 1, 1, 0, 1])
        y_prob = np.array([0.1, 0.9, 0.8, 0.2, 0.95])
        m = compute_metrics(y_true, y_prob)
        assert m.accuracy == 1.0
        assert m.precision == 1.0
        assert m.recall == 1.0
        assert m.brier_score < 0.1
        assert m.auc == 1.0

    def test_metric_ranges(self) -> None:
        rng = np.random.default_rng(42)
        y_true = rng.integers(0, 2, 100).astype(np.float64)
        y_prob = rng.uniform(0, 1, 100)
        m = compute_metrics(y_true, y_prob)
        assert 0.0 <= m.accuracy <= 1.0
        assert 0.0 <= m.precision <= 1.0
        assert 0.0 <= m.recall <= 1.0
        assert 0.0 <= m.brier_score <= 1.0


class TestDirectionClassifier:
    def test_train_and_predict(self) -> None:
        x, y = _synthetic_data(300)
        clf = DirectionClassifier()
        clf.train(x[:200], y[:200], x[200:], y[200:])
        proba = clf.predict_proba(x[200:])
        assert proba.shape == (100,)
        assert np.all((proba >= 0) & (proba <= 1))

    def test_direction_range(self) -> None:
        x, y = _synthetic_data(300)
        clf = DirectionClassifier()
        clf.train(x[:200], y[:200])
        dirs, confs = clf.predict_direction(x[200:])
        assert np.all((dirs >= -1) & (dirs <= 1))
        assert np.all((confs >= 0) & (confs <= 1))

    def test_predict_without_training_raises(self) -> None:
        clf = DirectionClassifier()
        with pytest.raises(RuntimeError, match="not trained"):
            clf.predict_proba(np.zeros((5, 10)))

    def test_save_load_roundtrip(self, tmp_path: Path) -> None:
        x, y = _synthetic_data(200)
        clf = DirectionClassifier(horizon=3)
        clf.train(x[:150], y[:150])
        pred_before = clf.predict_proba(x[150:])

        model_path = tmp_path / "model.pkl"
        clf.save(model_path)
        loaded = DirectionClassifier.load(model_path)
        pred_after = loaded.predict_proba(x[150:])

        np.testing.assert_array_almost_equal(pred_before, pred_after)
        assert loaded.horizon == 3


class TestWalkForward:
    def test_walk_forward_produces_folds(self) -> None:
        x, y = _synthetic_data(500)
        result = walk_forward_validate(
            x, y, step_size=50, min_train_size=200,
        )
        assert len(result.fold_metrics) >= 1

    def test_aggregated_metrics(self) -> None:
        x, y = _synthetic_data(500)
        result = walk_forward_validate(
            x, y, step_size=50, min_train_size=200,
        )
        agg = result.aggregated
        assert 0.0 <= agg.accuracy <= 1.0
        assert 0.0 <= agg.brier_score <= 1.0

    def test_no_folds_raises(self) -> None:
        x, y = _synthetic_data(50)
        result = walk_forward_validate(x, y, step_size=50, min_train_size=100)
        assert len(result.fold_metrics) == 0
        with pytest.raises(ValueError, match="No fold"):
            _ = result.aggregated
