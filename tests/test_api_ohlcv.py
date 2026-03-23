"""Tests for the OHLCV API endpoint."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.api.main import app

client = TestClient(app)


def test_ohlcv_valid_params():
    resp = client.get("/api/ohlcv", params={
        "symbol": "TX", "start": "2025-01-01", "end": "2026-01-01", "tf_minutes": 60,
    })
    assert resp.status_code == 200
    data = resp.json()
    assert "bars" in data
    assert "count" in data
    assert isinstance(data["bars"], list)
    assert data["count"] == len(data["bars"])


def test_ohlcv_empty_result():
    resp = client.get("/api/ohlcv", params={
        "symbol": "NOSYMBOL", "start": "2000-01-01", "end": "2000-02-01", "tf_minutes": 60,
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["bars"] == []
    assert data["count"] == 0


def test_ohlcv_invalid_date():
    resp = client.get("/api/ohlcv", params={
        "symbol": "TX", "start": "not-a-date", "end": "2026-01-01", "tf_minutes": 60,
    })
    assert resp.status_code == 422
