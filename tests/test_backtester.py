"""Tests for BacktestRunner with synthetic data."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from src.adapters.taifex import TaifexAdapter
from src.core.types import PyramidConfig
from src.simulator.backtester import BacktestRunner
from src.simulator.fill_model import ClosePriceFillModel, OpenPriceFillModel


@pytest.fixture
def config() -> PyramidConfig:
    return PyramidConfig(max_loss=200_000.0)


@pytest.fixture
def adapter() -> TaifexAdapter:
    return TaifexAdapter()


def _make_bars(n: int = 50, base: float = 20000.0) -> list[dict[str, object]]:
    bars: list[dict[str, object]] = []
    for i in range(n):
        p = base + i * 10
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


def _make_timestamps(n: int = 50) -> list[datetime]:
    return [datetime(2024, 1, 2, 9, 0, tzinfo=UTC) + timedelta(days=i) for i in range(n)]


class TestBacktestRunner:
    def test_run_returns_result(
        self, config: PyramidConfig, adapter: TaifexAdapter
    ) -> None:
        bars = _make_bars()
        ts = _make_timestamps()
        runner = BacktestRunner(config, adapter)
        result = runner.run(bars, timestamps=ts)
        assert len(result.equity_curve) > 0
        assert len(result.drawdown_series) > 0
        assert isinstance(result.metrics, dict)

    def test_equity_curve_starts_at_initial(
        self, config: PyramidConfig, adapter: TaifexAdapter
    ) -> None:
        bars = _make_bars(10)
        runner = BacktestRunner(config, adapter, initial_equity=1_000_000.0)
        result = runner.run(bars)
        assert result.equity_curve[0] == 1_000_000.0

    def test_trade_log_populated(
        self, config: PyramidConfig, adapter: TaifexAdapter
    ) -> None:
        bars = _make_bars()
        ts = _make_timestamps()
        runner = BacktestRunner(config, adapter)
        result = runner.run(bars, timestamps=ts)
        assert isinstance(result.trade_log, list)

    def test_metrics_contain_standard_keys(
        self, config: PyramidConfig, adapter: TaifexAdapter
    ) -> None:
        bars = _make_bars()
        runner = BacktestRunner(config, adapter)
        result = runner.run(bars)
        expected_keys = {"sharpe", "sortino", "calmar", "max_drawdown_pct", "win_rate"}
        assert expected_keys.issubset(result.metrics.keys())


class TestFillModels:
    def test_close_price_fill_slippage(self) -> None:
        from src.core.types import Order
        order = Order(
            order_type="market", side="buy", symbol="TX",
            contract_type="large", lots=1.0, price=None,
            stop_price=None, reason="entry",
        )
        bar = {"open": 20000.0, "high": 20050.0, "low": 19950.0, "close": 20010.0}
        ts = datetime(2024, 1, 2, 9, 0, tzinfo=UTC)
        model = ClosePriceFillModel(slippage_points=5.0)
        fill = model.simulate(order, bar, ts)
        assert fill.fill_price == 20015.0

    def test_open_price_fill(self) -> None:
        from src.core.types import Order
        order = Order(
            order_type="market", side="sell", symbol="TX",
            contract_type="large", lots=1.0, price=None,
            stop_price=None, reason="exit",
        )
        bar = {"open": 20000.0, "high": 20050.0, "low": 19950.0, "close": 20010.0}
        ts = datetime(2024, 1, 2, 9, 0, tzinfo=UTC)
        model = OpenPriceFillModel(slippage_points=3.0)
        fill = model.simulate(order, bar, ts)
        assert fill.fill_price == 19997.0
