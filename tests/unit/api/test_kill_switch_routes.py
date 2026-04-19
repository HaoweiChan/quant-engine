"""Unit tests for /api/kill-switch routes (Phase B2).

The previous implementation called ``gw.close_all_positions(symbol)`` on
the broker gateway, which raised AttributeError silently because no
such method exists on the read-only `BrokerGateway` ABC. The new
implementation:

  - Sets `SessionManager.halt_active` and transitions session state.
  - Iterates the live pipeline's runners and routes flatten orders
    through each runner's executor (paper or live).

These tests pin both behaviours.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.routes.kill_switch import router


@pytest.fixture
def app() -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    return app


def test_halt_requires_confirmation(app: FastAPI) -> None:
    """Forgetting the confirm payload must 400 to prevent accidental
    HALT presses on the dashboard.
    """
    client = TestClient(app)
    resp = client.post("/api/kill-switch/halt", json={})
    assert resp.status_code == 422  # pydantic body validation


def test_halt_with_wrong_confirm_string(app: FastAPI) -> None:
    client = TestClient(app)
    resp = client.post("/api/kill-switch/halt", json={"confirm": "yes"})
    assert resp.status_code == 400


def test_halt_calls_session_manager_halt(app: FastAPI) -> None:
    fake_mgr = MagicMock()
    with patch("src.api.routes.kill_switch.get_session_manager", return_value=fake_mgr), \
         patch("src.api.routes.kill_switch.sync_live_pipeline"):
        client = TestClient(app)
        resp = client.post("/api/kill-switch/halt", json={"confirm": "CONFIRM"})
    assert resp.status_code == 200
    assert resp.json() == {"status": "halted"}
    fake_mgr.halt.assert_called_once()


def test_resume_calls_session_manager_resume(app: FastAPI) -> None:
    fake_mgr = MagicMock()
    with patch("src.api.routes.kill_switch.get_session_manager", return_value=fake_mgr), \
         patch("src.api.routes.kill_switch.sync_live_pipeline"):
        client = TestClient(app)
        resp = client.post("/api/kill-switch/resume", json={"confirm": "CONFIRM"})
    assert resp.status_code == 200
    assert resp.json() == {"status": "resumed"}
    fake_mgr.resume.assert_called_once()


def test_flatten_routes_orders_through_runner_executors(app: FastAPI) -> None:
    """The route must build flatten orders per runner and submit them
    through the runner's executor — not through the (read-only) broker
    gateway, and not silently dropping them.
    """
    fake_mgr = MagicMock()
    fake_runner = MagicMock()
    fake_runner.symbol = "MTX"
    # Simulate one open position so _flatten_orders_for_runner emits one order.
    pos = MagicMock()
    pos.lots = 2
    pos.contract_type = "small"
    pos.symbol = "MTX"
    pos.direction = "long"
    pos.position_id = "pos-1"
    fake_runner.positions = [pos]
    # Snapshot the executor calls
    fake_executor = MagicMock()
    fake_executor.execute = AsyncMock(return_value=[])
    fake_runner._paper_engine = fake_executor
    fake_runner._last_snapshot = None  # exercise the fallback branch

    fake_pipeline = MagicMock()
    fake_pipeline.iter_runners = MagicMock(return_value=[("session-A", fake_runner)])

    with patch("src.api.routes.kill_switch.get_session_manager", return_value=fake_mgr), \
         patch("src.api.routes.kill_switch.get_live_pipeline", return_value=fake_pipeline), \
         patch("src.api.routes.kill_switch.sync_live_pipeline"):
        client = TestClient(app)
        resp = client.post("/api/kill-switch/flatten", json={"confirm": "CONFIRM"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "flattening"
    assert body["runners_affected"] == ["session-A"]
    assert body["orders_issued"] >= 1
    fake_mgr.flatten.assert_called_once()
    fake_executor.execute.assert_awaited_once()


def test_flatten_tolerates_missing_pipeline(app: FastAPI) -> None:
    """If the live pipeline isn't available (test/CI), the flatten route
    must still set the halt state and return 200 — not crash.
    """
    fake_mgr = MagicMock()
    with patch("src.api.routes.kill_switch.get_session_manager", return_value=fake_mgr), \
         patch("src.api.routes.kill_switch.get_live_pipeline", side_effect=RuntimeError("no pipeline")), \
         patch("src.api.routes.kill_switch.sync_live_pipeline"):
        client = TestClient(app)
        resp = client.post("/api/kill-switch/flatten", json={"confirm": "CONFIRM"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "flattening"
    assert body["orders_issued"] == 0
    fake_mgr.flatten.assert_called_once()
