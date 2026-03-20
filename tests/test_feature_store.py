"""Tests for feature store: indicators, plugins, parquet, cache."""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import polars as pl

from src.data.feature_plugins.base import FeaturePlugin
from src.data.feature_plugins.taifex import TaifexFeaturePlugin
from src.data.feature_store import FeatureStore, compute_standard_indicators


def _make_bars(n: int = 250) -> pl.DataFrame:
    base = 20000.0
    import math
    from datetime import timedelta
    timestamps = [
        datetime(2024, 1, 2, tzinfo=UTC) + timedelta(days=i)
        for i in range(n)
    ]
    prices = [base + 50 * math.sin(i / 10) + i * 0.5 for i in range(n)]
    return pl.DataFrame({
        "timestamp": timestamps,
        "open": prices,
        "high": [p + 20 for p in prices],
        "low": [p - 20 for p in prices],
        "close": [p + 5 for p in prices],
        "volume": [1000 + i * 10 for i in range(n)],
    })


class TestStandardIndicators:
    def test_rsi_present(self) -> None:
        bars = _make_bars(100)
        df_pd = bars.to_pandas()
        result = compute_standard_indicators(df_pd)
        rsi_cols = [c for c in result.columns if "RSI" in c.upper()]
        assert len(rsi_cols) > 0

    def test_macd_present(self) -> None:
        bars = _make_bars(100)
        df_pd = bars.to_pandas()
        result = compute_standard_indicators(df_pd)
        macd_cols = [c for c in result.columns if "MACD" in c.upper()]
        assert len(macd_cols) > 0

    def test_bollinger_present(self) -> None:
        bars = _make_bars(100)
        df_pd = bars.to_pandas()
        result = compute_standard_indicators(df_pd)
        bb_cols = [c for c in result.columns if "BB" in c.upper()]
        assert len(bb_cols) > 0


class TestPluginIntegration:
    def test_taifex_plugin_columns(self) -> None:
        bars = _make_bars(50)
        plugin = TaifexFeaturePlugin()
        result = plugin.compute(bars)
        assert "institutional_net" in result.columns
        assert "put_call_ratio" in result.columns
        assert "volatility_index" in result.columns
        assert "days_to_settlement" in result.columns
        assert "margin_events" in result.columns

    def test_plugin_registration(self) -> None:
        store = FeatureStore()
        plugin = TaifexFeaturePlugin()
        store.register_plugin(plugin)
        bars = _make_bars(50)
        result = store.compute_features(bars)
        assert "institutional_net" in result.columns

    def test_plugin_error_isolation(self) -> None:
        class BadPlugin(FeaturePlugin):
            def compute(self, bars: pl.DataFrame) -> pl.DataFrame:
                raise RuntimeError("plugin exploded")
            def required_columns(self) -> list[str]:
                return ["timestamp"]

        store = FeatureStore()
        store.register_plugin(BadPlugin())
        bars = _make_bars(50)
        result = store.compute_features(bars)
        assert len(result) == len(bars)


class TestParquetStorage:
    def test_round_trip(self, tmp_path: Path) -> None:
        store = FeatureStore()
        bars = _make_bars(50)
        features = store.compute_features(bars)
        parquet_path = tmp_path / "features.parquet"
        store.save_parquet(features, parquet_path)
        loaded = store.load_parquet(parquet_path)
        assert loaded.shape == features.shape


class TestCache:
    def test_cache_hit(self) -> None:
        store = FeatureStore(cache_size=4)
        bars = _make_bars(50)
        result1 = store.compute_features(bars)
        result2 = store.compute_features(bars)
        assert result1.shape == result2.shape

    def test_cache_invalidation(self) -> None:
        store = FeatureStore(cache_size=4)
        bars = _make_bars(50)
        store.compute_features(bars)
        store.invalidate_cache()
        assert len(store._cache) == 0
