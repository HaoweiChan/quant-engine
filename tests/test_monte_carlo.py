"""Tests for Monte Carlo runner."""
from __future__ import annotations

import pytest

from src.adapters.taifex import TaifexAdapter
from src.core.types import PyramidConfig
from src.simulator.monte_carlo import run_monte_carlo
from src.simulator.types import PathConfig


@pytest.fixture
def config() -> PyramidConfig:
    return PyramidConfig(max_loss=200_000.0)


@pytest.fixture
def adapter() -> TaifexAdapter:
    return TaifexAdapter()


class TestMonteCarloRunner:
    def test_result_structure(
        self, config: PyramidConfig, adapter: TaifexAdapter
    ) -> None:
        path_cfg = PathConfig(n_bars=30, seed=42)
        result = run_monte_carlo(3, config, adapter, path_cfg)
        assert len(result.terminal_pnl_distribution) == 3
        assert len(result.max_drawdown_distribution) == 3
        assert len(result.sharpe_distribution) == 3

    def test_percentiles_ordered(
        self, config: PyramidConfig, adapter: TaifexAdapter
    ) -> None:
        path_cfg = PathConfig(n_bars=30, seed=42)
        result = run_monte_carlo(10, config, adapter, path_cfg)
        assert result.percentiles["P5"] <= result.percentiles["P25"]
        assert result.percentiles["P25"] <= result.percentiles["P50"]
        assert result.percentiles["P50"] <= result.percentiles["P75"]
        assert result.percentiles["P75"] <= result.percentiles["P95"]

    def test_win_rate_bounded(
        self, config: PyramidConfig, adapter: TaifexAdapter
    ) -> None:
        path_cfg = PathConfig(n_bars=30, seed=42)
        result = run_monte_carlo(5, config, adapter, path_cfg)
        assert 0.0 <= result.win_rate <= 1.0

    def test_ruin_probability_bounded(
        self, config: PyramidConfig, adapter: TaifexAdapter
    ) -> None:
        path_cfg = PathConfig(n_bars=30, seed=42)
        result = run_monte_carlo(5, config, adapter, path_cfg)
        assert 0.0 <= result.ruin_probability <= 1.0
