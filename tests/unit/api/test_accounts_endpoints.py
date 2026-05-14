"""End-to-end tests for the accounts CRUD endpoints — pin the post-refactor
contract:
- POST /api/accounts requires an explicit non-empty id
- POST returns 409 on id collision (no silent overwrite)
- DELETE /api/accounts/{id} removes the DB row AND every credential the
  registry stored under that id (GSM cascade)
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.routes import accounts as accounts_module
from src.broker_gateway.account_db import AccountDB


@pytest.fixture
def app(tmp_path, monkeypatch):
    """FastAPI app with an isolated SQLite DB and stubbed credential storage."""
    test_db = AccountDB(db_path=tmp_path / "test_accounts.db")
    monkeypatch.setattr(accounts_module, "_get_db", lambda: test_db)

    saved: dict[str, dict] = {}
    deleted: list[str] = []

    def _save_credentials(account_id: str, creds: dict[str, str]) -> None:
        saved[account_id] = dict(creds)

    def _delete_credentials(account_id: str) -> None:
        deleted.append(account_id)
        saved.pop(account_id, None)

    # The endpoint imports these inside the request handler — patch the
    # source module so the imports inside the route resolve to the stubs.
    monkeypatch.setattr(
        "src.broker_gateway.registry.save_credentials", _save_credentials,
    )
    monkeypatch.setattr(
        "src.broker_gateway.registry.delete_credentials", _delete_credentials,
    )

    app = FastAPI()
    app.include_router(accounts_module.router)
    app.state._test_saved_creds = saved
    app.state._test_deleted_creds = deleted
    return app


def test_create_account_requires_explicit_id(app: FastAPI):
    client = TestClient(app)
    resp = client.post("/api/accounts", json={"broker": "sinopac"})
    assert resp.status_code == 422  # pydantic validation rejects missing id


def test_create_account_rejects_empty_id(app: FastAPI):
    client = TestClient(app)
    resp = client.post("/api/accounts", json={"id": "   ", "broker": "sinopac"})
    assert resp.status_code == 422


def test_create_account_succeeds_with_explicit_id(app: FastAPI):
    client = TestClient(app)
    resp = client.post(
        "/api/accounts",
        json={
            "id": "1839302",
            "broker": "sinopac",
            "display_name": "Sinopac A",
            "api_key": "trading-key-A",
            "api_secret": "trading-secret-A",
        },
    )
    assert resp.status_code == 201
    assert resp.json()["id"] == "1839302"
    # Credentials must have flowed through to the (stubbed) GSM layer.
    assert app.state._test_saved_creds["1839302"]["api_key"] == "trading-key-A"


def test_create_account_returns_409_on_collision(app: FastAPI):
    """The exact regression: a second POST with the same id used to wipe
    the original row. Now it must 409 and leave the original intact."""
    client = TestClient(app)
    r1 = client.post(
        "/api/accounts",
        json={"id": "1839302", "broker": "sinopac", "api_key": "first"},
    )
    assert r1.status_code == 201

    r2 = client.post(
        "/api/accounts",
        json={"id": "1839302", "broker": "sinopac", "api_key": "second-would-clobber"},
    )
    assert r2.status_code == 409
    assert "already exists" in r2.json()["detail"]

    # Original credential set must be untouched.
    saved = app.state._test_saved_creds
    assert saved["1839302"]["api_key"] == "first"


def test_create_two_distinct_sinopac_accounts(app: FastAPI):
    """The post-refactor workflow the user actually wants."""
    client = TestClient(app)
    for acct_id in ("1839302", "2010515"):
        resp = client.post(
            "/api/accounts",
            json={"id": acct_id, "broker": "sinopac", "api_key": f"key-{acct_id}"},
        )
        assert resp.status_code == 201

    listed = client.get("/api/accounts").json()
    ids = sorted(a["id"] for a in listed)
    assert ids == ["1839302", "2010515"]


def test_delete_account_cascades_to_gsm(app: FastAPI):
    """Deleting an account must remove the DB row AND the GSM credentials.
    User explicitly asked for this in the refactor brief."""
    client = TestClient(app)
    client.post(
        "/api/accounts",
        json={"id": "1839302", "broker": "sinopac", "api_key": "to-be-deleted"},
    )
    assert "1839302" in app.state._test_saved_creds

    resp = client.delete("/api/accounts/1839302")
    assert resp.status_code == 200
    assert resp.json()["deleted"] is True

    # DB row gone
    assert client.get("/api/accounts/1839302").status_code == 404
    # GSM credentials cleaned up via the registry stub
    assert "1839302" in app.state._test_deleted_creds
    assert "1839302" not in app.state._test_saved_creds


def test_delete_account_returns_404_when_missing(app: FastAPI):
    client = TestClient(app)
    resp = client.delete("/api/accounts/never-existed")
    assert resp.status_code == 404
    # Defensive sweep still attempts GSM cleanup so orphan secrets get cleared.
    assert "never-existed" in app.state._test_deleted_creds


# ---------------------------------------------------------------------------
# Cascade tests — pin the 2026-05-13 sinopac-main regression: deleting an
# account must transitively stop+remove its sessions and live portfolios so
# the session loader can't restore a paper runner under a now-nonexistent
# account on the next service restart.
# ---------------------------------------------------------------------------


class _FakeSession:
    def __init__(self, session_id: str, account_id: str, status: str = "active") -> None:
        self.session_id = session_id
        self.account_id = account_id
        self.status = status


class _FakeSessionManager:
    def __init__(self) -> None:
        self.sessions: dict[str, _FakeSession] = {}
        self.deleted_sessions: list[str] = []
        self.status_changes: list[tuple[str, str]] = []

    def add(self, sess: _FakeSession) -> None:
        self.sessions[sess.session_id] = sess

    def get_sessions_for_account(self, account_id: str) -> list[_FakeSession]:
        return [s for s in self.sessions.values() if s.account_id == account_id]

    def set_status(self, session_id: str, status: str) -> _FakeSession:
        sess = self.sessions[session_id]
        self.status_changes.append((session_id, status))
        sess.status = status
        return sess

    def delete_session(self, session_id: str) -> None:
        sess = self.sessions[session_id]
        if sess.status == "active":
            raise ValueError("Cannot delete an active session — stop it first")
        self.deleted_sessions.append(session_id)
        del self.sessions[session_id]


class _FakePortfolio:
    def __init__(self, portfolio_id: str, account_id: str, name: str) -> None:
        self.portfolio_id = portfolio_id
        self.account_id = account_id
        self.name = name


class _FakePortfolioStore:
    def __init__(self) -> None:
        self.portfolios: dict[str, _FakePortfolio] = {}
        self.deleted_portfolios: list[str] = []

    def add(self, p: _FakePortfolio) -> None:
        self.portfolios[p.portfolio_id] = p

    def load_for_account(self, account_id: str) -> list[_FakePortfolio]:
        return [p for p in self.portfolios.values() if p.account_id == account_id]

    def delete(self, portfolio_id: str) -> bool:
        if portfolio_id not in self.portfolios:
            return False
        self.deleted_portfolios.append(portfolio_id)
        del self.portfolios[portfolio_id]
        return True


@pytest.fixture
def app_with_cascade(app, monkeypatch):
    """Extends the base ``app`` fixture with stubbed session + portfolio
    stores wired through ``src.api.helpers`` exactly the way the
    production handler reaches them."""
    sm = _FakeSessionManager()
    ps = _FakePortfolioStore()

    # Make sure src.api.helpers is importable as a real module without
    # triggering its heavy init path. The handler imports lazily inside
    # the function body, so a plain attribute patch is enough.
    import src.api.helpers as helpers

    monkeypatch.setattr(helpers, "get_session_manager", lambda: sm, raising=False)
    monkeypatch.setattr(helpers, "_live_portfolio_store", ps, raising=False)
    monkeypatch.setattr(helpers, "sync_live_pipeline", lambda: None, raising=False)
    monkeypatch.setattr(helpers, "_gateway_registry", None, raising=False)

    app.state._test_session_manager = sm
    app.state._test_portfolio_store = ps
    return app


def test_delete_account_cascades_to_active_session_and_portfolio(app_with_cascade):
    """The exact regression: an ``active`` session and a live portfolio
    survive an account delete and the loader restores both on next
    restart. Now both must be transitioned to ``stopped`` and removed in
    the same call."""
    client = TestClient(app_with_cascade)
    sm = app_with_cascade.state._test_session_manager
    ps = app_with_cascade.state._test_portfolio_store

    client.post(
        "/api/accounts",
        json={"id": "sinopac-main", "broker": "sinopac", "api_key": "k"},
    )
    sm.add(_FakeSession("sess-1", "sinopac-main", status="active"))
    ps.add(_FakePortfolio("port-1", "sinopac-main", "TMF Max Sharpe 28/62/10"))

    resp = client.delete("/api/accounts/sinopac-main")

    assert resp.status_code == 200
    body = resp.json()
    assert body["deleted"] is True
    assert body["deleted_sessions"] == ["sess-1"]
    assert body["deleted_portfolios"] == ["port-1"]
    # Status must transit through "stopped" before delete — the
    # SessionManager refuses to drop an active session.
    assert ("sess-1", "stopped") in sm.status_changes
    assert sm.deleted_sessions == ["sess-1"]
    assert ps.deleted_portfolios == ["port-1"]
    assert "sess-1" not in sm.sessions
    assert "port-1" not in ps.portfolios


def test_delete_account_cascade_ignores_other_accounts(app_with_cascade):
    """Cascade must be scoped — sessions/portfolios on unrelated accounts
    must remain untouched."""
    client = TestClient(app_with_cascade)
    sm = app_with_cascade.state._test_session_manager
    ps = app_with_cascade.state._test_portfolio_store

    for acct in ("sinopac-main", "2010515"):
        client.post(
            "/api/accounts",
            json={"id": acct, "broker": "sinopac", "api_key": f"k-{acct}"},
        )

    sm.add(_FakeSession("doomed", "sinopac-main", status="active"))
    sm.add(_FakeSession("survivor", "2010515", status="active"))
    ps.add(_FakePortfolio("p-doomed", "sinopac-main", "doomed"))
    ps.add(_FakePortfolio("p-survivor", "2010515", "survivor"))

    resp = client.delete("/api/accounts/sinopac-main")

    assert resp.status_code == 200
    assert "survivor" in sm.sessions
    assert "p-survivor" in ps.portfolios
    assert "doomed" not in sm.sessions
    assert "p-doomed" not in ps.portfolios


def test_delete_account_cascade_handles_stopped_session_directly(app_with_cascade):
    """A session that's already ``stopped`` must skip the status transition
    (it would fail validation) and go straight to delete."""
    client = TestClient(app_with_cascade)
    sm = app_with_cascade.state._test_session_manager

    client.post(
        "/api/accounts",
        json={"id": "1839302", "broker": "sinopac", "api_key": "k"},
    )
    sm.add(_FakeSession("sess-stopped", "1839302", status="stopped"))

    resp = client.delete("/api/accounts/1839302")

    assert resp.status_code == 200
    # No status changes — the session was already stopped.
    assert sm.status_changes == []
    assert sm.deleted_sessions == ["sess-stopped"]


def test_delete_account_returns_no_cascade_when_no_dependents(app_with_cascade):
    """An account with no sessions/portfolios must still delete cleanly
    and report empty cascade lists, not None."""
    client = TestClient(app_with_cascade)
    client.post(
        "/api/accounts",
        json={"id": "lonely", "broker": "sinopac", "api_key": "k"},
    )
    resp = client.delete("/api/accounts/lonely")
    assert resp.status_code == 200
    body = resp.json()
    assert body["deleted_sessions"] == []
    assert body["deleted_portfolios"] == []
