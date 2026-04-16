"""Tests for Risk Monitor portfolio risk extension (VaR, beta, concentration checks)."""
from __future__ import annotations

import random
from datetime import datetime

from src.core.types import AccountState, Position, RiskAction
from src.pipeline.config import RiskConfig
from src.risk.monitor import RiskMonitor
from src.risk.portfolio import PortfolioRiskEngine


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
) -> AccountState:
    pos = positions if positions is not None else [_pos()]
    return AccountState(
        equity=equity, unrealized_pnl=0.0, realized_pnl=0.0,
        margin_used=margin_used,
        margin_available=equity - margin_used,
        margin_ratio=equity / max(margin_used, 1),
        drawdown_pct=0.0, positions=pos,
        timestamp=datetime.now(),
    )


def _returns(n: int = 60, vol: float = 0.01) -> list[float]:
    random.seed(42)
    return [random.gauss(0, vol) for _ in range(n)]


def _monitor_with_portfolio(
    portfolio_risk_enabled: bool = True,
    max_var_pct: float = 0.05,
    max_beta_absolute: float = 2.0,
    max_concentration_pct: float = 0.50,
) -> tuple[RiskMonitor, PortfolioRiskEngine]:
    config = RiskConfig(
        portfolio_risk_enabled=portfolio_risk_enabled,
        max_var_pct=max_var_pct,
        max_beta_absolute=max_beta_absolute,
        max_concentration_pct=max_concentration_pct,
    )
    portfolio = PortfolioRiskEngine()
    monitor = RiskMonitor(config=config, portfolio_risk=portfolio)
    returns = {"TX": _returns(60, vol=0.01)}
    prices = {"TX": 20000.0}
    monitor.update_market_data(returns, prices)
    return monitor, portfolio


class TestPortfolioRiskDisabled:
    """Portfolio risk is disabled by default — backwards compatible."""

    def test_disabled_by_default(self):
        config = RiskConfig()
        monitor = RiskMonitor(config=config)
        result = monitor.check(_account())
        assert result == RiskAction.NORMAL

    def test_disabled_skips_portfolio_checks(self):
        monitor, _ = _monitor_with_portfolio(portfolio_risk_enabled=False)
        result = monitor.check(_account())
        assert result == RiskAction.NORMAL

    def test_none_portfolio_risk(self):
        config = RiskConfig(portfolio_risk_enabled=True)
        monitor = RiskMonitor(config=config, portfolio_risk=None)
        result = monitor.check(_account())
        assert result == RiskAction.NORMAL


class TestVaRCheck:
    """Task 4.2: VaR breach → HALT_NEW_ENTRIES."""

    def test_var_within_limit(self):
        monitor, _ = _monitor_with_portfolio(max_var_pct=0.50)
        result = monitor.check(_account())
        assert result == RiskAction.NORMAL

    def test_var_breach_halts(self):
        # Very tight VaR limit that will be breached
        monitor, _ = _monitor_with_portfolio(max_var_pct=0.0001)
        result = monitor.check(_account())
        assert result == RiskAction.HALT_NEW_ENTRIES
        assert any(e.trigger == "var_limit_breach" for e in monitor.events)

    def test_var_event_has_details(self):
        monitor, _ = _monitor_with_portfolio(max_var_pct=0.0001)
        monitor.check(_account())
        events = [e for e in monitor.events if e.trigger == "var_limit_breach"]
        assert len(events) == 1
        assert "var_pct" in events[0].details
        assert "var_99_1d" in events[0].details


class TestBetaCheck:
    """Task 4.3: beta breach → HALT_NEW_ENTRIES."""

    def test_beta_within_limit(self):
        monitor, _ = _monitor_with_portfolio(max_beta_absolute=2.0)
        result = monitor.check(_account())
        assert result == RiskAction.NORMAL

    def test_beta_breach_halts(self):
        monitor, _ = _monitor_with_portfolio(max_beta_absolute=0.01)
        result = monitor.check(_account())
        assert result == RiskAction.HALT_NEW_ENTRIES
        assert any(e.trigger == "beta_breach" for e in monitor.events)


class TestConcentrationCheck:
    """Task 4.3: concentration breach → HALT_NEW_ENTRIES."""

    def test_concentration_within_limit(self):
        monitor, _ = _monitor_with_portfolio(max_concentration_pct=0.50)
        result = monitor.check(_account())
        assert result == RiskAction.NORMAL

    def test_concentration_breach_halts(self):
        # 1 lot * 20000 / 10000 equity = 200% concentration
        monitor, _ = _monitor_with_portfolio(max_concentration_pct=0.01)
        account = _account(equity=10_000, margin_used=5_000)
        result = monitor.check(account)
        assert result == RiskAction.HALT_NEW_ENTRIES
        assert any(e.trigger == "concentration_breach" for e in monitor.events)


class TestPriorityOrdering:
    """Portfolio risk checks should respect priority ordering."""

    def test_drawdown_takes_precedence(self):
        """Drawdown (priority 1) overrides VaR (priority 3.5)."""
        monitor, _ = _monitor_with_portfolio(max_var_pct=0.0001)
        account = _account(equity=1_000_000)
        # Trigger drawdown circuit breaker
        account = AccountState(
            equity=1_000_000, unrealized_pnl=-600_000, realized_pnl=0.0,
            margin_used=200_000, margin_available=800_000,
            margin_ratio=5.0, drawdown_pct=0.6, positions=[_pos()],
            timestamp=datetime.now(),
        )
        result = monitor.check(account)
        assert result == RiskAction.CLOSE_ALL

    def test_var_before_signal_staleness(self):
        """VaR check (3.5) fires before signal staleness (4)."""
        monitor, _ = _monitor_with_portfolio(max_var_pct=0.0001)
        monitor.update_signal_time(datetime(2020, 1, 1))  # very stale
        result = monitor.check(_account())
        assert result == RiskAction.HALT_NEW_ENTRIES
        assert any(e.trigger == "var_limit_breach" for e in monitor.events)
