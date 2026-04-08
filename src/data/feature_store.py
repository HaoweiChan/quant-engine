"""Feature computation, caching, and storage."""
from __future__ import annotations

import hashlib
from collections import OrderedDict
from pathlib import Path

import pandas as pd
import polars as pl
import structlog

from src.data.feature_plugins.base import FeaturePlugin

logger = structlog.get_logger(__name__)


def compute_standard_indicators(df_pd: pd.DataFrame) -> pd.DataFrame:
    """Compute standard technical indicators via pandas-ta."""
    import pandas_ta  # noqa: F401

    result = df_pd.copy()
    result.ta.rsi(length=14, append=True)
    result.ta.macd(fast=12, slow=26, signal=9, append=True)
    result.ta.bbands(length=20, std=2, append=True)
    result.ta.sma(length=20, append=True)
    result.ta.sma(length=50, append=True)
    result.ta.sma(length=200, append=True)
    result.ta.atr(length=14, append=True)
    result.ta.adx(length=14, append=True)
    result.ta.stoch(k=14, d=3, append=True)
    return result


class FeatureStore:
    def __init__(self, storage_dir: Path | None = None, cache_size: int = 32) -> None:
        self._storage_dir = storage_dir
        self._plugins: list[FeaturePlugin] = []
        self._cache: OrderedDict[str, pl.DataFrame] = OrderedDict()
        self._cache_size = cache_size
        self._last_bar_hash: str | None = None

    def register_plugin(self, plugin: FeaturePlugin) -> None:
        self._plugins.append(plugin)

    def compute_features(self, bars: pl.DataFrame) -> pl.DataFrame:
        """Compute all features: standard indicators + plugin features."""
        cache_key = self._make_cache_key(bars)
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached

        df_pd = bars.to_pandas()
        result_pd = compute_standard_indicators(df_pd)
        result = pl.from_pandas(result_pd)

        for plugin in self._plugins:
            try:
                missing = [c for c in plugin.required_columns() if c not in bars.columns]
                if missing:
                    logger.warning(
                        "plugin_missing_columns",
                        plugin=type(plugin).__name__, missing=missing,
                    )
                    continue
                plugin_result = plugin.compute(bars)
                for col in plugin_result.columns:
                    if col not in result.columns:
                        result = result.with_columns(plugin_result[col])
            except Exception:
                logger.exception("plugin_failed", plugin=type(plugin).__name__)

        self._cache_put(cache_key, result)
        return result

    def compute_incremental(self, bars: pl.DataFrame, last_n: int = 1) -> pl.DataFrame:
        """Only compute features for new bars, reusing cached history."""
        bar_hash = self._hash_df(bars)
        if bar_hash == self._last_bar_hash:
            cache_key = self._make_cache_key(bars)
            cached = self._cache_get(cache_key)
            if cached is not None:
                return cached
        self._last_bar_hash = bar_hash
        return self.compute_features(bars)

    def save_parquet(self, features: pl.DataFrame, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        features.write_parquet(path)

    def load_parquet(
        self,
        path: Path,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> pl.DataFrame:
        df = pl.read_parquet(path)
        if date_from and "timestamp" in df.columns:
            df = df.filter(pl.col("timestamp") >= pl.lit(date_from).str.to_datetime())
        if date_to and "timestamp" in df.columns:
            df = df.filter(pl.col("timestamp") <= pl.lit(date_to).str.to_datetime())
        return df

    def invalidate_cache(self) -> None:
        self._cache.clear()
        self._last_bar_hash = None

    def _make_cache_key(self, df: pl.DataFrame) -> str:
        return self._hash_df(df)

    def _hash_df(self, df: pl.DataFrame) -> str:
        h = hashlib.sha256()
        h.update(str(df.shape).encode())
        if len(df) > 0:
            h.update(str(df.row(0)).encode())
            h.update(str(df.row(-1)).encode())
        return h.hexdigest()[:16]

    def _cache_get(self, key: str) -> pl.DataFrame | None:
        if key in self._cache:
            self._cache.move_to_end(key)
            return self._cache[key]
        return None

    def _cache_put(self, key: str, df: pl.DataFrame) -> None:
        self._cache[key] = df
        self._cache.move_to_end(key)
        while len(self._cache) > self._cache_size:
            self._cache.popitem(last=False)
