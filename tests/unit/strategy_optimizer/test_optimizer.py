"""Tests for Sequential Optimizer: Stage 1, Stage 2, full optimization."""
from __future__ import annotations

import numpy as np
import polars as pl

from src.pipeline.optimizer import run_full_optimization, run_stage1, run_stage2
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
