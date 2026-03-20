"""Tests for bar builder aggregation and ATR computation."""
from __future__ import annotations

from datetime import UTC, datetime

import polars as pl

from src.data.bar_builder import (
    aggregate_bars,
    build_all_timeframes,
    compute_atr,
    compute_multi_timeframe_atr,
)


def _make_minute_data(n_minutes: int = 300, base_price: float = 20000.0) -> pl.DataFrame:
    from datetime import timedelta
    timestamps = [
        datetime(2024, 1, 2, 8, 45, tzinfo=UTC) + timedelta(minutes=i)
        for i in range(n_minutes)
    ]
    prices = [base_price + (i % 50) - 25 for i in range(n_minutes)]
    return pl.DataFrame({
        "timestamp": timestamps,
        "open": prices,
        "high": [p + 5 for p in prices],
        "low": [p - 5 for p in prices],
        "close": [p + 2 for p in prices],
        "volume": [100] * n_minutes,
    })


class TestAggregation:
    def test_5m_aggregation(self) -> None:
        df = _make_minute_data(30)
        result = aggregate_bars(df, "5m")
        assert len(result) == 6
        assert "open" in result.columns

    def test_1h_aggregation(self) -> None:
        df = _make_minute_data(120)
        result = aggregate_bars(df, "1H")
        assert len(result) >= 2

    def test_4h_aggregation(self) -> None:
        df = _make_minute_data(480)
        result = aggregate_bars(df, "4H")
        assert len(result) >= 2

    def test_daily_aggregation(self) -> None:
        df = _make_minute_data(300)
        result = aggregate_bars(df, "daily")
        assert len(result) >= 1

    def test_ohlcv_correctness(self) -> None:
        df = pl.DataFrame({
            "timestamp": [
                datetime(2024, 1, 2, 9, 0, tzinfo=UTC),
                datetime(2024, 1, 2, 9, 1, tzinfo=UTC),
                datetime(2024, 1, 2, 9, 2, tzinfo=UTC),
                datetime(2024, 1, 2, 9, 3, tzinfo=UTC),
                datetime(2024, 1, 2, 9, 4, tzinfo=UTC),
            ],
            "open": [100.0, 102.0, 101.0, 103.0, 104.0],
            "high": [105.0, 106.0, 104.0, 107.0, 108.0],
            "low": [99.0, 100.0, 98.0, 101.0, 102.0],
            "close": [102.0, 101.0, 103.0, 104.0, 106.0],
            "volume": [10, 20, 15, 25, 30],
        })
        result = aggregate_bars(df, "5m")
        assert len(result) == 1
        row = result.row(0, named=True)
        assert row["open"] == 100.0
        assert row["high"] == 108.0
        assert row["low"] == 98.0
        assert row["close"] == 106.0
        assert row["volume"] == 100

    def test_empty_input(self) -> None:
        df = pl.DataFrame({
            "timestamp": [],
            "open": [],
            "high": [],
            "low": [],
            "close": [],
            "volume": [],
        }).cast({"timestamp": pl.Datetime})
        result = aggregate_bars(df, "5m")
        assert result.is_empty()


class TestBuildAllTimeframes:
    def test_returns_all_timeframes(self) -> None:
        df = _make_minute_data(1500)
        result = build_all_timeframes(df)
        assert "5m" in result
        assert "1H" in result
        assert "4H" in result
        assert "daily" in result


class TestATR:
    def test_compute_atr_basic(self) -> None:
        df = _make_minute_data(300)
        bars_5m = aggregate_bars(df, "5m")
        atr = compute_atr(bars_5m, period=14)
        assert len(atr) == len(bars_5m)
        non_null = atr.drop_nulls()
        assert len(non_null) > 0

    def test_multi_timeframe_atr_keys(self) -> None:
        df = _make_minute_data(1500)
        bars = build_all_timeframes(df)
        atr_dict = compute_multi_timeframe_atr(bars)
        assert "daily" in atr_dict
        assert "hourly" in atr_dict
        assert "5m" in atr_dict

    def test_short_data_returns_none(self) -> None:
        df = _make_minute_data(10)
        bars = build_all_timeframes(df)
        atr_dict = compute_multi_timeframe_atr(bars)
        assert atr_dict.get("daily") is None
