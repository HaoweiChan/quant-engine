"""Tests for the OHLCV API endpoint."""
from __future__ import annotations

import pytest
from src.api.main import app
from datetime import datetime
from fastapi.testclient import TestClient

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


def test_ohlcv_returns_only_session_window_bars():
    resp = client.get("/api/ohlcv", params={
        "symbol": "TX", "start": "2026-03-01", "end": "2026-04-02", "tf_minutes": 1,
    })
    assert resp.status_code == 200
    bars = resp.json()["bars"]
    assert isinstance(bars, list)
    for bar in bars:
        ts = str(bar["timestamp"]).replace(" ", "T")
        dt = datetime.fromisoformat(ts)
        minute_of_day = dt.hour * 60 + dt.minute
        in_after_hours = minute_of_day >= 15 * 60 or minute_of_day <= 5 * 60
        in_regular = (8 * 60 + 45) <= minute_of_day <= (13 * 60 + 45)
        assert in_after_hours or in_regular, bar["timestamp"]
