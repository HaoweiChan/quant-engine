"""Tests for Sequential Optimizer: Stage 1, Stage 2, full optimization."""
from __future__ import annotations

import numpy as np
import polars as pl

from src.pipeline.optimizer import (
    Stage1Result,
    run_final_oos,
    run_full_optimization,
    run_robustness_test,
    run_stage1,
    run_stage2,
)
from src.prediction.features import DataSplits, build_labels, split_time_ordered


def _make_splits() -> tuple[DataSplits, list[str]]:
    rng = np.random.default_rng(42)
    n = 400
    feature_cols = ["f1", "f2", "f3"]
    df = pl.DataFrame({
        "timestamp": list(range(n)),
        "close": (20000 + rng.standard_normal(n).cumsum() * 50).tolist(),
        "f1": rng.standard_normal(n).tolist(),
        "f2": rng.standard_normal(n).tolist(),
        "f3": rng.standard_normal(n).tolist(),
    })
    labeled = build_labels(df, horizon=5)
    splits = split_time_ordered(labeled)
    return splits, feature_cols


def _make_param_propagation_splits() -> tuple[DataSplits, list[str]]:
    n = 120
    feature_cols = ["f1", "f2"]
    base = np.linspace(0.001, 0.006, n)
    direction = np.where(np.arange(n) % 2 == 0, 1.0, -1.0)
    forward_returns = (base * direction).tolist()
    frame = pl.DataFrame(
        {
            "timestamp": list(range(n)),
            "close": (20_000 + np.cumsum(np.array(forward_returns) * 20_000)).tolist(),
            "f1": np.sin(np.linspace(0.0, 6.0, n)).tolist(),
            "f2": np.cos(np.linspace(0.0, 6.0, n)).tolist(),
            "forward_return": forward_returns,
            "label": [1 if r > 0 else 0 for r in forward_returns],
        }
    )
    splits = split_time_ordered(frame)
    return splits, feature_cols


class _StubDirectionModel:
    def __init__(self, directions: np.ndarray, confidences: np.ndarray) -> None:
        self._directions = directions
        self._confidences = confidences

    def predict_direction(self, x: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        n = len(x)
        return self._directions[:n], self._confidences[:n]


class TestOptimizer:
    def test_stage1(self) -> None:
        splits, feature_cols = _make_splits()
        result = run_stage1(
            splits, feature_cols,
            regime_feature_cols=["f1", "f2", "f3"],
        )
        assert result.direction_model is not None
        assert result.regime_model is not None
        assert result.vol_model is not None
        assert len(result.direction_metrics) > 0

    def test_stage2(self) -> None:
        splits, feature_cols = _make_splits()
        s1 = run_stage1(splits, feature_cols, regime_feature_cols=["f1", "f2", "f3"])
        s2 = run_stage2(s1, splits, feature_cols)
        assert len(s2.results_grid) > 0
        assert "stop_atr_mult" in s2.best_params

    def test_full_optimization(self) -> None:
        splits, feature_cols = _make_splits()
        result = run_full_optimization(
            splits, feature_cols,
            regime_feature_cols=["f1", "f2", "f3"],
        )
        assert result.stage1.direction_model is not None
        assert len(result.stage2.results_grid) > 0
        assert isinstance(result.passed_robustness, bool)

    def test_stage2_params_propagate_to_robustness_and_oos(self) -> None:
        splits, feature_cols = _make_param_propagation_splits()
        eval_len = len(splits.position_val)
        directions = np.where(np.arange(eval_len) % 3 == 0, 1.0, -1.0).astype(np.float64)
        confidences = np.linspace(0.3, 1.0, eval_len).astype(np.float64)
        stage1 = Stage1Result(direction_model=_StubDirectionModel(directions, confidences))
        param_grid = {"stop_atr_mult": [0.3, 2.0], "trail_atr_mult": [0.5, 4.0]}

        stage2 = run_stage2(stage1, splits, feature_cols, param_grid=param_grid)
        assert stage2.best_params

        robust_best = run_robustness_test(
            stage1, splits, feature_cols, stage2_params=stage2.best_params, degradation=0.0
        )
        robust_alt = run_robustness_test(
            stage1,
            splits,
            feature_cols,
            stage2_params={"stop_atr_mult": 0.1, "trail_atr_mult": 0.1},
            degradation=0.0,
        )
        oos_best = run_final_oos(stage1, splits, feature_cols, stage2_params=stage2.best_params)
        oos_alt = run_final_oos(
            stage1,
            splits,
            feature_cols,
            stage2_params={"stop_atr_mult": 0.1, "trail_atr_mult": 0.1},
        )

        assert robust_best != robust_alt
        assert oos_best != oos_alt
