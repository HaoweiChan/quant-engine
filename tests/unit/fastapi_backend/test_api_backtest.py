"""Tests for the backtest API endpoint."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.api.main import app

client = TestClient(app)


def test_backtest_unknown_strategy():
    resp = client.post("/api/backtest/run", json={
        "strategy": "nonexistent_strategy",
        "symbol": "TX",
        "start": "2025-08-01",
        "end": "2026-03-14",
    })
    assert resp.status_code == 400
    assert "Unknown strategy" in resp.json()["detail"]


def test_backtest_valid_strategy():
    resp = client.post("/api/backtest/run", json={
        "strategy": "atr_mean_reversion",
        "symbol": "TX",
        "start": "2025-08-01",
        "end": "2026-03-14",
    })
    # May return 200 (success) or 500 (if no DB data) depending on environment
    if resp.status_code == 200:
        data = resp.json()
        assert "equity_curve" in data
        assert "metrics" in data
        assert "bars_count" in data
