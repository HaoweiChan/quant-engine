"""End-to-end tests for the accounts CRUD endpoints — pin the post-refactor
contract:
- POST /api/accounts requires an explicit non-empty id
- POST returns 409 on id collision (no silent overwrite)
- DELETE /api/accounts/{id} removes the DB row AND every credential the
  registry stored under that id (GSM cascade)
"""
from __future__ import annotations

from unittest.mock import patch

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
