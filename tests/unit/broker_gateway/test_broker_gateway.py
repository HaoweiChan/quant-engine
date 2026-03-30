"""Tests for broker_gateway: types, ABC, MockGateway, AccountDB, GatewayRegistry."""
from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.broker_gateway.abc import BrokerGateway
from src.broker_gateway.account_db import AccountDB
from src.broker_gateway.mock import MockGateway
from src.broker_gateway.registry import GatewayRegistry, _gsm_key
from src.broker_gateway.types import AccountConfig, AccountSnapshot


class TestBrokerGatewayABC:
    def test_cannot_instantiate_abc(self) -> None:
        with pytest.raises(TypeError):
            BrokerGateway()  # type: ignore[abstract]

    def test_incomplete_subclass_raises(self) -> None:
        class Incomplete(BrokerGateway):
            pass

        with pytest.raises(TypeError):
            Incomplete()  # type: ignore[abstract]

    def test_minimal_subclass_works(self) -> None:
        class Minimal(BrokerGateway):
            def connect(self) -> None: ...
            def disconnect(self) -> None: ...
            def _fetch_snapshot(self) -> AccountSnapshot:
                return AccountSnapshot.disconnected()
            def get_equity_history(self, days=30):
                return []
            def get_order_events_since(self, cursor: str | None):
                return [], cursor
            @property
            def broker_name(self) -> str:
                return "test"
            @property
            def is_connected(self) -> bool:
                return False

        gw = Minimal()
        assert gw.broker_name == "test"
        assert not gw.is_connected


class TestAccountSnapshot:
    def test_disconnected_sentinel(self) -> None:
        snap = AccountSnapshot.disconnected()
        assert snap.connected is False
        assert snap.equity == 0.0
        assert snap.positions == []
        assert snap.recent_fills == []
        assert snap.open_orders == []
        assert snap.continuity_cursor is None


class TestAccountConfig:
    def test_round_trip_db_row(self) -> None:
        config = AccountConfig(
            id="test-main", broker="sinopac",
            display_name="Test Account",
            gateway_class="src.broker_gateway.mock.MockGateway",
            sandbox_mode=True, demo_trading=False,
            guards={"max_drawdown_pct": 15.0, "max_margin_pct": 80.0},
            strategies=[{"slug": "atr_mean_reversion", "symbol": "TX"}],
        )
        row = config.to_db_row()
        assert row["id"] == "test-main"
        assert row["sandbox_mode"] == 1
        assert row["demo_trading"] == 0
        restored = AccountConfig.from_db_row(row)
        assert restored.id == config.id
        assert restored.broker == config.broker
        assert restored.sandbox_mode is True
        assert restored.guards == config.guards
        assert restored.strategies == config.strategies


class TestMockGateway:
    def test_always_connected(self) -> None:
        gw = MockGateway()
        assert gw.is_connected
        assert gw.broker_name == "Mock"

    def test_snapshot_has_data(self) -> None:
        gw = MockGateway(seed=123)
        snap = gw.get_account_snapshot()
        assert snap.connected is True
        assert snap.equity > 0
        assert len(snap.positions) == 2
        assert len(snap.recent_fills) >= 1
        assert len(snap.open_orders) >= 1
        assert snap.continuity_cursor is not None

    def test_equity_history_returns_points(self) -> None:
        gw = MockGateway()
        history = gw.get_equity_history(days=10)
        assert len(history) == 10
        for ts, eq in history:
            assert eq > 0

    def test_order_events_cursor_progression(self) -> None:
        gw = MockGateway(seed=777, cache_ttl=0.0)
        gw.get_account_snapshot()
        events_first, cursor_first = gw.get_order_events_since(None)
        assert len(events_first) >= 1
        assert cursor_first is not None
        events_second, cursor_second = gw.get_order_events_since(cursor_first)
        assert events_second == []
        assert cursor_second == cursor_first

    def test_equity_evolves(self) -> None:
        gw = MockGateway(seed=42)
        snap1 = gw.get_account_snapshot()
        gw.invalidate_cache()
        snap2 = gw.get_account_snapshot()
        assert snap1.equity != snap2.equity


class TestTTLCaching:
    def test_cached_snapshot_returned_within_ttl(self) -> None:
        gw = MockGateway(cache_ttl=10.0, seed=42)
        snap1 = gw.get_account_snapshot()
        snap2 = gw.get_account_snapshot()
        assert snap1.equity == snap2.equity  # same cached object

    def test_fresh_fetch_after_invalidation(self) -> None:
        gw = MockGateway(cache_ttl=10.0, seed=42)
        snap1 = gw.get_account_snapshot()
        gw.invalidate_cache()
        snap2 = gw.get_account_snapshot()
        assert snap1.equity != snap2.equity

    def test_fresh_fetch_after_ttl_expires(self) -> None:
        gw = MockGateway(cache_ttl=0.01, seed=42)
        snap1 = gw.get_account_snapshot()
        time.sleep(0.02)
        snap2 = gw.get_account_snapshot()
        assert snap1.equity != snap2.equity

    def test_fetch_exception_returns_disconnected(self) -> None:
        gw = MockGateway()
        gw.invalidate_cache()
        with patch.object(gw, "_fetch_snapshot", side_effect=ConnectionError("down")):
            snap = gw.get_account_snapshot()
        assert snap.connected is False


class TestAccountDB:
    @pytest.fixture
    def db(self, tmp_path: Path) -> AccountDB:
        return AccountDB(db_path=tmp_path / "test.db")

    def _make_config(self, id_: str = "test-acct") -> AccountConfig:
        return AccountConfig(
            id=id_, broker="mock",
            display_name="Test",
            gateway_class="src.broker_gateway.mock.MockGateway",
            guards={"max_drawdown_pct": 10.0},
        )

    def test_empty_db_returns_empty(self, db: AccountDB) -> None:
        assert db.load_all_accounts() == []

    def test_save_and_load(self, db: AccountDB) -> None:
        config = self._make_config()
        db.save_account(config)
        loaded = db.load_all_accounts()
        assert len(loaded) == 1
        assert loaded[0].id == "test-acct"
        assert loaded[0].guards["max_drawdown_pct"] == 10.0

    def test_load_single(self, db: AccountDB) -> None:
        config = self._make_config()
        db.save_account(config)
        loaded = db.load_account("test-acct")
        assert loaded is not None
        assert loaded.broker == "mock"

    def test_load_missing_returns_none(self, db: AccountDB) -> None:
        assert db.load_account("nonexistent") is None

    def test_update_overwrites(self, db: AccountDB) -> None:
        config = self._make_config()
        db.save_account(config)
        config.display_name = "Updated"
        db.update_account(config)
        loaded = db.load_account("test-acct")
        assert loaded is not None
        assert loaded.display_name == "Updated"

    def test_delete(self, db: AccountDB) -> None:
        config = self._make_config()
        db.save_account(config)
        assert db.delete_account("test-acct") is True
        assert db.load_all_accounts() == []

    def test_delete_nonexistent_returns_false(self, db: AccountDB) -> None:
        assert db.delete_account("nope") is False

    def test_multiple_accounts(self, db: AccountDB) -> None:
        db.save_account(self._make_config("acct-a"))
        db.save_account(self._make_config("acct-b"))
        db.save_account(self._make_config("acct-c"))
        accounts = db.load_all_accounts()
        assert len(accounts) == 3
        ids = [a.id for a in accounts]
        assert "acct-a" in ids
        assert "acct-c" in ids


class TestGSMNamingConvention:
    def test_simple_id(self) -> None:
        assert _gsm_key("sinopac-main", "API_KEY") == "SINOPAC_MAIN_API_KEY"

    def test_multi_hyphen(self) -> None:
        assert _gsm_key("my-crypto-acct", "API_SECRET") == "MY_CRYPTO_ACCT_API_SECRET"

    def test_already_upper(self) -> None:
        assert _gsm_key("BINANCE", "PASSWORD") == "BINANCE_PASSWORD"


class TestGatewayRegistry:
    @pytest.fixture
    def registry(self, tmp_path: Path) -> GatewayRegistry:
        db = AccountDB(db_path=tmp_path / "test.db")
        return GatewayRegistry(db=db)

    def test_empty_registry(self, registry: GatewayRegistry) -> None:
        registry.load_all()
        assert registry.account_ids == []
        assert registry.get_all_configs() == []

    def test_load_mock_gateway(self, tmp_path: Path) -> None:
        db = AccountDB(db_path=tmp_path / "test.db")
        config = AccountConfig(
            id="mock-1", broker="mock",
            display_name="Mock Account",
            gateway_class="src.broker_gateway.mock.MockGateway",
        )
        db.save_account(config)
        reg = GatewayRegistry(db=db)
        reg.load_all()
        assert "mock-1" in reg.account_ids
        gw = reg.get_gateway("mock-1")
        assert gw is not None
        assert gw.broker_name == "Mock"
        assert gw.is_connected

    def test_get_all_snapshots(self, tmp_path: Path) -> None:
        db = AccountDB(db_path=tmp_path / "test.db")
        for i in range(2):
            db.save_account(AccountConfig(
                id=f"mock-{i}", broker="mock",
                display_name=f"Mock {i}",
                gateway_class="src.broker_gateway.mock.MockGateway",
            ))
        reg = GatewayRegistry(db=db)
        reg.load_all()
        snaps = reg.get_all_snapshots()
        assert len(snaps) == 2
        for snap in snaps.values():
            assert snap.connected is True

    def test_hot_reload(self, tmp_path: Path) -> None:
        db = AccountDB(db_path=tmp_path / "test.db")
        config = AccountConfig(
            id="hr-acct", broker="mock",
            display_name="HR",
            gateway_class="src.broker_gateway.mock.MockGateway",
        )
        db.save_account(config)
        reg = GatewayRegistry(db=db)
        reg.load_all()
        gw1 = reg.get_gateway("hr-acct")
        config.display_name = "Updated"
        reg.hot_reload(config)
        gw2 = reg.get_gateway("hr-acct")
        assert gw1 is not gw2

    def test_remove(self, tmp_path: Path) -> None:
        db = AccountDB(db_path=tmp_path / "test.db")
        db.save_account(AccountConfig(
            id="rem-1", broker="mock",
            display_name="Remove",
            gateway_class="src.broker_gateway.mock.MockGateway",
        ))
        reg = GatewayRegistry(db=db)
        reg.load_all()
        assert "rem-1" in reg.account_ids
        reg.remove("rem-1")
        assert "rem-1" not in reg.account_ids
        assert reg.get_gateway("rem-1") is None

    def test_invalid_gateway_class_skipped(self, tmp_path: Path) -> None:
        db = AccountDB(db_path=tmp_path / "test.db")
        db.save_account(AccountConfig(
            id="bad-gw", broker="nonexistent",
            display_name="Bad",
            gateway_class="src.broker_gateway.nonexistent.NoSuchGateway",
        ))
        reg = GatewayRegistry(db=db)
        reg.load_all()
        assert reg.get_gateway("bad-gw") is None
