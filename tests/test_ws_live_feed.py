"""Tests for the WebSocket live feed."""
from __future__ import annotations

from fastapi.testclient import TestClient

from src.api.main import app

client = TestClient(app)


def test_ws_connect_and_ping():
    with client.websocket_connect("/ws/live-feed") as ws:
        ws.send_text("ping")
        data = ws.receive_json()
        assert data["type"] == "pong"


def test_ws_backtest_progress_connect():
    with client.websocket_connect("/ws/backtest-progress") as ws:
        ws.send_text("ping")
        data = ws.receive_json()
        assert data["type"] == "pong"
