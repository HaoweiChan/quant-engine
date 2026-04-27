"""Regression tests for the silent-overwrite bug that wiped the 100k Sinopac
account when a second Sinopac row was added under the same default id.

These tests pin the post-fix contract:
- ``save_account`` raises ``AccountAlreadyExistsError`` on id collision
- ``update_account`` is the only path that mutates an existing row
- ``delete_account`` is idempotent and returns whether a row was deleted
"""
from __future__ import annotations

import pytest

from src.broker_gateway.account_db import AccountAlreadyExistsError, AccountDB
from src.broker_gateway.types import AccountConfig


def _config(account_id: str, *, display_name: str = "Test", broker: str = "sinopac") -> AccountConfig:
    return AccountConfig(
        id=account_id,
        broker=broker,
        display_name=display_name,
        gateway_class="src.broker_gateway.mock.MockGateway",
        sandbox_mode=False,
        guards={"max_drawdown_pct": 15},
        strategies=[],
    )


@pytest.fixture
def db(tmp_path):
    return AccountDB(db_path=tmp_path / "test_trading.db")


def test_save_account_inserts_new_row(db: AccountDB):
    db.save_account(_config("1839302", display_name="Sinopac A"))
    rows = db.load_all_accounts()
    assert len(rows) == 1
    assert rows[0].id == "1839302"
    assert rows[0].display_name == "Sinopac A"


def test_save_account_raises_on_collision(db: AccountDB):
    """The exact regression: two POSTs with the same id used to silently
    overwrite. Now they must raise so the API can return 409."""
    db.save_account(_config("1839302", display_name="Sinopac A"))
    with pytest.raises(AccountAlreadyExistsError) as exc_info:
        db.save_account(_config("1839302", display_name="Sinopac B"))
    assert exc_info.value.account_id == "1839302"
    # First row must be untouched.
    rows = db.load_all_accounts()
    assert len(rows) == 1
    assert rows[0].display_name == "Sinopac A"


def test_save_account_allows_distinct_ids_for_same_broker(db: AccountDB):
    """The user's actual workflow: two Sinopac trading accounts side by side."""
    db.save_account(_config("1839302", display_name="Sinopac (1839302)"))
    db.save_account(_config("2010515", display_name="Sinopac (2010515)"))
    ids = sorted(a.id for a in db.load_all_accounts())
    assert ids == ["1839302", "2010515"]


def test_update_account_modifies_existing_row(db: AccountDB):
    db.save_account(_config("1839302", display_name="original"))
    db.update_account(_config("1839302", display_name="renamed"))
    loaded = db.load_account("1839302")
    assert loaded is not None
    assert loaded.display_name == "renamed"


def test_update_account_no_op_on_missing_row(db: AccountDB):
    """Update must not invent rows — that would re-introduce the
    REPLACE-on-INSERT silent-create behaviour we just removed."""
    db.update_account(_config("ghost", display_name="will-not-exist"))
    assert db.load_account("ghost") is None


def test_delete_account_removes_row_and_returns_true(db: AccountDB):
    db.save_account(_config("1839302"))
    assert db.delete_account("1839302") is True
    assert db.load_account("1839302") is None


def test_delete_account_returns_false_when_missing(db: AccountDB):
    assert db.delete_account("never-existed") is False
