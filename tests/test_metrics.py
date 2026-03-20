"""Tests for performance metrics against known values."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from src.simulator.metrics import (
    avg_holding_period,
    avg_win_loss,
    calmar_ratio,
    max_drawdown_abs,
    max_drawdown_pct,
    monthly_returns,
    profit_factor,
    sharpe_ratio,
    sortino_ratio,
    trade_count,
    win_rate,
    yearly_returns,
)
from src.simulator.types import Fill


def _fill(side: str, price: float, ts: datetime, lots: float = 1.0) -> Fill:
    return Fill(
        order_type="market", side=side, symbol="TX",
        lots=lots, fill_price=price, slippage=0.0,
        timestamp=ts, reason="test",
    )


class TestSharpe:
    def test_flat_equity(self) -> None:
        assert sharpe_ratio([100.0] * 10) == 0.0

    def test_positive_returns(self) -> None:
        curve = [100.0 + i * 1.0 for i in range(252)]
        s = sharpe_ratio(curve)
        assert s > 0

    def test_single_point(self) -> None:
        assert sharpe_ratio([100.0]) == 0.0


class TestSortino:
    def test_no_downside(self) -> None:
        curve = [100.0 + i for i in range(50)]
        assert sortino_ratio(curve) == 0.0

    def test_with_downside(self) -> None:
        curve = [100.0, 102.0, 99.0, 101.0, 98.0, 103.0]
        s = sortino_ratio(curve)
        assert isinstance(s, float)


class TestCalmar:
    def test_no_drawdown(self) -> None:
        curve = [100.0 + i for i in range(50)]
        assert calmar_ratio(curve) == 0.0

    def test_with_drawdown(self) -> None:
        curve = [100.0, 110.0, 105.0, 115.0, 108.0, 120.0]
        c = calmar_ratio(curve)
        assert c > 0


class TestMaxDrawdown:
    def test_known_drawdown_abs(self) -> None:
        curve = [100.0, 110.0, 90.0, 95.0]
        assert max_drawdown_abs(curve) == pytest.approx(20.0)

    def test_known_drawdown_pct(self) -> None:
        curve = [100.0, 110.0, 90.0, 95.0]
        assert max_drawdown_pct(curve) == pytest.approx(20.0 / 110.0)


class TestWinRateAndProfitFactor:
    def test_all_winners(self) -> None:
        ts = datetime(2024, 1, 2, 9, 0, tzinfo=UTC)
        log = [
            _fill("buy", 100.0, ts),
            _fill("sell", 110.0, ts + timedelta(hours=1)),
        ]
        assert win_rate(log) == 1.0
        assert profit_factor(log) == float("inf")

    def test_mixed(self) -> None:
        ts = datetime(2024, 1, 2, 9, 0, tzinfo=UTC)
        log = [
            _fill("buy", 100.0, ts),
            _fill("sell", 110.0, ts + timedelta(hours=1)),
            _fill("buy", 100.0, ts + timedelta(hours=2)),
            _fill("sell", 90.0, ts + timedelta(hours=3)),
        ]
        assert win_rate(log) == 0.5
        avg_w, avg_l = avg_win_loss(log)
        assert avg_w > 0
        assert avg_l < 0


class TestTradeCountAndHolding:
    def test_count(self) -> None:
        ts = datetime(2024, 1, 2, tzinfo=UTC)
        log = [
            _fill("buy", 100.0, ts),
            _fill("sell", 110.0, ts + timedelta(hours=2)),
        ]
        assert trade_count(log) == 1

    def test_avg_holding(self) -> None:
        ts = datetime(2024, 1, 2, tzinfo=UTC)
        log = [
            _fill("buy", 100.0, ts),
            _fill("sell", 110.0, ts + timedelta(hours=4)),
        ]
        assert avg_holding_period(log) == pytest.approx(4.0)


class TestPeriodReturns:
    def test_monthly(self) -> None:
        curve = [100.0, 110.0, 120.0]
        ts = [
            datetime(2024, 1, 15, tzinfo=UTC),
            datetime(2024, 2, 15, tzinfo=UTC),
            datetime(2024, 3, 15, tzinfo=UTC),
        ]
        m = monthly_returns(curve, ts)
        assert len(m) >= 1

    def test_yearly(self) -> None:
        curve = [100.0, 120.0]
        ts = [
            datetime(2024, 6, 15, tzinfo=UTC),
            datetime(2025, 6, 15, tzinfo=UTC),
        ]
        y = yearly_returns(curve, ts)
        assert len(y) >= 1
