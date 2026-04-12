"""Tests for the /api/sessions PATCH equity-share endpoint."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from src.api import routes
from src.trading_session.manager import SessionManager
from src.trading_session.session_db import SessionDB


@pytest.fixture()
def test_client(tmp_path: Path, monkeypatch):
    """Spin up a TestClient backed by an isolated SessionManager.

    Uses a fresh SessionDB under tmp_path so tests do not touch the real
    trading.db. The module-level get_session_manager() helper is
    monkeypatched to hand our isolated manager to the route.
    """
    registry = MagicMock()
    registry.get_all_configs.return_value = []
    db = SessionDB(db_path=tmp_path / "test_trading.db")
    mgr = SessionManager(registry=registry, session_db=db)

    # Route imports get_session_manager lazily from src.api.helpers; patch it
    import src.api.routes.sessions as sessions_route
    monkeypatch.setattr(sessions_route, "_get_session_manager", lambda: mgr)

    # Build a minimal FastAPI app that only mounts the sessions router
    from fastapi import FastAPI
    app = FastAPI()
    app.include_router(routes.sessions.router)
    client = TestClient(app)
    yield client, mgr
    db.close()


class TestEquityShareEndpoint:
    def test_patch_updates_share(self, test_client) -> None:
        client, mgr = test_client
        session = mgr.create_session("acct-1", "strat-a", "TX", equity_share=1.0)
        resp = client.patch(
            f"/api/sessions/{session.session_id}/equity-share",
            json={"share": 0.6},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["equity_share"] == pytest.approx(0.6)
        assert body["session_id"] == session.session_id
        # And it's persisted on the manager
        assert mgr.get_session(session.session_id).equity_share == pytest.approx(0.6)

    def test_patch_rejects_out_of_range(self, test_client) -> None:
        client, mgr = test_client
        session = mgr.create_session("acct-1", "strat-a", "TX")
        # 0 fails pydantic validation with 422
        resp = client.patch(
            f"/api/sessions/{session.session_id}/equity-share",
            json={"share": 0.0},
        )
        assert resp.status_code == 422
        resp = client.patch(
            f"/api/sessions/{session.session_id}/equity-share",
            json={"share": 1.5},
        )
        assert resp.status_code == 422

    def test_patch_404_for_unknown_session(self, test_client) -> None:
        client, _ = test_client
        resp = client.patch(
            "/api/sessions/does-not-exist/equity-share",
            json={"share": 0.5},
        )
        assert resp.status_code == 404

    def test_patch_409_on_allocation_overflow(self, test_client) -> None:
        client, mgr = test_client
        a = mgr.create_session("acct-1", "strat-a", "TX", equity_share=0.6)
        b = mgr.create_session("acct-1", "strat-b", "TX", equity_share=0.4)
        # Total is already 1.0; pushing b to 0.5 would make total 1.1
        resp = client.patch(
            f"/api/sessions/{b.session_id}/equity-share",
            json={"share": 0.5},
        )
        assert resp.status_code == 409
        # a's share is unchanged
        assert mgr.get_session(a.session_id).equity_share == pytest.approx(0.6)

    def test_list_sessions_includes_equity_share(self, test_client) -> None:
        client, mgr = test_client
        mgr.create_session("acct-1", "strat-a", "TX", equity_share=0.6)
        mgr.create_session("acct-1", "strat-b", "TX", equity_share=0.4)
        resp = client.get("/api/sessions")
        assert resp.status_code == 200
        rows = resp.json()
        shares = {row["strategy_slug"]: row["equity_share"] for row in rows}
        assert shares["strat-a"] == pytest.approx(0.6)
        assert shares["strat-b"] == pytest.approx(0.4)
