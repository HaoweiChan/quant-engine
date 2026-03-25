"""Tests for trading_session: SessionSnapshot, SnapshotStore, SessionManager."""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pytest

from src.broker_gateway.account_db import AccountDB
from src.broker_gateway.mock import MockGateway
from src.broker_gateway.registry import GatewayRegistry
from src.broker_gateway.types import AccountConfig, LivePosition
from src.trading_session.manager import SessionManager
from src.trading_session.session import SessionSnapshot, TradingSession
from src.trading_session.store import SnapshotStore


class TestSessionSnapshotDrawdown:
    def test_zero_equity(self) -> None:
        snap = SessionSnapshot.compute(equity=0.0, peak_equity=0.0, unrealized_pnl=0.0, realized_pnl=0.0)
        assert snap.drawdown_pct == 0.0

    def test_no_drawdown_at_peak(self) -> None:
        snap = SessionSnapshot.compute(equity=1_000_000, peak_equity=1_000_000, unrealized_pnl=0, realized_pnl=0)
        assert snap.drawdown_pct == 0.0
        assert snap.peak_equity == 1_000_000

    def test_drawdown_computed_correctly(self) -> None:
        snap = SessionSnapshot.compute(equity=900_000, peak_equity=1_000_000, unrealized_pnl=0, realized_pnl=0)
        assert snap.drawdown_pct == pytest.approx(10.0)

    def test_new_high_updates_peak(self) -> None:
        snap = SessionSnapshot.compute(equity=1_100_000, peak_equity=1_000_000, unrealized_pnl=0, realized_pnl=0)
        assert snap.peak_equity == 1_100_000
        assert snap.drawdown_pct == 0.0

    def test_positions_preserved(self) -> None:
        pos = [LivePosition("TX", "long", 2, 20000, 20100, 20000, 100000)]
        snap = SessionSnapshot.compute(
            equity=1_000_000, peak_equity=1_000_000,
            unrealized_pnl=20000, realized_pnl=5000,
            positions=pos, trade_count=5,
        )
        assert len(snap.positions) == 1
        assert snap.trade_count == 5
        assert snap.unrealized_pnl == 20000


class TestTradingSession:
    def test_create_generates_id(self) -> None:
        s = TradingSession.create("acct-1", "atr_mean_reversion", "TX")
        assert len(s.session_id) > 0
        assert s.account_id == "acct-1"
        assert s.strategy_slug == "atr_mean_reversion"
        assert s.status == "active"

    def test_create_sets_initial_equity(self) -> None:
        s = TradingSession.create("acct-1", "strat", "TX", initial_equity=500_000)
        assert s.initial_equity == 500_000
        assert s.peak_equity == 500_000


class TestSnapshotStore:
    @pytest.fixture
    def store(self, tmp_path: Path) -> SnapshotStore:
        return SnapshotStore(db_path=tmp_path / "test.db")

    def test_write_and_read_equity_curve(self, store: SnapshotStore) -> None:
        session_id = "test-session-1"
        snap = SessionSnapshot.compute(
            equity=1_000_000, peak_equity=1_000_000,
            unrealized_pnl=0, realized_pnl=0, trade_count=3,
        )
        store.write_snapshot(session_id, snap)
        curve = store.get_equity_curve(session_id, days=1)
        assert len(curve) == 1
        ts, eq = curve[0]
        assert eq == 1_000_000

    def test_multiple_snapshots_ordered(self, store: SnapshotStore) -> None:
        session_id = "test-session-2"
        for eq_val in [100, 200, 300]:
            snap = SessionSnapshot.compute(
                equity=float(eq_val), peak_equity=float(eq_val),
                unrealized_pnl=0, realized_pnl=0,
            )
            store.write_snapshot(session_id, snap)
        curve = store.get_equity_curve(session_id, days=1)
        assert len(curve) == 3
        equities = [eq for _, eq in curve]
        assert equities == [100.0, 200.0, 300.0]

    def test_get_latest_snapshot(self, store: SnapshotStore) -> None:
        session_id = "test-session-3"
        for eq_val in [100, 200, 999]:
            snap = SessionSnapshot.compute(
                equity=float(eq_val), peak_equity=float(eq_val),
                unrealized_pnl=0, realized_pnl=0,
            )
            store.write_snapshot(session_id, snap)
        latest = store.get_latest_snapshot(session_id)
        assert latest is not None
        assert latest["equity"] == 999.0

    def test_get_latest_nonexistent_returns_none(self, store: SnapshotStore) -> None:
        assert store.get_latest_snapshot("no-such-session") is None

    def test_equity_curve_filters_by_days(self, store: SnapshotStore) -> None:
        session_id = "filter-session"
        snap = SessionSnapshot(
            timestamp=datetime.now() - timedelta(days=60),
            equity=1000, unrealized_pnl=0, realized_pnl=0,
            drawdown_pct=0, peak_equity=1000,
        )
        store.write_snapshot(session_id, snap)
        snap_recent = SessionSnapshot.compute(
            equity=2000, peak_equity=2000, unrealized_pnl=0, realized_pnl=0,
        )
        store.write_snapshot(session_id, snap_recent)
        # Only 30-day window should return the recent snapshot
        curve = store.get_equity_curve(session_id, days=30)
        assert len(curve) == 1
        assert curve[0][1] == 2000.0

    def test_separate_sessions_isolated(self, store: SnapshotStore) -> None:
        for sid in ["sess-a", "sess-b"]:
            snap = SessionSnapshot.compute(equity=1000, peak_equity=1000, unrealized_pnl=0, realized_pnl=0)
            store.write_snapshot(sid, snap)
        assert len(store.get_equity_curve("sess-a", days=1)) == 1
        assert len(store.get_equity_curve("sess-b", days=1)) == 1


class TestSessionManager:
    @pytest.fixture
    def setup(self, tmp_path: Path):
        db = AccountDB(db_path=tmp_path / "test.db")
        config = AccountConfig(
            id="mock-acct", broker="mock",
            display_name="Mock Account",
            gateway_class="src.broker_gateway.mock.MockGateway",
            strategies=[
                {"slug": "atr_mean_reversion", "symbol": "TX"},
                {"slug": "trend_follow", "symbol": "MTX"},
            ],
        )
        db.save_account(config)
        reg = GatewayRegistry(db=db)
        reg.load_all()
        store = SnapshotStore(db_path=tmp_path / "test.db")
        mgr = SessionManager(registry=reg, store=store)
        return mgr, reg, store

    def test_restore_creates_sessions(self, setup) -> None:
        mgr, _, _ = setup
        mgr.restore_from_config()
        sessions = mgr.get_all_sessions()
        assert len(sessions) == 2
        slugs = {s.strategy_slug for s in sessions}
        assert slugs == {"atr_mean_reversion", "trend_follow"}

    def test_create_session(self, setup) -> None:
        mgr, _, _ = setup
        session = mgr.create_session("mock-acct", "new_strat", "TX")
        assert session.status == "active"
        assert session.account_id == "mock-acct"
        assert mgr.get_session(session.session_id) is not None

    def test_get_sessions_for_account(self, setup) -> None:
        mgr, _, _ = setup
        mgr.restore_from_config()
        sessions = mgr.get_sessions_for_account("mock-acct")
        assert len(sessions) == 2
        assert all(s.account_id == "mock-acct" for s in sessions)
        assert mgr.get_sessions_for_account("nonexistent") == []

    def test_poll_all_updates_snapshots(self, setup) -> None:
        mgr, _, _ = setup
        mgr.restore_from_config()
        mgr.poll_all()
        for session in mgr.get_all_sessions():
            assert session.current_snapshot is not None
            assert session.current_snapshot.equity > 0

    def test_poll_writes_to_store(self, setup) -> None:
        mgr, _, store = setup
        mgr.restore_from_config()
        mgr.poll_all()
        for session in mgr.get_all_sessions():
            curve = store.get_equity_curve(session.session_id, days=1)
            assert len(curve) >= 1

    def test_paused_session_skipped(self, setup) -> None:
        mgr, _, _ = setup
        session = mgr.create_session("mock-acct", "paused_strat", "TX")
        session.status = "paused"
        mgr.poll_all()
        assert session.current_snapshot is None

    def test_disconnected_gateway_skips_update(self, tmp_path: Path) -> None:
        db = AccountDB(db_path=tmp_path / "test.db")
        config = AccountConfig(
            id="dc-acct", broker="mock",
            display_name="DC",
            gateway_class="src.broker_gateway.mock.MockGateway",
            strategies=[{"slug": "strat", "symbol": "TX"}],
        )
        db.save_account(config)
        reg = GatewayRegistry(db=db)
        reg.load_all()
        # Replace the real gateway with one that returns disconnected
        gw = reg.get_gateway("dc-acct")
        from unittest.mock import patch
        with patch.object(gw, "get_account_snapshot") as mock_snap:
            from src.broker_gateway.types import AccountSnapshot
            mock_snap.return_value = AccountSnapshot.disconnected()
            store = SnapshotStore(db_path=tmp_path / "test.db")
            mgr = SessionManager(registry=reg, store=store)
            mgr.restore_from_config()
            mgr.poll_all()
            for s in mgr.get_all_sessions():
                assert s.current_snapshot is None

    def test_get_equity_curve(self, setup) -> None:
        mgr, _, store = setup
        session = mgr.create_session("mock-acct", "strat", "TX")
        snap = SessionSnapshot.compute(equity=1234, peak_equity=1234, unrealized_pnl=0, realized_pnl=0)
        store.write_snapshot(session.session_id, snap)
        curve = mgr.get_equity_curve(session.session_id, days=1)
        assert len(curve) == 1
        assert curve[0][1] == 1234.0
