"""Tests for the accounts API endpoint."""
from __future__ import annotations

from fastapi.testclient import TestClient

from src.api.main import app

client = TestClient(app)


def test_list_accounts():
    resp = client.get("/api/accounts")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_create_account():
    resp = client.post("/api/accounts", json={
        "broker": "mock",
        "display_name": "Test Mock Account",
    })
    assert resp.status_code == 201
    data = resp.json()
    assert data["broker"] == "mock"
    assert data["display_name"] == "Test Mock Account"
    assert "id" in data


def test_get_nonexistent_account():
    resp = client.get("/api/accounts/does-not-exist-abc123")
    assert resp.status_code == 404
