"""Tests for roll cost estimation in backtesting."""
from __future__ import annotations

from datetime import date

import pytest

from src.simulator.roll_cost import (
    RollCostEstimate,
    count_settlements_in_range,
    estimate_roll_costs,
    inject_roll_costs_into_metrics,
)


class TestCountSettlements:
    def test_single_month(self) -> None:
        settlements = count_settlements_in_range(date(2024, 1, 1), date(2024, 1, 31))
        assert len(settlements) == 1
        assert settlements[0].month == 1

    def test_multi_month(self) -> None:
        settlements = count_settlements_in_range(date(2024, 1, 1), date(2024, 6, 30))
        assert len(settlements) == 6

    def test_full_year(self) -> None:
        settlements = count_settlements_in_range(date(2024, 1, 1), date(2024, 12, 31))
        assert len(settlements) == 12

    def test_empty_range(self) -> None:
        settlements = count_settlements_in_range(date(2024, 1, 20), date(2024, 1, 25))
        assert len(settlements) <= 1


class TestEstimateRollCosts:
    def test_short_term_zero(self) -> None:
        est = estimate_roll_costs("short_term", date(2024, 1, 1), date(2024, 12, 31))
        assert est.n_rolls == 0
        assert est.total_roll_cost == 0.0

    def test_swing_full_year(self) -> None:
        est = estimate_roll_costs(
            "swing", date(2024, 1, 1), date(2024, 12, 31),
            lots=1.0, point_value=200.0, avg_spread_pts=15.0,
        )
        assert est.n_rolls == 12
        expected_per_roll = 15.0 * 200.0 * 1.0
        assert est.total_roll_cost == pytest.approx(expected_per_roll * 12)
        assert len(est.cost_per_roll) == 12

    def test_medium_term_costs(self) -> None:
        est = estimate_roll_costs(
            "medium_term", date(2024, 3, 1), date(2024, 6, 30),
            lots=2.0, point_value=200.0, avg_spread_pts=10.0,
        )
        assert est.n_rolls >= 3
        assert est.total_roll_cost > 0
        assert all(c == est.cost_per_roll[0] for c in est.cost_per_roll)

    def test_mtx_point_value(self) -> None:
        est = estimate_roll_costs(
            "swing", date(2024, 1, 1), date(2024, 3, 31),
            lots=4.0, point_value=50.0, avg_spread_pts=15.0,
        )
        expected_per_roll = 15.0 * 50.0 * 4.0
        assert est.cost_per_roll[0] == pytest.approx(expected_per_roll)


class TestInjectMetrics:
    def test_adds_roll_fields(self) -> None:
        metrics: dict[str, float] = {"net_pnl": 500_000.0, "sharpe": 1.5}
        result = inject_roll_costs_into_metrics(
            metrics, "swing", date(2024, 1, 1), date(2024, 12, 31),
            lots=1.0, point_value=200.0, avg_spread_pts=15.0,
        )
        assert "roll_count" in result
        assert result["roll_count"] == 12.0
        assert "roll_total_cost" in result
        assert result["roll_total_cost"] > 0
        assert "roll_cost_pct_of_pnl" in result
        assert result["roll_cost_pct_of_pnl"] > 0

    def test_short_term_zero_cost(self) -> None:
        metrics: dict[str, float] = {"net_pnl": 100_000.0}
        result = inject_roll_costs_into_metrics(
            metrics, "short_term", date(2024, 1, 1), date(2024, 12, 31),
        )
        assert result["roll_count"] == 0.0
        assert result["roll_total_cost"] == 0.0
        assert result["roll_cost_pct_of_pnl"] == 0.0
