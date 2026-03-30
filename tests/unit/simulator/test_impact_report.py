"""Tests for BacktestResult impact report and extended metrics."""
from __future__ import annotations

from datetime import datetime

import pytest

from src.simulator.backtester import BacktestRunner
from src.simulator.types import Fill, ImpactReport


def _make_fill(
    side: str = "buy",
    lots: float = 2.0,
    fill_price: float = 20001.0,
    market_impact: float = 1.5,
    spread_cost: float = 0.5,
    commission_cost: float = 0.0,
    latency_ms: float = 10.0,
    is_partial: bool = False,
) -> Fill:
    return Fill(
        order_type="market", side=side, symbol="TX",
        lots=lots, fill_price=fill_price, slippage=1.0,
        timestamp=datetime(2024, 6, 1), reason="entry",
        market_impact=market_impact, spread_cost=spread_cost,
        commission_cost=commission_cost,
        latency_ms=latency_ms, fill_qty=lots, remaining_qty=0.0,
        is_partial=is_partial,
    )


class TestImpactReport:
    def test_report_totals(self) -> None:
        fills = [
            _make_fill(market_impact=2.0, spread_cost=0.5, latency_ms=10.0),
            _make_fill(market_impact=3.0, spread_cost=1.0, latency_ms=20.0),
        ]
        equity_curve = [2_000_000.0, 2_001_000.0, 2_002_000.0]
        report = BacktestRunner._build_impact_report(fills, equity_curve)
        assert report.total_market_impact == pytest.approx(5.0)
        assert report.total_spread_cost == pytest.approx(1.5)
        assert report.total_commission_cost == pytest.approx(0.0)
        assert report.avg_latency_ms == pytest.approx(15.0)

    def test_naive_vs_realistic_pnl(self) -> None:
        fills = [_make_fill(market_impact=100.0, spread_cost=50.0)]
        equity_curve = [2_000_000.0, 2_000_500.0]
        report = BacktestRunner._build_impact_report(fills, equity_curve)
        assert report.realistic_pnl == pytest.approx(500.0)
        assert report.naive_pnl == pytest.approx(500.0 + 100.0 + 50.0)
        assert report.pnl_ratio == pytest.approx(500.0 / 650.0)

    def test_partial_fill_count(self) -> None:
        fills = [
            _make_fill(is_partial=False),
            _make_fill(is_partial=True),
            _make_fill(is_partial=True),
        ]
        equity_curve = [2_000_000.0, 2_001_000.0]
        report = BacktestRunner._build_impact_report(fills, equity_curve)
        assert report.partial_fill_count == 2

    def test_per_trade_breakdown_count(self) -> None:
        fills = [_make_fill(), _make_fill(), _make_fill()]
        equity_curve = [2_000_000.0, 2_001_000.0]
        report = BacktestRunner._build_impact_report(fills, equity_curve)
        assert len(report.per_trade_impact_breakdown) == 3
        assert "market_impact" in report.per_trade_impact_breakdown[0]

    def test_no_trades_zero_report(self) -> None:
        equity_curve = [2_000_000.0, 2_000_000.0]
        report = BacktestRunner._build_impact_report([], equity_curve)
        assert report.total_market_impact == 0.0
        assert report.total_spread_cost == 0.0
        assert report.total_commission_cost == 0.0
        assert report.avg_latency_ms == 0.0
        assert report.partial_fill_count == 0
        assert report.pnl_ratio == 1.0


class TestMetricsExtension:
    def test_metrics_include_impact_fields(self) -> None:
        fills = [_make_fill(market_impact=2.0, spread_cost=1.0, latency_ms=15.0)]
        equity_curve = [2_000_000.0, 2_001_000.0]
        report = BacktestRunner._build_impact_report(fills, equity_curve)
        metrics: dict[str, float] = {}
        metrics["total_market_impact"] = report.total_market_impact
        metrics["total_spread_cost"] = report.total_spread_cost
        metrics["total_commission_cost"] = report.total_commission_cost
        metrics["avg_latency_ms"] = report.avg_latency_ms
        metrics["partial_fill_count"] = float(report.partial_fill_count)
        assert metrics["total_market_impact"] == pytest.approx(2.0)
        assert metrics["total_spread_cost"] == pytest.approx(1.0)
        assert metrics["total_commission_cost"] == pytest.approx(0.0)
        assert metrics["avg_latency_ms"] == pytest.approx(15.0)
        assert metrics["partial_fill_count"] == 0.0


class TestImpactReportDataclass:
    def test_pnl_ratio_one_when_no_pnl(self) -> None:
        report = ImpactReport(
            naive_pnl=0.0, realistic_pnl=0.0, pnl_ratio=1.0,
            total_market_impact=0.0, total_spread_cost=0.0,
            total_commission_cost=0.0,
            avg_latency_ms=0.0, partial_fill_count=0,
            per_trade_impact_breakdown=[],
        )
        assert report.pnl_ratio == 1.0
