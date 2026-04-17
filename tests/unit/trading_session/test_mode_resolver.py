"""Tests for resolve_session_mode() precedence ladder."""
from __future__ import annotations

from dataclasses import dataclass

import pytest

from src.trading_session.mode_resolver import resolve_session_mode
from src.trading_session.portfolio_db import LivePortfolio
from src.trading_session.session import TradingSession


@dataclass
class _FakeAccount:
    sandbox_mode: bool


class _FakeAccountStore:
    def __init__(self, account: _FakeAccount | None) -> None:
        self._account = account

    def load_account(self, account_id: str) -> _FakeAccount | None:
        del account_id
        return self._account


class _FakePortfolioStore:
    def __init__(self, portfolios: dict[str, LivePortfolio] | None = None) -> None:
        self._portfolios = portfolios or {}

    def get(self, portfolio_id: str) -> LivePortfolio | None:
        return self._portfolios.get(portfolio_id)


def _make_session(**overrides) -> TradingSession:
    base = dict(
        account_id="acct-1",
        strategy_slug="some_strategy",
        symbol="TX",
    )
    base.update(overrides)
    return TradingSession.create(**base)


class TestResolveSessionMode:
    def test_portfolio_mode_overrides_session_override(self) -> None:
        """When bound to a portfolio, session.execution_mode is ignored."""
        portfolio = LivePortfolio.create(
            name="p1", account_id="acct-1", mode="live",
        )
        session = _make_session(
            execution_mode="paper",
            portfolio_id=portfolio.portfolio_id,
        )
        store = _FakePortfolioStore({portfolio.portfolio_id: portfolio})
        mode = resolve_session_mode(session, portfolio_store=store)
        assert mode == "live"

    def test_session_override_wins_when_no_portfolio(self) -> None:
        session = _make_session(execution_mode="live")
        # account defaults to sandbox (paper) but session override should win
        store = _FakeAccountStore(_FakeAccount(sandbox_mode=True))
        mode = resolve_session_mode(session, account_store=store)
        assert mode == "live"

    def test_account_sandbox_mode_falls_back_to_paper(self) -> None:
        session = _make_session()
        store = _FakeAccountStore(_FakeAccount(sandbox_mode=True))
        assert resolve_session_mode(session, account_store=store) == "paper"

    def test_account_non_sandbox_falls_back_to_live(self) -> None:
        session = _make_session()
        store = _FakeAccountStore(_FakeAccount(sandbox_mode=False))
        assert resolve_session_mode(session, account_store=store) == "live"

    def test_terminal_default_when_all_stores_empty(self) -> None:
        """No portfolio, no session mode, no account → default_mode (paper)."""
        session = _make_session()
        assert resolve_session_mode(session) == "paper"

    def test_unknown_portfolio_id_raises(self) -> None:
        session = _make_session(portfolio_id="ghost-id")
        store = _FakePortfolioStore({})
        with pytest.raises(ValueError, match="unknown portfolio"):
            resolve_session_mode(session, portfolio_store=store)

    def test_portfolio_id_without_store_raises(self) -> None:
        session = _make_session(portfolio_id="some-id")
        with pytest.raises(ValueError, match="no portfolio_store"):
            resolve_session_mode(session)

    def test_portfolio_mode_change_reflects_on_next_resolve(self) -> None:
        """Mode is always re-read from the store, so flips are picked up."""
        portfolio = LivePortfolio.create(
            name="p1", account_id="acct-1", mode="paper",
        )
        session = _make_session(portfolio_id=portfolio.portfolio_id)
        store = _FakePortfolioStore({portfolio.portfolio_id: portfolio})
        assert resolve_session_mode(session, portfolio_store=store) == "paper"
        portfolio.mode = "live"
        assert resolve_session_mode(session, portfolio_store=store) == "live"
