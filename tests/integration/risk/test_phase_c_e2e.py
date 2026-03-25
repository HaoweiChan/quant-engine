"""Integration test: position exceeding VaR limit → halted by Risk Monitor.
Exercises the Phase C portfolio-risk-var-engine stack end-to-end.
"""
from __future__ import annotations

import random
from datetime import datetime

import pytest

from src.core.types import (
    AccountState,
    Position,
    RiskAction,
    StressScenario,
    VaRResult,
)
from src.pipeline.config import RiskConfig
from src.risk.monitor import RiskMonitor
from src.risk.portfolio import PortfolioRiskEngine
from src.risk.var_engine import VaREngine


def _pos(
    symbol: str = "TX", lots: float = 1.0, price: float = 20000.0,
    direction: str = "long",
) -> Position:
    return Position(
        entry_price=price, lots=lots, contract_type=symbol,
        stop_level=price - 100, pyramid_level=1,
        entry_timestamp=datetime(2024, 1, 1), direction=direction,
    )


def _account(
    equity: float = 1_000_000, margin_used: float = 200_000,
    positions: list[Position] | None = None,
    drawdown_pct: float = 0.0,
) -> AccountState:
    pos = positions if positions is not None else [_pos()]
    return AccountState(
        equity=equity, unrealized_pnl=0.0, realized_pnl=0.0,
        margin_used=margin_used,
        margin_available=equity - margin_used,
        margin_ratio=equity / max(margin_used, 1),
        drawdown_pct=drawdown_pct, positions=pos,
        timestamp=datetime.now(),
    )


def _returns(n: int = 60, vol: float = 0.01) -> list[float]:
    random.seed(42)
    return [random.gauss(0, vol) for _ in range(n)]


class TestPhaseCEndToEnd:
    """Full stack: PortfolioRiskEngine → RiskMonitor → VaR breach halts entries."""

    def test_var_breach_halts_via_monitor(self):
        """Large position with tight VaR limit → HALT_NEW_ENTRIES."""
        config = RiskConfig(
            portfolio_risk_enabled=True,
            max_var_pct=0.001,  # very tight: 0.1% of equity
        )
        var_engine = VaREngine(lookback_days=252)
        portfolio = PortfolioRiskEngine(var_engine=var_engine)
        monitor = RiskMonitor(config=config, portfolio_risk=portfolio)
        returns = {"TX": _returns(60, vol=0.02)}
        prices = {"TX": 20000.0}
        monitor.update_market_data(returns, prices)
        positions = [_pos(lots=10, price=20000)]
        account = _account(
            equity=1_000_000, margin_used=500_000, positions=positions,
        )
        action = monitor.check(account)
        assert action == RiskAction.HALT_NEW_ENTRIES
        assert any(e.trigger == "var_limit_breach" for e in monitor.events)

    def test_healthy_portfolio_passes(self):
        """Moderate position with generous VaR limit → NORMAL."""
        config = RiskConfig(
            portfolio_risk_enabled=True,
            max_var_pct=0.50,  # 50% generous limit
        )
        portfolio = PortfolioRiskEngine()
        monitor = RiskMonitor(config=config, portfolio_risk=portfolio)
        returns = {"TX": _returns(60, vol=0.01)}
        prices = {"TX": 20000.0}
        monitor.update_market_data(returns, prices)
        account = _account(equity=1_000_000, margin_used=200_000)
        action = monitor.check(account)
        assert action == RiskAction.NORMAL

    def test_stress_scenarios_full_pipeline(self):
        """Run stress scenarios through PortfolioRiskEngine and verify results."""
        engine = PortfolioRiskEngine()
        returns = {"TX": _returns(60, vol=0.015)}
        scenarios = [
            StressScenario(name="margin_2x", margin_multiplier=2.0),
            StressScenario(name="vol_3x", volatility_multiplier=3.0),
            StressScenario(name="corr_breakdown", correlation_override=1.0),
        ]
        account = _account(equity=500_000, margin_used=300_000)
        summary = engine.get_risk_summary(
            [_pos(lots=5)], returns, account,
            prices={"TX": 20000.0},
            stress_scenarios=scenarios,
        )
        assert len(summary.stress_results) == 3
        margin_2x = summary.stress_results[0]
        assert margin_2x.margin_call is True
        assert margin_2x.shortfall > 0
        vol_3x = summary.stress_results[1]
        assert vol_3x.stressed_var > summary.var.var_99_1d

    def test_var_computation_accuracy(self):
        """Verify VaR engine produces sensible numbers through full stack."""
        engine = PortfolioRiskEngine()
        returns = {"TX": _returns(100, vol=0.015)}
        account = _account(equity=1_000_000)
        summary = engine.get_risk_summary(
            [_pos(lots=2, price=20000)], returns, account,
            prices={"TX": 20000.0},
        )
        var = summary.var
        assert var.var_99_1d > 0
        assert var.var_95_1d > 0
        assert var.var_99_1d > var.var_95_1d
        assert var.var_99_10d > var.var_99_1d
        assert var.expected_shortfall_99 > var.var_99_1d
        assert "TX" in var.position_var
        assert summary.portfolio_beta != 0.0

    def test_historical_var_crosscheck(self):
        """HVaR vs parametric divergence detection works end-to-end."""
        var_engine = VaREngine()
        positions = [_pos(lots=5, price=20000)]
        returns = {"TX": _returns(200, vol=0.02)}
        prices = {"TX": 20000.0}
        parametric = var_engine.compute(positions, returns, prices)
        historical = var_engine.compute_historical(positions, returns, prices)
        diverged, ratio = var_engine.check_divergence(
            parametric.var_99_1d, historical,
        )
        assert isinstance(diverged, bool)
        assert ratio >= 0.0
