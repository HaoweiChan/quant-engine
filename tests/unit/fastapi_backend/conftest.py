"""Isolate account tests from the production trading.db."""
import pytest
import src.broker_gateway.account_db as _adb


@pytest.fixture(autouse=True)
def _isolated_account_db(tmp_path, monkeypatch):
    monkeypatch.setattr(_adb, "_DB_PATH", tmp_path / "test_trading.db")
