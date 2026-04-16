"""Tests for SessionDB persistence and SessionManager lifecycle."""
from __future__ import annotations

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


class TestEquityShareRoundTrip:
    def test_round_trip_default(self, db: SessionDB) -> None:
        s = TradingSession.create("acct-1", "strat-a", "TX")
        db.save(s)
        loaded = db.load_all()
        assert loaded[0].equity_share == 1.0

    def test_round_trip_custom(self, db: SessionDB) -> None:
        s = TradingSession.create("acct-1", "strat-a", "TX", equity_share=0.6)
        db.save(s)
        loaded = db.load_all()
        assert loaded[0].equity_share == pytest.approx(0.6)

    def test_update_equity_share(self, db: SessionDB) -> None:
        s = TradingSession.create("acct-1", "strat-a", "TX")
        db.save(s)
        db.update_equity_share(s.session_id, 0.4)
        loaded = db.find_session("acct-1", "strat-a", "TX")
        assert loaded is not None
        assert loaded.equity_share == pytest.approx(0.4)

    def test_update_equity_share_rejects_invalid(self, db: SessionDB) -> None:
        s = TradingSession.create("acct-1", "strat-a", "TX")
        db.save(s)
        with pytest.raises(ValueError):
            db.update_equity_share(s.session_id, 0.0)
        with pytest.raises(ValueError):
            db.update_equity_share(s.session_id, 1.5)

    def test_sum_equity_share_for_account(self, db: SessionDB) -> None:
        a = TradingSession.create("acct-1", "strat-a", "TX", equity_share=0.6)
        b = TradingSession.create("acct-1", "strat-b", "TX", equity_share=0.3)
        c = TradingSession.create("acct-2", "strat-c", "TX", equity_share=0.9)
        db.save(a)
        db.save(b)
        db.save(c)
        assert db.sum_equity_share_for_account("acct-1") == pytest.approx(0.9)
        assert db.sum_equity_share_for_account("acct-2") == pytest.approx(0.9)
        assert db.sum_equity_share_for_account(
            "acct-1", exclude_session_id=a.session_id
        ) == pytest.approx(0.3)

    def test_concurrent_patch_does_not_over_allocate(self, tmp_path: Path) -> None:
        """Race multiple threads against set_equity_share to confirm the
        manager's allocation lock prevents an over-allocated account.

        Without the lock, two concurrent PATCHes could each read
        other_sum=0.4 for their counterpart, both commit their own 0.7,
        and land at 1.4 > 1.0.
        """
        import threading
        from unittest.mock import MagicMock

        from src.trading_session.manager import SessionManager

        registry = MagicMock()
        registry.get_all_configs.return_value = []
        mgr_db = SessionDB(db_path=tmp_path / "race.db")
        mgr = SessionManager(registry=registry, session_db=mgr_db)

        a = mgr.create_session("acct-1", "strat-a", "TX", equity_share=0.3)
        b = mgr.create_session("acct-1", "strat-b", "TX", equity_share=0.3)

        errors: list[Exception] = []

        def try_grow(session_id: str, target: float) -> None:
            try:
                mgr.set_equity_share(session_id, target)
            except Exception as e:  # noqa: BLE001
                errors.append(e)

        # Both threads try to push to 0.7. Only one can succeed — the sum
        # of shares after one success is 0.3 + 0.7 = 1.0, so the other
        # must see overflow and be rejected.
        t1 = threading.Thread(target=try_grow, args=(a.session_id, 0.7))
        t2 = threading.Thread(target=try_grow, args=(b.session_id, 0.7))
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        # Exactly one raise: an overflow ValueError from the losing thread.
        assert len(errors) == 1, f"expected 1 overflow error, got {len(errors)}"
        assert "overflow" in str(errors[0]).lower()

        # Sum of shares held at <= 1.0 + epsilon
        total = mgr_db.sum_equity_share_for_account("acct-1")
        assert total <= 1.0 + 1e-6

    def test_legacy_schema_migrates(self, tmp_path: Path) -> None:
        """A pre-existing sessions table without equity_share should get the
        column added in place, with existing rows defaulting to 1.0."""
        import sqlite3
        db_path = tmp_path / "legacy.db"
        conn = sqlite3.connect(db_path)
        conn.executescript(
            """
            CREATE TABLE sessions (
                session_id TEXT PRIMARY KEY,
                account_id TEXT NOT NULL,
                strategy_slug TEXT NOT NULL,
                symbol TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'stopped',
                started_at TEXT NOT NULL,
                initial_equity REAL NOT NULL DEFAULT 0,
                peak_equity REAL NOT NULL DEFAULT 0,
                deployed_candidate_id INTEGER,
                updated_at TEXT NOT NULL
            );
            INSERT INTO sessions VALUES (
                'legacy-1', 'acct-1', 'strat-a', 'TX', 'stopped',
                '2024-01-01T00:00:00+08:00', 0, 0, NULL, '2024-01-01T00:00:00+08:00'
            );
            """
        )
        conn.commit()
        conn.close()

        new_db = SessionDB(db_path=db_path)
        loaded = new_db.load_all()
        assert len(loaded) == 1
        assert loaded[0].session_id == "legacy-1"
        assert loaded[0].equity_share == 1.0
