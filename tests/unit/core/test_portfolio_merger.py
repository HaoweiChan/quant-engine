"""Unit tests for PortfolioMerger."""
from __future__ import annotations

import pytest

from src.core.portfolio_merger import PortfolioMerger, PortfolioMergerInput


@pytest.fixture
def merger() -> PortfolioMerger:
    return PortfolioMerger(initial_capital=1_000_000.0)


def _make_input(slug: str, returns: list[float], weight: float = 1.0) -> PortfolioMergerInput:
    return PortfolioMergerInput(daily_returns=returns, strategy_slug=slug, weight=weight)


class TestMerge:
    def test_equal_weights_two_strategies(self, merger: PortfolioMerger) -> None:
        a = _make_input("a", [0.01, -0.005, 0.02], weight=0.5)
        b = _make_input("b", [0.005, 0.01, -0.01], weight=0.5)
        result = merger.merge([a, b])
        assert len(result.merged_daily_returns) == 3
        assert abs(result.merged_daily_returns[0] - 0.0075) < 1e-9
        assert abs(result.merged_daily_returns[1] - 0.0025) < 1e-9
        assert abs(result.merged_daily_returns[2] - 0.005) < 1e-9

    def test_custom_weights_normalized(self, merger: PortfolioMerger) -> None:
        a = _make_input("a", [0.10], weight=2.0)
        b = _make_input("b", [0.20], weight=3.0)
        result = merger.merge([a, b])
        expected = 0.10 * (2.0 / 5.0) + 0.20 * (3.0 / 5.0)
        assert abs(result.merged_daily_returns[0] - expected) < 1e-9

    def test_unequal_lengths_padded(self, merger: PortfolioMerger) -> None:
        a = _make_input("a", [0.01, 0.02, 0.03], weight=0.5)
        b = _make_input("b", [0.01], weight=0.5)
        result = merger.merge([a, b])
        assert len(result.merged_daily_returns) == 3
        # Day 2: 0.5 * 0.02 + 0.5 * 0.0 = 0.01
        assert abs(result.merged_daily_returns[1] - 0.01) < 1e-9

    def test_single_strategy_passthrough(self, merger: PortfolioMerger) -> None:
        a = _make_input("a", [0.01, -0.01])
        result = merger.merge([a])
        assert result.merged_daily_returns == [0.01, -0.01]

    def test_empty_returns_raises(self, merger: PortfolioMerger) -> None:
        a = _make_input("a", [])
        b = _make_input("b", [0.01])
        with pytest.raises(ValueError, match="Empty"):
            merger.merge([a, b])

    def test_no_inputs_raises(self, merger: PortfolioMerger) -> None:
        with pytest.raises(ValueError):
            merger.merge([])

    def test_equity_curve_compounds(self, merger: PortfolioMerger) -> None:
        a = _make_input("a", [0.01, 0.01])
        result = merger.merge([a])
        assert result.merged_equity_curve[0] == 1_000_000.0
        assert abs(result.merged_equity_curve[1] - 1_010_000.0) < 0.01
        assert abs(result.merged_equity_curve[2] - 1_020_100.0) < 0.01


class TestCorrelation:
    def test_two_identical_strategies(self, merger: PortfolioMerger) -> None:
        rets = [0.01, -0.01, 0.02, -0.005]
        a = _make_input("a", rets)
        b = _make_input("b", rets)
        result = merger.merge([a, b])
        assert len(result.correlation_matrix) == 2
        assert abs(result.correlation_matrix[0][1] - 1.0) < 1e-6

    def test_three_strategies(self, merger: PortfolioMerger) -> None:
        a = _make_input("a", [0.01, -0.01, 0.02])
        b = _make_input("b", [0.02, -0.02, 0.04])
        c = _make_input("c", [-0.01, 0.01, -0.02])
        result = merger.merge([a, b, c])
        assert len(result.correlation_matrix) == 3
        assert len(result.correlation_matrix[0]) == 3


class TestMetrics:
    def test_metrics_keys_present(self, merger: PortfolioMerger) -> None:
        a = _make_input("a", [0.01, -0.005, 0.02, 0.003, -0.01])
        result = merger.merge([a])
        expected_keys = {
            "total_return", "sharpe", "sortino", "max_drawdown_pct",
            "calmar", "annual_return", "annual_vol", "n_days",
        }
        assert expected_keys == set(result.metrics.keys())

    def test_zero_variance_safe(self, merger: PortfolioMerger) -> None:
        a = _make_input("a", [0.0, 0.0, 0.0])
        result = merger.merge([a])
        assert result.metrics["sharpe"] == 0.0
        assert result.metrics["sortino"] == 0.0
