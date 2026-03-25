"""Tests for PortfolioRiskEngine and enhanced PreTradeRiskCheck."""
from __future__ import annotations

import random
from datetime import datetime

import pytest

from src.core.types import (
    AccountState,
    Order,
    Position,
    PreTradeRiskConfig,
    StressScenario,
    VaRResult,
)
from src.risk.portfolio import PortfolioRiskEngine
from src.risk.pre_trade import PreTradeRiskCheck
from src.risk.var_engine import VaREngine


def _pos(
    symbol: str = "TX",
    lots: float = 1.0,
    price: float = 20000.0,
    direction: str = "long",
) -> Position:
    return Position(
        entry_price=price, lots=lots, contract_type=symbol,
        stop_level=price - 100, pyramid_level=1,
        entry_timestamp=datetime(2024, 1, 1), direction=direction,
    )


def _account(
    equity: float = 1_000_000, margin_used: float = 200_000,
) -> AccountState:
    return AccountState(
        equity=equity, unrealized_pnl=0.0, realized_pnl=0.0,
        margin_used=margin_used,
        margin_available=equity - margin_used,
        margin_ratio=equity / max(margin_used, 1),
        drawdown_pct=0.0, positions=[_pos()],
        timestamp=datetime.now(),
    )


def _order(
    symbol: str = "TX", lots: float = 1.0, side: str = "buy",
) -> Order:
    return Order(
        symbol=symbol, lots=lots, side=side, order_type="market",
        contract_type=symbol, price=None, stop_price=None, reason="test",
    )


def _returns(n: int = 60, vol: float = 0.01) -> list[float]:
    random.seed(42)
    return [random.gauss(0, vol) for _ in range(n)]


class TestPortfolioRiskEngine:
    """Task 3.1: get_risk_summary returns VaR + beta + concentration."""

    def test_risk_summary_has_all_fields(self):
        engine = PortfolioRiskEngine()
        positions = [_pos()]
        returns = {"TX": _returns(60)}
        account = _account()
        summary = engine.get_risk_summary(
            positions, returns, account, prices={"TX": 20000.0},
        )
        assert summary.var is not None
        assert summary.var.var_99_1d > 0
        assert isinstance(summary.portfolio_beta, float)
        assert "TX" in summary.concentration
        assert len(summary.stress_results) == 3  # default scenarios

    def test_empty_portfolio(self):
        engine = PortfolioRiskEngine()
        account = _account(equity=1_000_000, margin_used=0)
        summary = engine.get_risk_summary([], {}, account)
        assert summary.var.var_99_1d == 0.0
        assert summary.portfolio_beta == 0.0


class TestBetaTracking:
    """Task 3.3: portfolio beta vs benchmark."""

    def test_single_tx_beta_approx_one(self):
        """Single long TX futures on TAIEX → beta ≈ 1.0."""
        engine = PortfolioRiskEngine(benchmark_symbol="TAIEX")
        # No benchmark returns → implied beta for index futures
        beta = engine.compute_beta([_pos("TX")], {}, {"TX": 20000.0})
        assert beta == pytest.approx(1.0, abs=0.01)

    def test_short_position_negative_beta(self):
        engine = PortfolioRiskEngine(benchmark_symbol="TAIEX")
        beta = engine.compute_beta(
            [_pos("TX", direction="short")], {}, {"TX": 20000.0},
        )
        assert beta == pytest.approx(-1.0, abs=0.01)

    def test_beta_with_returns(self):
        """When enough benchmark returns exist, compute actual beta."""
        random.seed(123)
        benchmark = [random.gauss(0, 0.01) for _ in range(60)]
        # Asset highly correlated with benchmark
        asset = [b + random.gauss(0, 0.001) for b in benchmark]
        engine = PortfolioRiskEngine(benchmark_symbol="TAIEX")
        beta = engine.compute_beta(
            [_pos("TX")], {"TX": asset, "TAIEX": benchmark}, {"TX": 20000.0},
        )
        assert 0.8 < beta < 1.2  # should be close to 1.0


class TestConcentration:
    """Task 3.3 supplement: concentration tracking."""

    def test_single_position_concentration(self):
        engine = PortfolioRiskEngine()
        conc = engine.compute_concentration(
            [_pos("TX", lots=2, price=20000)],
            equity=1_000_000, prices={"TX": 20000.0},
        )
        assert conc["TX"] == pytest.approx(0.04)

    def test_multiple_positions(self):
        engine = PortfolioRiskEngine()
        positions = [_pos("TX", lots=2), _pos("MX", lots=10, price=10000)]
        conc = engine.compute_concentration(
            positions, equity=1_000_000, prices={"TX": 20000.0, "MX": 10000.0},
        )
        assert "TX" in conc
        assert "MX" in conc
        assert sum(conc.values()) == pytest.approx(0.14)


class TestStressScenarios:
    """Task 3.4: margin stress testing."""

    def test_margin_doubling_triggers_call(self):
        engine = PortfolioRiskEngine()
        returns = {"TX": _returns(60)}
        account = _account(equity=500_000, margin_used=300_000)
        scenarios = [StressScenario(name="margin_2x", margin_multiplier=2.0)]
        summary = engine.get_risk_summary(
            [_pos()], returns, account, {"TX": 20000.0}, scenarios,
        )
        assert summary.stress_results[0].margin_call is True

    def test_vol_spike_increases_var(self):
        engine = PortfolioRiskEngine()
        returns = {"TX": _returns(60)}
        account = _account()
        normal_summary = engine.get_risk_summary(
            [_pos()], returns, account, {"TX": 20000.0},
            [StressScenario(name="baseline")],
        )
        vol_summary = engine.get_risk_summary(
            [_pos()], returns, account, {"TX": 20000.0},
            [StressScenario(name="vol_3x", volatility_multiplier=3.0)],
        )
        assert (
            vol_summary.stress_results[0].stressed_var
            > normal_summary.stress_results[0].stressed_var
        )


class TestEnhancedPreTrade:
    """Task 3.2: VaR, beta, and concentration limit checks."""

    def _setup_pre_trade_with_portfolio(
        self, config: PreTradeRiskConfig | None = None,
        var_99: float = 30_000, beta: float = 1.0,
    ) -> PreTradeRiskCheck:
        """Create PreTradeRiskCheck wired to a PortfolioRiskEngine with mocked state."""
        portfolio = PortfolioRiskEngine()
        portfolio._last_var = VaRResult(
            var_99_1d=var_99, var_95_1d=20_000,
            var_99_10d=var_99 * 3.16, var_95_10d=20_000 * 3.16,
            expected_shortfall_99=var_99 * 1.1,
            timestamp=datetime.now(),
        )
        portfolio._last_beta = beta
        return PreTradeRiskCheck(config=config, portfolio_risk=portfolio)

    def test_order_within_all_limits(self):
        check = self._setup_pre_trade_with_portfolio(var_99=30_000, beta=1.0)
        result = check.evaluate(
            _order(lots=1), _account(equity=1_000_000, margin_used=200_000),
            {"margin_per_unit": 100_000, "adv": 5000, "price": 20000},
        )
        assert result.approved is True

    def test_var_limit_exceeded(self):
        config = PreTradeRiskConfig(max_var_pct=0.02)
        check = self._setup_pre_trade_with_portfolio(config=config, var_99=30_000)
        result = check.evaluate(
            _order(lots=1), _account(equity=1_000_000),
            {"margin_per_unit": 100_000, "adv": 5000, "price": 20000},
        )
        assert "var_limit_exceeded" in result.violations

    def test_beta_exceeded(self):
        config = PreTradeRiskConfig(max_beta_absolute=1.5)
        check = self._setup_pre_trade_with_portfolio(config=config, beta=2.5)
        result = check.evaluate(
            _order(lots=1), _account(equity=1_000_000),
            {"margin_per_unit": 100_000, "adv": 5000, "price": 20000},
        )
        assert "beta_exceeded" in result.violations

    def test_concentration_exceeded(self):
        config = PreTradeRiskConfig(max_concentration_pct=0.10)
        check = self._setup_pre_trade_with_portfolio(config=config)
        result = check.evaluate(
            _order(lots=100), _account(equity=1_000_000),
            {"margin_per_unit": 50_000, "adv": 50000, "price": 20000},
        )
        assert "concentration_exceeded" in result.violations

    def test_no_portfolio_risk_backwards_compatible(self):
        """Without portfolio risk engine, only legacy checks run."""
        check = PreTradeRiskCheck()
        result = check.evaluate(
            _order(lots=1), _account(equity=1_000_000),
            {"margin_per_unit": 100_000, "adv": 5000},
        )
        assert result.approved is True
        assert "current_var_pct" not in result.risk_metrics

    def test_disabled_approves_all(self):
        config = PreTradeRiskConfig(enabled=False)
        check = self._setup_pre_trade_with_portfolio(config=config, var_99=999_999)
        result = check.evaluate(
            _order(lots=1), _account(), {"margin_per_unit": 100_000, "adv": 5000},
        )
        assert result.approved is True
