"""Tests for SessionDB persistence and SessionManager lifecycle."""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from src.trading_session.session import TradingSession
from src.trading_session.session_db import SessionDB


@pytest.fixture()
def db(tmp_path: Path) -> SessionDB:
    return SessionDB(db_path=tmp_path / "test_trading.db")


class TestSessionDB:
    def test_save_and_load(self, db: SessionDB) -> None:
        s = TradingSession.create("acct-1", "ema_trend_pullback", "TX")
        db.save(s)
        loaded = db.load_all()
        assert len(loaded) == 1
        assert loaded[0].session_id == s.session_id
        assert loaded[0].account_id == "acct-1"
        assert loaded[0].strategy_slug == "ema_trend_pullback"
        assert loaded[0].symbol == "TX"
        assert loaded[0].status == "stopped"

    def test_update_status(self, db: SessionDB) -> None:
        s = TradingSession.create("acct-1", "strat-a", "TX")
        db.save(s)
        db.update_status(s.session_id, "active")
        loaded = db.load_all()
        assert loaded[0].status == "active"

    def test_update_deployed(self, db: SessionDB) -> None:
        s = TradingSession.create("acct-1", "strat-a", "TX")
        db.save(s)
        db.update_deployed(s.session_id, 42)
        loaded = db.load_all()
        assert loaded[0].deployed_candidate_id == 42

    def test_find_session(self, db: SessionDB) -> None:
        s = TradingSession.create("acct-1", "strat-a", "TX")
        db.save(s)
        found = db.find_session("acct-1", "strat-a", "TX")
        assert found is not None
        assert found.session_id == s.session_id
        missing = db.find_session("acct-1", "strat-a", "MTX")
        assert missing is None

    def test_save_upsert(self, db: SessionDB) -> None:
        s = TradingSession.create("acct-1", "strat-a", "TX")
        db.save(s)
        s.status = "active"
        db.save(s)
        loaded = db.load_all()
        assert len(loaded) == 1
        assert loaded[0].status == "active"

    def test_deployment_log(self, db: SessionDB) -> None:
        log_id = db.log_deployment(
            account_id="acct-1",
            session_id="sess-abc",
            strategy="ema_trend_pullback",
            symbol="TX",
            candidate_id=5,
            params={"bar_agg": 5, "lots": 4},
        )
        assert log_id > 0
        history = db.get_deploy_history("acct-1")
        assert len(history) == 1
        assert history[0]["candidate_id"] == 5
        assert history[0]["account_id"] == "acct-1"

    def test_deployment_log_all_accounts(self, db: SessionDB) -> None:
        db.log_deployment("a1", "s1", "strat", "TX", 1, {})
        db.log_deployment("a2", "s2", "strat", "MTX", 2, {})
        history = db.get_deploy_history()
        assert len(history) == 2

    def test_validate_transition(self) -> None:
        assert SessionDB.validate_transition("stopped", "active") is True
        assert SessionDB.validate_transition("active", "paused") is True
        assert SessionDB.validate_transition("active", "stopped") is True
        assert SessionDB.validate_transition("paused", "active") is True
        assert SessionDB.validate_transition("paused", "stopped") is True
        assert SessionDB.validate_transition("stopped", "paused") is False
        assert SessionDB.validate_transition("stopped", "stopped") is False


class TestSessionManagerLifecycle:
    def test_create_and_restore(self, tmp_path: Path) -> None:
        from unittest.mock import MagicMock
        from src.trading_session.manager import SessionManager

        registry = MagicMock()
        registry.get_all_configs.return_value = []
        db = SessionDB(db_path=tmp_path / "test.db")
        mgr = SessionManager(registry=registry, session_db=db)
        s = mgr.create_session("acct-1", "strat-a", "TX")
        assert s.status == "stopped"

        # Create a new manager and restore
        mgr2 = SessionManager(registry=registry, session_db=db)
        mgr2.restore_from_db()
        assert len(mgr2.get_all_sessions()) == 1
        restored = mgr2.get_session(s.session_id)
        assert restored is not None
        assert restored.account_id == "acct-1"

    def test_set_status_valid(self, tmp_path: Path) -> None:
        from unittest.mock import MagicMock
        from src.trading_session.manager import SessionManager

        registry = MagicMock()
        registry.get_all_configs.return_value = []
        db = SessionDB(db_path=tmp_path / "test.db")
        mgr = SessionManager(registry=registry, session_db=db)
        s = mgr.create_session("acct-1", "strat-a", "TX")
        mgr.set_status(s.session_id, "active")
        assert mgr.get_session(s.session_id).status == "active"

    def test_set_status_invalid(self, tmp_path: Path) -> None:
        from unittest.mock import MagicMock
        from src.trading_session.manager import SessionManager

        registry = MagicMock()
        registry.get_all_configs.return_value = []
        db = SessionDB(db_path=tmp_path / "test.db")
        mgr = SessionManager(registry=registry, session_db=db)
        s = mgr.create_session("acct-1", "strat-a", "TX")
        with pytest.raises(ValueError, match="Invalid transition"):
            mgr.set_status(s.session_id, "paused")

    def test_deploy(self, tmp_path: Path) -> None:
        from unittest.mock import MagicMock
        from src.trading_session.manager import SessionManager

        registry = MagicMock()
        registry.get_all_configs.return_value = []
        db = SessionDB(db_path=tmp_path / "test.db")
        mgr = SessionManager(registry=registry, session_db=db)
        s = mgr.create_session("acct-1", "strat-a", "TX")
        mgr.deploy(s.session_id, 42, {"bar_agg": 5})
        assert mgr.get_session(s.session_id).deployed_candidate_id == 42
        history = db.get_deploy_history("acct-1")
        assert len(history) == 1
        assert history[0]["candidate_id"] == 42
