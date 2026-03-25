"""Tests for prediction feature pipeline: merge, NaN handling, split correctness."""
import numpy as np
import polars as pl
import pytest

from src.prediction.features import (
    build_labels,
    clean_features,
    merge_features,
    prepare_xy,
    split_time_ordered,
)


def _make_feature_df(n: int = 200) -> pl.DataFrame:
    rng = np.random.default_rng(42)
    return pl.DataFrame({
        "timestamp": pl.datetime_range(
            pl.lit("2023-01-01").str.to_datetime(),
            pl.lit("2023-01-01").str.to_datetime() + pl.duration(days=n - 1),
            interval="1d",
            eager=True,
        ),
        "close": 20000 + rng.standard_normal(n).cumsum() * 50,
        "rsi_14": rng.uniform(20, 80, n),
        "sma_20": 20000 + rng.standard_normal(n).cumsum() * 10,
        "volume": rng.integers(1000, 5000, n).astype(float),
    })


class TestMergeFeatures:
    def test_merge_two_dfs(self) -> None:
        df1 = pl.DataFrame({
            "timestamp": [1, 2, 3],
            "feature_a": [10.0, 20.0, 30.0],
        })
        df2 = pl.DataFrame({
            "timestamp": [1, 2, 3],
            "feature_b": [40.0, 50.0, 60.0],
        })
        merged = merge_features(df1, df2)
        assert "feature_a" in merged.columns
        assert "feature_b" in merged.columns
        assert len(merged) == 3

    def test_merge_empty_raises(self) -> None:
        with pytest.raises(ValueError, match="At least one"):
            merge_features()

    def test_merge_inner_join(self) -> None:
        df1 = pl.DataFrame({"timestamp": [1, 2, 3], "a": [1.0, 2.0, 3.0]})
        df2 = pl.DataFrame({"timestamp": [2, 3, 4], "b": [5.0, 6.0, 7.0]})
        merged = merge_features(df1, df2)
        assert len(merged) == 2


class TestCleanFeatures:
    def test_removes_nan(self) -> None:
        df = pl.DataFrame({
            "timestamp": [1, 2, 3],
            "val": [1.0, float("nan"), 3.0],
        })
        cleaned, report = clean_features(df)
        assert cleaned["val"].null_count() == 0
        assert not any(cleaned["val"].is_nan())

    def test_removes_inf(self) -> None:
        df = pl.DataFrame({
            "timestamp": [1, 2, 3],
            "val": [1.0, float("inf"), 3.0],
        })
        cleaned, report = clean_features(df)
        assert len(report.inf_columns) > 0
        assert cleaned["val"].is_infinite().sum() == 0

    def test_forward_fills(self) -> None:
        df = pl.DataFrame({
            "timestamp": [1, 2, 3, 4],
            "val": [1.0, None, None, 4.0],
        })
        cleaned, report = clean_features(df)
        # After forward-fill, row 1 and 2 should be 1.0
        assert len(cleaned) == 4
        assert cleaned["val"][1] == 1.0
        assert cleaned["val"][2] == 1.0

    def test_drops_leading_nulls(self) -> None:
        df = pl.DataFrame({
            "timestamp": [1, 2, 3],
            "val": [None, None, 3.0],
        })
        cleaned, report = clean_features(df)
        assert report.dropped_rows == 2


class TestSplitTimeOrdered:
    def test_splits_are_chronological(self) -> None:
        df = _make_feature_df(200)
        splits = split_time_ordered(df)
        assert len(splits.train) > 0
        assert len(splits.model_val) > 0
        assert len(splits.position_val) > 0
        assert len(splits.final_oos) > 0

        # Verify no temporal overlap
        train_max = splits.train["timestamp"].max()
        val_min = splits.model_val["timestamp"].min()
        assert train_max < val_min  # type: ignore[operator]

        mval_max = splits.model_val["timestamp"].max()
        pval_min = splits.position_val["timestamp"].min()
        assert mval_max < pval_min  # type: ignore[operator]

    def test_split_ratios_approximate(self) -> None:
        df = _make_feature_df(1000)
        splits = split_time_ordered(df)
        assert 550 < len(splits.train) < 650
        assert 100 < len(splits.model_val) < 200
        assert 100 < len(splits.position_val) < 200
        assert 50 < len(splits.final_oos) < 150

    def test_no_leakage(self) -> None:
        df = _make_feature_df(200)
        splits = split_time_ordered(df)
        train_ts = set(splits.train["timestamp"].to_list())
        val_ts = set(splits.model_val["timestamp"].to_list())
        assert train_ts.isdisjoint(val_ts)


class TestBuildLabels:
    def test_label_creation(self) -> None:
        df = pl.DataFrame({
            "timestamp": list(range(20)),
            "close": [100.0 + i for i in range(20)],
        })
        labeled = build_labels(df, horizon=5)
        assert "label" in labeled.columns
        assert "forward_return" in labeled.columns
        assert len(labeled) == 15  # 20 - 5

    def test_labels_are_binary(self) -> None:
        rng = np.random.default_rng(42)
        df = pl.DataFrame({
            "timestamp": list(range(100)),
            "close": 100 + rng.standard_normal(100).cumsum(),
        })
        labeled = build_labels(df, horizon=5)
        unique = set(labeled["label"].to_list())
        assert unique <= {0, 1}


class TestPrepareXY:
    def test_output_shapes(self) -> None:
        df = pl.DataFrame({
            "f1": [1.0, 2.0, 3.0],
            "f2": [4.0, 5.0, 6.0],
            "label": [1, 0, 1],
        })
        x, y = prepare_xy(df, ["f1", "f2"])
        assert x.shape == (3, 2)
        assert y.shape == (3,)
        assert x.dtype == np.float64
