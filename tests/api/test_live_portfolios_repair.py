"""Integration tests for the /api/live-portfolios/{id}/repair-allocations endpoint."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.routes.live_portfolios import router as live_portfolios_router
from src.trading_session.live_portfolio_manager import LivePortfolioManager
from src.trading_session.portfolio_db import LivePortfolioStore
from src.trading_session.session import TradingSession
from src.trading_session.session_db import SessionDB


class _FakeSessionManager:
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
def app_with_manager(tmp_path: Path):
    """Build an isolated FastAPI app whose live-portfolio routes resolve to
    a fixture-owned manager. Returns (TestClient, manager, store, session_db).
    """
    pdb = LivePortfolioStore(db_path=tmp_path / "portfolio.db")
    sdb = SessionDB(db_path=tmp_path / "trading.db")
    sessions: list[TradingSession] = []
    sm = _FakeSessionManager(sessions, session_db=sdb)
    mgr = LivePortfolioManager(store=pdb, session_manager=sm)  # type: ignore[arg-type]

    app = FastAPI()
    app.include_router(live_portfolios_router)

    # Patch the helper so the route resolves to our fixture-owned manager
    # instead of the global one.
    import src.api.routes.live_portfolios as live_portfolios_mod

    original = live_portfolios_mod._get_manager
    live_portfolios_mod._get_manager = lambda: mgr

    client = TestClient(app)
    yield client, mgr, sm, sdb, sessions
    live_portfolios_mod._get_manager = original


def _attach_legacy_state(
    mgr: LivePortfolioManager,
    sm: _FakeSessionManager,
    sdb: SessionDB,
    sessions_ref: list[TradingSession],
    n: int,
    account_id: str = "acct-A",
) -> str:
    """Build n sessions on the same account and bind them to a fresh
    portfolio without going through attach_session — this preserves the
    legacy default equity_share=1.0 state we want the repair endpoint to
    fix.
    """
    portfolio = mgr.create_portfolio(name="legacy", account_id=account_id)
    for i in range(n):
        s = TradingSession.create(account_id, f"strat-{i}", "TX")
        sdb.save(s)
        sessions_ref.append(s)
        sm._by_id[s.session_id] = s
        s.portfolio_id = portfolio.portfolio_id
        sdb.update_portfolio_id(s.session_id, portfolio.portfolio_id)
    return portfolio.portfolio_id


class TestRepairEndpoint:
    def test_repair_invalid_portfolio_rebalances(self, app_with_manager) -> None:
        client, mgr, sm, sdb, sessions = app_with_manager
        pid = _attach_legacy_state(mgr, sm, sdb, sessions, n=3)
        # Pre-condition: 3 sessions × 1.0 (sum=3.0).
        assert all(s.equity_share == 1.0 for s in sessions)
        resp = client.post(f"/api/live-portfolios/{pid}/repair-allocations")
        assert resp.status_code == 200
        body = resp.json()
        assert body["rebalanced"] is True
        # After: shares sum to 1.0, each ≈ 1/3.
        after_total = sum(body["after"].values())
        assert after_total == pytest.approx(1.0, abs=1e-9)
        for share in body["after"].values():
            assert 0.3332 <= share <= 0.3335

    def test_repair_valid_portfolio_is_noop(self, app_with_manager) -> None:
        client, mgr, sm, sdb, sessions = app_with_manager
        pid = _attach_legacy_state(mgr, sm, sdb, sessions, n=3)
        # First call rebalances; second call should be a no-op.
        client.post(f"/api/live-portfolios/{pid}/repair-allocations")
        resp = client.post(f"/api/live-portfolios/{pid}/repair-allocations")
        assert resp.status_code == 200
        body = resp.json()
        assert body["rebalanced"] is False
        # Shares unchanged.
        before_after_match = body["before"] == body["after"]
        assert before_after_match

    def test_repair_unknown_portfolio_returns_404(self, app_with_manager) -> None:
        client, *_ = app_with_manager
        resp = client.post("/api/live-portfolios/does-not-exist/repair-allocations")
        assert resp.status_code == 404
