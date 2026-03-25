"""Tests for the strategies API endpoint."""
from __future__ import annotations

from fastapi.testclient import TestClient

from src.api.main import app

client = TestClient(app)


def test_list_strategies():
    resp = client.get("/api/strategies")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) >= 1
    for strat in data:
        assert "slug" in strat
        assert "name" in strat
        assert "param_grid" in strat
