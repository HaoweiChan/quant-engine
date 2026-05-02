"""Tests for the LivePortfolio allocation invariant.

Covers the auto-rebalance on attach, the explicit-batch-weight override,
the repair entrypoint for the boot scan, and the idempotency contract.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from src.trading_session.live_portfolio_manager import LivePortfolioManager
from src.trading_session.portfolio_db import LivePortfolioStore
from src.trading_session.session import TradingSession
from src.trading_session.session_db import SessionDB


@dataclass
class _FakePosition:
    symbol: str = "TX"


class _FakeSessionManager:
    """Minimal SessionManager stand-in matching the interface used by
    LivePortfolioManager — only the attributes we actually touch.
    """

    def __init__(
        self, sessions: list[TradingSession], session_db: Any = None,
    ) -> None:
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


def _make_session(slug: str, account: str = "acct-1") -> TradingSession:
    """Build a default-equity_share=1.0 session — matches the legacy
    state we are repairing."""
    return TradingSession.create(account, slug, "TX")


# ---------------------------------------------------------------------------
# attach_session auto-rebalance
# ---------------------------------------------------------------------------


class TestAttachAutoRebalance:
    def test_single_member_keeps_full_share(
        self, store: LivePortfolioStore, session_db: SessionDB,
    ) -> None:
        s1 = _make_session("strat-a")
        session_db.save(s1)
        sm = _FakeSessionManager([s1], session_db=session_db)
        mgr = LivePortfolioManager(store=store, session_manager=sm)  # type: ignore[arg-type]
        portfolio = mgr.create_portfolio(name="p1", account_id="acct-1")
        mgr.attach_session(portfolio.portfolio_id, s1.session_id)
        # 1 member → 1.0 (full share, matches legacy behaviour bit-for-bit).
        assert s1.equity_share == 1.0
        # DB round-trip
        loaded = session_db.find_session("acct-1", "strat-a", "TX")
        assert loaded is not None
        assert loaded.equity_share == 1.0

    def test_three_members_yield_one_third_each(
        self, store: LivePortfolioStore, session_db: SessionDB,
    ) -> None:
        sessions = [_make_session(f"strat-{i}") for i in "abc"]
        for s in sessions:
            session_db.save(s)
        sm = _FakeSessionManager(sessions, session_db=session_db)
        mgr = LivePortfolioManager(store=store, session_manager=sm)  # type: ignore[arg-type]
        portfolio = mgr.create_portfolio(name="p1", account_id="acct-1")
        for s in sessions:
            mgr.attach_session(portfolio.portfolio_id, s.session_id)
        # All three members rebalanced to 1/3 each (with last absorbing
        # the rounding remainder). Sum is exactly 1.0.
        shares = [s.equity_share for s in sessions]
        assert sum(shares) == pytest.approx(1.0, abs=1e-9)
        # Each share is approximately 0.3333; the last one is 0.3334.
        assert all(0.3332 <= s <= 0.3335 for s in shares)
        # DB round-trip — new sessions persisted with the rebalanced share.
        loaded_all = session_db.load_all()
        assert sum(s.equity_share for s in loaded_all) == pytest.approx(1.0, abs=1e-9)

    def test_attach_failure_does_not_rebalance(
        self, store: LivePortfolioStore, session_db: SessionDB,
    ) -> None:
        # Cross-account attach must fail BEFORE any rebalance fires.
        existing = _make_session("strat-a", account="acct-1")
        session_db.save(existing)
        cross = _make_session("strat-b", account="acct-other")
        session_db.save(cross)
        sm = _FakeSessionManager([existing, cross], session_db=session_db)
        mgr = LivePortfolioManager(store=store, session_manager=sm)  # type: ignore[arg-type]
        portfolio = mgr.create_portfolio(name="p1", account_id="acct-1")
        mgr.attach_session(portfolio.portfolio_id, existing.session_id)
        # Pre-failure baseline: existing is 1.0 (1 member portfolio).
        assert existing.equity_share == 1.0
        with pytest.raises(ValueError, match="does not match"):
            mgr.attach_session(portfolio.portfolio_id, cross.session_id)
        # Existing share unchanged — failed attach must not have triggered
        # a rebalance to 0.5 each.
        assert existing.equity_share == 1.0


# ---------------------------------------------------------------------------
# explicit batch weights override
# ---------------------------------------------------------------------------


class TestExplicitBatchOverride:
    def test_explicit_weights_after_attach_take_precedence(
        self, store: LivePortfolioStore, tmp_path: Path,
    ) -> None:
        # Use the real SessionManager so we exercise the batch path the
        # frontend's load-portfolio flow actually uses.
        from src.trading_session.manager import SessionManager
        from src.broker_gateway.registry import GatewayRegistry

        sdb = SessionDB(db_path=tmp_path / "trading.db")
        registry = GatewayRegistry.__new__(GatewayRegistry)
        registry._db = None  # type: ignore[attr-defined]
        registry._gateways = {}  # type: ignore[attr-defined]
        registry._configs = []  # type: ignore[attr-defined]

        sm = SessionManager(registry=registry, session_db=sdb)
        # Inject 3 sessions directly via create_session so SessionManager's
        # in-memory dict is populated.
        s1 = sm.create_session("acct-1", "strat-a", "TX")
        s2 = sm.create_session("acct-1", "strat-b", "TX")
        s3 = sm.create_session("acct-1", "strat-c", "TX")

        mgr = LivePortfolioManager(store=store, session_manager=sm)
        portfolio = mgr.create_portfolio(name="p1", account_id="acct-1")
        mgr.attach_session(portfolio.portfolio_id, s1.session_id)
        mgr.attach_session(portfolio.portfolio_id, s2.session_id)
        mgr.attach_session(portfolio.portfolio_id, s3.session_id)
        # After three attaches each is ≈ 1/3.
        assert sum(s.equity_share for s in (s1, s2, s3)) == pytest.approx(1.0, abs=1e-9)

        # Frontend now applies explicit weights via batchUpdateEquityShare.
        sm.set_equity_shares_batch([
            (s1.session_id, 0.5),
            (s2.session_id, 0.3),
            (s3.session_id, 0.2),
        ])
        assert s1.equity_share == 0.5
        assert s2.equity_share == 0.3
        assert s3.equity_share == 0.2


# ---------------------------------------------------------------------------
# rebalance_equal_weights / repair
# ---------------------------------------------------------------------------


class TestRebalanceAndRepair:
    def _three_session_portfolio(
        self, store: LivePortfolioStore, session_db: SessionDB,
    ) -> tuple[LivePortfolioManager, list[TradingSession], str]:
        sessions = [_make_session(f"strat-{i}") for i in "abc"]
        for s in sessions:
            session_db.save(s)
        sm = _FakeSessionManager(sessions, session_db=session_db)
        mgr = LivePortfolioManager(store=store, session_manager=sm)  # type: ignore[arg-type]
        portfolio = mgr.create_portfolio(name="p1", account_id="acct-1")
        # Bypass attach_session to keep the broken state we want to repair:
        # 3 members all at the default equity_share=1.0.
        for s in sessions:
            s.portfolio_id = portfolio.portfolio_id
            session_db.update_portfolio_id(s.session_id, portfolio.portfolio_id)
        return mgr, sessions, portfolio.portfolio_id

    def test_rebalance_repairs_all_one_state(
        self, store: LivePortfolioStore, session_db: SessionDB,
    ) -> None:
        mgr, sessions, pid = self._three_session_portfolio(store, session_db)
        # Pre-condition: broken state.
        assert all(s.equity_share == 1.0 for s in sessions)
        mgr.rebalance_equal_weights(pid)
        assert sum(s.equity_share for s in sessions) == pytest.approx(1.0, abs=1e-9)

    def test_rebalance_idempotent_on_valid_portfolio(
        self, store: LivePortfolioStore, session_db: SessionDB,
    ) -> None:
        mgr, sessions, pid = self._three_session_portfolio(store, session_db)
        mgr.rebalance_equal_weights(pid)
        first = [s.equity_share for s in sessions]
        # Re-running on already-equal portfolio is a no-op.
        mgr.rebalance_equal_weights(pid)
        second = [s.equity_share for s in sessions]
        assert first == second

    def test_rebalance_unknown_portfolio_raises(
        self, store: LivePortfolioStore, session_db: SessionDB,
    ) -> None:
        sm = _FakeSessionManager([], session_db=session_db)
        mgr = LivePortfolioManager(store=store, session_manager=sm)  # type: ignore[arg-type]
        with pytest.raises(ValueError, match="not found"):
            mgr.rebalance_equal_weights("does-not-exist")

    def test_rebalance_empty_portfolio_returns_empty(
        self, store: LivePortfolioStore, session_db: SessionDB,
    ) -> None:
        sm = _FakeSessionManager([], session_db=session_db)
        mgr = LivePortfolioManager(store=store, session_manager=sm)  # type: ignore[arg-type]
        portfolio = mgr.create_portfolio(name="p1", account_id="acct-1")
        result = mgr.rebalance_equal_weights(portfolio.portfolio_id)
        assert result == []

    def test_repair_invalid_portfolios_skips_valid_ones(
        self, store: LivePortfolioStore, session_db: SessionDB,
    ) -> None:
        # Build two portfolios on the same fake-account fixture: one valid
        # (already 0.5/0.5), one broken (1.0/1.0).
        valid_a = _make_session("v-a", account="acct-A")
        valid_b = _make_session("v-b", account="acct-A")
        valid_a.equity_share = 0.5
        valid_b.equity_share = 0.5
        broken_a = _make_session("b-a", account="acct-B")
        broken_b = _make_session("b-b", account="acct-B")
        for s in (valid_a, valid_b, broken_a, broken_b):
            session_db.save(s)
        sm = _FakeSessionManager(
            [valid_a, valid_b, broken_a, broken_b], session_db=session_db,
        )
        mgr = LivePortfolioManager(store=store, session_manager=sm)  # type: ignore[arg-type]
        p_valid = mgr.create_portfolio(name="valid", account_id="acct-A")
        p_broken = mgr.create_portfolio(name="broken", account_id="acct-B")
        for s in (valid_a, valid_b):
            s.portfolio_id = p_valid.portfolio_id
            session_db.update_portfolio_id(s.session_id, p_valid.portfolio_id)
        for s in (broken_a, broken_b):
            s.portfolio_id = p_broken.portfolio_id
            session_db.update_portfolio_id(s.session_id, p_broken.portfolio_id)
        repaired = mgr.repair_invalid_portfolios()
        # Only the broken portfolio should have been touched.
        assert len(repaired) == 1
        assert repaired[0]["portfolio_id"] == p_broken.portfolio_id
        # Valid portfolio shares unchanged.
        assert valid_a.equity_share == 0.5
        assert valid_b.equity_share == 0.5
        # Broken portfolio fixed.
        assert sum((broken_a.equity_share, broken_b.equity_share)) == pytest.approx(1.0, abs=1e-9)

    def test_repair_idempotent(
        self, store: LivePortfolioStore, session_db: SessionDB,
    ) -> None:
        mgr, _sessions, _pid = self._three_session_portfolio(store, session_db)
        first = mgr.repair_invalid_portfolios()
        assert len(first) == 1
        second = mgr.repair_invalid_portfolios()
        assert second == []
