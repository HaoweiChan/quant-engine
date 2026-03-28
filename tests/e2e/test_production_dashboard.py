"""E2E tests for the production dashboard overhaul endpoints.

These tests exercise the FastAPI endpoints directly via TestClient,
covering global params, kill switch, heartbeat, blotter WS, and Monte Carlo.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np
import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.e2e


@pytest.fixture
def client():
    from src.api.main import app
    return TestClient(app)


# ── 9.2  Global param context: backtest accepts cost model + provenance ──

class TestGlobalParamsAcrossTabs:
    def test_backtest_accepts_cost_model_params(self, client: TestClient):
        """POST /api/backtest/run should accept slippage_bps and commission_bps."""
        payload = {
            "strategy": "atr_mean_reversion",
            "symbol": "TX",
            "start": "2025-08-01",
            "end": "2026-03-14",
            "slippage_bps": 2.5,
            "commission_bps": 1.0,
        }
        with patch("src.api.routes.backtest.run_strategy_backtest") as mock_bt:
            mock_bt.return_value = {
                "daily_returns": [0.01, -0.005, 0.003],
                "equity_curve": [2_000_000, 2_020_000, 2_010_000, 2_016_000],
                "bnh_returns": [0.005, -0.003, 0.002],
                "bnh_equity": [2_000_000, 2_010_000, 2_004_000, 2_008_000],
                "metrics": {"sharpe": 1.2, "total_return": 0.008},
                "bars_count": 100,
            }
            resp = client.post("/api/backtest/run", json=payload)
            assert resp.status_code == 200
            mock_bt.assert_called_once()
            call_kwargs = mock_bt.call_args
            assert call_kwargs.kwargs["slippage_bps"] == 2.5
            assert call_kwargs.kwargs["commission_bps"] == 1.0

    def test_backtest_accepts_provenance(self, client: TestClient):
        """POST /api/backtest/run should pass provenance through."""
        provenance = {"git_commit": "abc1234", "param_hash": "deadbeef12345678"}
        payload = {
            "strategy": "atr_mean_reversion",
            "symbol": "TX",
            "start": "2025-08-01",
            "end": "2026-03-14",
            "provenance": provenance,
        }
        with patch("src.api.routes.backtest.run_strategy_backtest") as mock_bt:
            mock_bt.return_value = {
                "daily_returns": [0.01],
                "equity_curve": [2_000_000, 2_020_000],
                "bnh_returns": [0.005],
                "bnh_equity": [2_000_000, 2_010_000],
                "metrics": {"sharpe": 1.0},
                "bars_count": 50,
            }
            resp = client.post("/api/backtest/run", json=payload)
            assert resp.status_code == 200
            assert mock_bt.call_args.kwargs["provenance"] == provenance

    def test_meta_endpoint_returns_git_commit(self, client: TestClient):
        """GET /api/meta should return git_commit and version."""
        resp = client.get("/api/meta")
        assert resp.status_code == 200
        body = resp.json()
        assert "git_commit" in body
        assert "version" in body

    def test_optimizer_accepts_cost_model(self, client: TestClient):
        """POST /api/optimizer/run should accept slippage_bps and commission_bps."""
        payload = {
            "strategy": "atr_mean_reversion",
            "param_grid": {"bb_len": [15, 20]},
            "slippage_bps": 3.0,
            "commission_bps": 1.5,
        }
        with (
            patch("src.api.routes.optimizer.start_optimizer_run") as mock_opt,
            patch("src.api.routes.optimizer.STRATEGY_REGISTRY", {"atr_mean_reversion": MagicMock(module="m", factory="f")}),
        ):
            mock_opt.return_value = True
            resp = client.post("/api/optimizer/run", json=payload)
            assert resp.status_code == 202
            assert mock_opt.call_args.kwargs["slippage_bps"] == 3.0
            assert mock_opt.call_args.kwargs["commission_bps"] == 1.5


# ── 9.3  Kill switch flow ────────────────────────────────────────────────

class TestKillSwitchFlow:
    def _mock_session_manager(self):
        mgr = MagicMock()
        mgr.halt_active = False
        return mgr

    def test_halt_requires_confirm(self, client: TestClient):
        """POST /api/kill-switch/halt without CONFIRM should 400."""
        resp = client.post("/api/kill-switch/halt", json={"confirm": "wrong"})
        assert resp.status_code == 400

    def test_halt_with_confirm(self, client: TestClient):
        """POST /api/kill-switch/halt with CONFIRM should succeed."""
        mgr = self._mock_session_manager()
        with patch("src.api.routes.kill_switch.get_session_manager", return_value=mgr):
            resp = client.post("/api/kill-switch/halt", json={"confirm": "CONFIRM"})
            assert resp.status_code == 200
            assert resp.json()["status"] == "halted"
            mgr.halt.assert_called_once()

    def test_flatten_with_confirm(self, client: TestClient):
        """POST /api/kill-switch/flatten with CONFIRM should succeed."""
        mgr = self._mock_session_manager()
        with patch("src.api.routes.kill_switch.get_session_manager", return_value=mgr):
            resp = client.post("/api/kill-switch/flatten", json={"confirm": "CONFIRM"})
            assert resp.status_code == 200
            assert resp.json()["status"] == "flattening"
            mgr.flatten.assert_called_once()

    def test_resume_with_confirm(self, client: TestClient):
        """POST /api/kill-switch/resume with CONFIRM should succeed."""
        mgr = self._mock_session_manager()
        with patch("src.api.routes.kill_switch.get_session_manager", return_value=mgr):
            resp = client.post("/api/kill-switch/resume", json={"confirm": "CONFIRM"})
            assert resp.status_code == 200
            assert resp.json()["status"] == "resumed"
            mgr.resume.assert_called_once()


# ── 9.4  Heartbeat + Blotter ─────────────────────────────────────────────

class TestHeartbeatAndBlotter:
    def test_heartbeat_endpoint(self, client: TestClient):
        """GET /api/heartbeat should return brokers list and halt_active."""
        mgr = MagicMock()
        mgr.halt_active = False
        registry = MagicMock()
        registry.list_gateways.return_value = []
        with (
            patch("src.api.routes.heartbeat.get_session_manager", return_value=mgr),
            patch("src.api.routes.heartbeat.get_gateway_registry", return_value=registry),
        ):
            resp = client.get("/api/heartbeat")
            assert resp.status_code == 200
            body = resp.json()
            assert "brokers" in body
            assert "halt_active" in body
            assert body["halt_active"] is False

    def test_blotter_websocket_connects(self, client: TestClient):
        """WS /ws/blotter should accept connections."""
        with client.websocket_connect("/ws/blotter") as ws:
            assert ws is not None

    def test_monte_carlo_endpoint(self, client: TestClient):
        """POST /api/monte-carlo should return bands and risk metrics."""
        payload = {
            "strategy": "atr_mean_reversion",
            "n_paths": 50,
            "n_days": 30,
            "method": "stationary",
        }
        fake_returns = np.random.default_rng(42).normal(0.001, 0.01, 100).tolist()
        with patch("src.api.routes.monte_carlo.run_strategy_backtest") as mock_bt:
            mock_bt.return_value = {"daily_returns": fake_returns}
            resp = client.post("/api/monte-carlo", json=payload)
            assert resp.status_code == 200
            body = resp.json()
            assert "bands" in body
            assert "var_95" in body
            assert "cvar_95" in body
            assert "prob_ruin" in body
            assert body["method"] == "stationary"
            assert body["n_paths"] == 50
            assert set(body["bands"].keys()) == {"p5", "p25", "p50", "p75", "p95"}

    def test_monte_carlo_garch_insufficient_data(self, client: TestClient):
        """POST /api/monte-carlo with GARCH and < 50 returns should 422."""
        payload = {
            "strategy": "atr_mean_reversion",
            "n_paths": 50,
            "n_days": 30,
            "method": "garch",
        }
        fake_returns = np.random.default_rng(42).normal(0.001, 0.01, 20).tolist()
        with patch("src.api.routes.monte_carlo.run_strategy_backtest") as mock_bt:
            mock_bt.return_value = {"daily_returns": fake_returns}
            resp = client.post("/api/monte-carlo", json=payload)
            assert resp.status_code == 422
            assert "GARCH" in resp.json()["detail"]
