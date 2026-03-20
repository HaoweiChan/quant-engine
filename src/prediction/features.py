"""Feature pipeline: merge, clean, split Feature Store output into ML-ready DataFrames."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import numpy.typing as npt
import polars as pl
import structlog

logger = structlog.get_logger(__name__)

SPLIT_RATIOS = {
    "train": 0.60,
    "model_val": 0.15,
    "position_val": 0.15,
    "final_oos": 0.10,
}


@dataclass
class DataSplits:
    train: pl.DataFrame
    model_val: pl.DataFrame
    position_val: pl.DataFrame
    final_oos: pl.DataFrame


@dataclass
class FeatureImportance:
    feature_names: list[str]
    importance_values: list[float]
    importance_type: str = "gain"

    @property
    def ranked(self) -> list[tuple[str, float]]:
        pairs = list(zip(self.feature_names, self.importance_values, strict=True))
        return sorted(pairs, key=lambda x: x[1], reverse=True)


@dataclass
class CleanReport:
    rows_before: int = 0
    rows_after: int = 0
    nan_columns: list[str] = field(default_factory=list)
    inf_columns: list[str] = field(default_factory=list)
    dropped_rows: int = 0


def merge_features(*dfs: pl.DataFrame, on: str = "timestamp") -> pl.DataFrame:
    """Merge multiple feature DataFrames on a shared timestamp column."""
    if not dfs:
        raise ValueError("At least one DataFrame required")
    result = dfs[0]
    for df in dfs[1:]:
        new_cols = [c for c in df.columns if c not in result.columns or c == on]
        result = result.join(df.select(new_cols), on=on, how="inner")
    return result.sort(on)


def clean_features(df: pl.DataFrame) -> tuple[pl.DataFrame, CleanReport]:
    """Replace NaN/inf, forward-fill, drop remaining NaN rows."""
    report = CleanReport(rows_before=len(df))
    numeric_cols = [c for c in df.columns if df[c].dtype in (pl.Float64, pl.Float32)]

    for col in numeric_cols:
        inf_count = df.filter(pl.col(col).is_infinite()).height
        if inf_count > 0:
            report.inf_columns.append(col)

    cleaned = df.with_columns([
        pl.when(pl.col(c).is_infinite() | pl.col(c).is_nan())
        .then(None).otherwise(pl.col(c)).alias(c)
        for c in numeric_cols
    ])

    for col in numeric_cols:
        null_count = cleaned[col].null_count()
        if null_count > 0 and col not in report.inf_columns:
            report.nan_columns.append(col)

    cleaned = cleaned.with_columns([
        pl.col(c).forward_fill().alias(c) for c in numeric_cols
    ])

    null_mask = pl.lit(False)
    for c in numeric_cols:
        null_mask = null_mask | pl.col(c).is_null()
    cleaned = cleaned.filter(~null_mask)

    report.rows_after = len(cleaned)
    report.dropped_rows = report.rows_before - report.rows_after
    if report.nan_columns:
        logger.info("nan_columns_filled", columns=report.nan_columns)
    if report.inf_columns:
        logger.info("inf_columns_replaced", columns=report.inf_columns)
    if report.dropped_rows > 0:
        logger.info("dropped_null_rows", count=report.dropped_rows)
    return cleaned, report


def split_time_ordered(df: pl.DataFrame, timestamp_col: str = "timestamp") -> DataSplits:
    """Split DataFrame chronologically: 60% train, 15% model_val, 15% position_val, 10% OOS."""
    df = df.sort(timestamp_col)
    n = len(df)
    t_train = int(n * SPLIT_RATIOS["train"])
    t_model_val = t_train + int(n * SPLIT_RATIOS["model_val"])
    t_position_val = t_model_val + int(n * SPLIT_RATIOS["position_val"])
    return DataSplits(
        train=df[:t_train],
        model_val=df[t_train:t_model_val],
        position_val=df[t_model_val:t_position_val],
        final_oos=df[t_position_val:],
    )


def compute_feature_importance(
    model: Any,
    feature_names: list[str],
    importance_type: str = "gain",
) -> FeatureImportance:
    """Extract feature importance from a trained LightGBM Booster or sklearn-like model."""
    booster = getattr(model, "booster_", None) or model
    raw: Any = booster.feature_importance(importance_type=importance_type)
    values = [float(v) for v in raw]
    total = sum(values)
    if total > 0:
        values = [v / total for v in values]
    return FeatureImportance(
        feature_names=list(feature_names),
        importance_values=values,
        importance_type=importance_type,
    )


def build_labels(
    df: pl.DataFrame,
    horizon: int = 5,
    price_col: str = "close",
) -> pl.DataFrame:
    """Create binary up/down labels based on N-day forward return."""
    future_price = pl.col(price_col).shift(-horizon)
    return df.with_columns(
        ((future_price - pl.col(price_col)) / pl.col(price_col)).alias("forward_return"),
        (future_price > pl.col(price_col)).cast(pl.Int32).alias("label"),
    ).head(len(df) - horizon)


def prepare_xy(
    df: pl.DataFrame,
    feature_cols: list[str],
    label_col: str = "label",
) -> tuple[npt.NDArray[np.float64], npt.NDArray[np.float64]]:
    """Extract feature matrix X and label vector y as numpy arrays."""
    x = df.select(feature_cols).to_numpy().astype(np.float64)
    y = df[label_col].to_numpy().astype(np.float64)
    return x, y
