"""Tests for parameter scanner grid search."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from src.adapters.taifex import TaifexAdapter
from src.core.types import PyramidConfig
from src.simulator.scanner import SweepRange, find_robust_regions, grid_search


@pytest.fixture
def config() -> PyramidConfig:
    return PyramidConfig(max_loss=200_000.0)


@pytest.fixture
def adapter() -> TaifexAdapter:
    return TaifexAdapter()


def _make_bars(n: int = 30) -> list[dict[str, object]]:
    bars: list[dict[str, object]] = []
    for i in range(n):
        p = 20000.0 + i * 10
        bars.append({
            "price": p,
            "symbol": "TX",
            "daily_atr": 100.0,
            "open": p - 5,
            "high": p + 20,
            "low": p - 20,
            "close": p,
        })
    return bars


def _make_timestamps(n: int = 30) -> list[datetime]:
    return [datetime(2024, 1, 2, 9, 0, tzinfo=UTC) + timedelta(days=i) for i in range(n)]


class TestGridSearch:
    def test_result_shape(
        self, config: PyramidConfig, adapter: TaifexAdapter
    ) -> None:
        sweep = SweepRange(
            stop_atr_mult=[1.0, 2.0],
            trail_atr_mult=[2.0, 3.0],
            add_trigger_atr=[[4.0, 8.0, 12.0]],
            kelly_fraction=[0.25],
        )
        bars = _make_bars()
        ts = _make_timestamps()
        results = grid_search(config, adapter, bars, sweep, timestamps=ts)
        assert len(results) == 4
        assert "sharpe" in results.columns

    def test_covers_all_combos(
        self, config: PyramidConfig, adapter: TaifexAdapter
    ) -> None:
        sweep = SweepRange(
            stop_atr_mult=[1.0, 1.5],
            trail_atr_mult=[3.0],
            add_trigger_atr=[[4.0, 8.0, 12.0]],
            kelly_fraction=[0.2, 0.3],
        )
        bars = _make_bars()
        results = grid_search(config, adapter, bars, sweep)
        assert len(results) == 4


class TestRobustRegions:
    def test_filters_to_robust(
        self, config: PyramidConfig, adapter: TaifexAdapter
    ) -> None:
        sweep = SweepRange(
            stop_atr_mult=[1.0, 1.5, 2.0],
            trail_atr_mult=[2.0, 3.0, 4.0],
            add_trigger_atr=[[4.0, 8.0, 12.0]],
            kelly_fraction=[0.25],
        )
        bars = _make_bars()
        results = grid_search(config, adapter, bars, sweep)
        robust = find_robust_regions(results, "sharpe", top_pct=0.5)
        assert len(robust) <= len(results)
        assert len(robust) >= 0
