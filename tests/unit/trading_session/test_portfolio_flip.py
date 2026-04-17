"""Tests for LivePortfolioManager — CRUD, membership, and flip_mode precondition."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from src.trading_session.live_portfolio_manager import (
    LivePortfolioManager,
    PortfolioFlipError,
)
from src.trading_session.portfolio_db import LivePortfolioStore
from src.trading_session.session import SessionSnapshot, TradingSession
from src.trading_session.session_db import SessionDB


@dataclass
class _FakePosition:
    symbol: str = "TX"


def _snapshot_with_positions(n: int) -> SessionSnapshot:
    """Build a snapshot reporting `n` open positions."""
    return SessionSnapshot.compute(
        equity=1_000_000.0,
        peak_equity=1_000_000.0,
        unrealized_pnl=0.0,
        realized_pnl=0.0,
        positions=[_FakePosition() for _ in range(n)],  # type: ignore[list-item]
    )


class _FakeSessionManager:
    """Minimal SessionManager stand-in for isolated portfolio tests."""

    def __init__(self, sessions: list[TradingSession], session_db: Any = None) -> None:
        self._by_id = {s.session_id: s for s in sessions}
        self._session_db = session_db

    def get_session(self, session_id: str) -> TradingSession | None:
        return self._by_id.get(session_id)

    def get_all_sessions(self) -> list[TradingSession]:
        return list(self._by_id.values())


@pytest.fixture()
def store(tmp_path: Path) -> LivePortfolioStore:
    return LivePortfolioStore(db_path=tmp_path / "portfolio.db")


@pytest.fixture()
def session_db(tmp_path: Path) -> SessionDB:
    return SessionDB(db_path=tmp_path / "trading.db")


class TestCreateAndCrud:
    def test_create_portfolio_persists(self, store: LivePortfolioStore) -> None:
        sm = _FakeSessionManager([])
        mgr = LivePortfolioManager(store=store, session_manager=sm)  # type: ignore[arg-type]
        portfolio = mgr.create_portfolio(
            name="alpha", account_id="acct-1", mode="paper",
        )
        assert portfolio.mode == "paper"
        # Retrieve via manager and direct store lookup.
        assert mgr.get_portfolio(portfolio.portfolio_id).mode == "paper"  # type: ignore[union-attr]
        assert store.get(portfolio.portfolio_id) is not None


class TestMembership:
    def test_attach_rejects_cross_account(
        self, store: LivePortfolioStore, session_db: SessionDB,
    ) -> None:
        session = TradingSession.create("acct-other", "strat", "TX")
        session_db.save(session)
        sm = _FakeSessionManager([session], session_db=session_db)
        mgr = LivePortfolioManager(store=store, session_manager=sm)  # type: ignore[arg-type]
        portfolio = mgr.create_portfolio(name="p1", account_id="acct-1")
        with pytest.raises(ValueError, match="does not match"):
            mgr.attach_session(portfolio.portfolio_id, session.session_id)

    def test_attach_writes_through_to_db(
        self, store: LivePortfolioStore, session_db: SessionDB,
    ) -> None:
        session = TradingSession.create("acct-1", "strat", "TX")
        session_db.save(session)
        sm = _FakeSessionManager([session], session_db=session_db)
        mgr = LivePortfolioManager(store=store, session_manager=sm)  # type: ignore[arg-type]
        portfolio = mgr.create_portfolio(name="p1", account_id="acct-1")
        mgr.attach_session(portfolio.portfolio_id, session.session_id)
        # In-memory
        assert session.portfolio_id == portfolio.portfolio_id
        # DB round-trip
        loaded = session_db.load_all()[0]
        assert loaded.portfolio_id == portfolio.portfolio_id


class TestFlipPrecondition:
    def _make_running_session(self) -> TradingSession:
        s = TradingSession.create("acct-1", "strat-a", "TX")
        s.status = "active"
        return s

    def _make_flat_stopped_session(self) -> TradingSession:
        # status='stopped', zero positions — flip-eligible.
        return TradingSession.create("acct-1", "strat-a", "TX")

    def _make_stopped_with_positions(self) -> TradingSession:
        s = TradingSession.create("acct-1", "strat-a", "TX")
        s.current_snapshot = _snapshot_with_positions(2)
        return s

    def test_flip_rejected_when_member_is_active(
        self, store: LivePortfolioStore,
    ) -> None:
        session = self._make_running_session()
        sm = _FakeSessionManager([session])
        mgr = LivePortfolioManager(store=store, session_manager=sm)  # type: ignore[arg-type]
        portfolio = mgr.create_portfolio(name="p1", account_id="acct-1", mode="paper")
        session.portfolio_id = portfolio.portfolio_id
        with pytest.raises(PortfolioFlipError) as exc:
            mgr.flip_mode(portfolio.portfolio_id, "live")
        reasons = exc.value.reasons
        assert len(reasons) == 1
        assert reasons[0]["reason"] == "session_not_stopped_or_paused"
        # Portfolio mode in DB must be unchanged.
        assert store.get(portfolio.portfolio_id).mode == "paper"  # type: ignore[union-attr]

    def test_flip_rejected_when_member_has_positions(
        self, store: LivePortfolioStore,
    ) -> None:
        session = self._make_stopped_with_positions()
        sm = _FakeSessionManager([session])
        mgr = LivePortfolioManager(store=store, session_manager=sm)  # type: ignore[arg-type]
        portfolio = mgr.create_portfolio(name="p1", account_id="acct-1", mode="paper")
        session.portfolio_id = portfolio.portfolio_id
        with pytest.raises(PortfolioFlipError) as exc:
            mgr.flip_mode(portfolio.portfolio_id, "live")
        assert exc.value.reasons[0]["reason"] == "session_has_open_positions"
        assert exc.value.reasons[0]["position_count"] == 2

    def test_flip_happy_path_triggers_callback(
        self, store: LivePortfolioStore,
    ) -> None:
        session = self._make_flat_stopped_session()
        sm = _FakeSessionManager([session])
        callback = MagicMock()
        mgr = LivePortfolioManager(
            store=store, session_manager=sm, on_mode_changed=callback,  # type: ignore[arg-type]
        )
        portfolio = mgr.create_portfolio(name="p1", account_id="acct-1", mode="paper")
        session.portfolio_id = portfolio.portfolio_id
        updated = mgr.flip_mode(portfolio.portfolio_id, "live")
        assert updated.mode == "live"
        assert store.get(portfolio.portfolio_id).mode == "live"  # type: ignore[union-attr]
        callback.assert_called_once()
        assert callback.call_args[0][0].portfolio_id == portfolio.portfolio_id

    def test_flip_noop_when_already_in_target_mode(
        self, store: LivePortfolioStore,
    ) -> None:
        # No sessions → preconditions would pass trivially. Verify that
        # same-mode flip is a no-op and does not fire the callback.
        sm = _FakeSessionManager([])
        callback = MagicMock()
        mgr = LivePortfolioManager(
            store=store, session_manager=sm, on_mode_changed=callback,  # type: ignore[arg-type]
        )
        portfolio = mgr.create_portfolio(name="p1", account_id="acct-1", mode="paper")
        mgr.flip_mode(portfolio.portfolio_id, "paper")
        callback.assert_not_called()

    def test_invalid_mode_rejected(self, store: LivePortfolioStore) -> None:
        sm = _FakeSessionManager([])
        mgr = LivePortfolioManager(store=store, session_manager=sm)  # type: ignore[arg-type]
        portfolio = mgr.create_portfolio(name="p1", account_id="acct-1", mode="paper")
        with pytest.raises(ValueError, match="new_mode must be"):
            mgr.flip_mode(portfolio.portfolio_id, "fake-mode")  # type: ignore[arg-type]
