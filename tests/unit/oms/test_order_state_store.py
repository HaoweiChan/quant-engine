"""Tests for ``src/oms/order_state_store.py`` and LiveExecutor write-through."""
from __future__ import annotations

import sqlite3

import pytest

from src.oms.order_state_store import OrderStateStore


@pytest.fixture
def store(tmp_path) -> OrderStateStore:
    s = OrderStateStore(db_path=tmp_path / "trading.db")
    yield s
    s.close()


# -- Schema --------------------------------------------------------------


class TestSchema:
    def test_table_created(self, tmp_path) -> None:
        path = tmp_path / "trading.db"
        OrderStateStore(db_path=path)
        with sqlite3.connect(str(path)) as conn:
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
        assert "orders" in tables


# -- Happy path lifecycle -----------------------------------------------


class TestHappyPath:
    def test_placement_persists_pending(self, store) -> None:
        store.record_placement(
            "OID-1", symbol="TX", side="buy", lots=1.0,
            price=20000.0, reason="entry",
        )
        rec = store.get("OID-1")
        assert rec is not None
        assert rec.status == "pending"
        assert rec.symbol == "TX"
        assert rec.side == "buy"
        assert rec.lots == 1.0
        assert rec.price == 20000.0
        assert rec.fills == []
        assert not rec.is_terminal

    def test_ack_sets_broker_id(self, store) -> None:
        store.record_placement("OID-1", symbol="TX", side="buy", lots=1.0)
        store.record_ack("OID-1", broker_order_id="SJ-XYZ")
        rec = store.get("OID-1")
        assert rec.status == "ack"
        assert rec.broker_order_id == "SJ-XYZ"

    def test_partial_then_filled(self, store) -> None:
        store.record_placement("OID-1", symbol="TX", side="buy", lots=2.0)
        store.record_partial("OID-1", fill_price=20000.0, fill_qty=1.0)
        store.record_filled("OID-1", fill_price=20001.0, fill_qty=1.0)
        rec = store.get("OID-1")
        assert rec.status == "filled"
        assert len(rec.fills) == 2
        assert rec.fills[0]["price"] == 20000.0
        assert rec.fills[1]["price"] == 20001.0
        assert rec.is_terminal

    def test_rejected_and_cancelled_are_terminal(self, store) -> None:
        store.record_placement("OID-1", symbol="TX", side="buy", lots=1.0)
        store.record_rejected("OID-1", reason="margin")
        rec = store.get("OID-1")
        assert rec.status == "rejected"
        assert rec.last_error == "margin"
        assert rec.is_terminal

        store.record_placement("OID-2", symbol="TX", side="sell", lots=1.0)
        store.record_cancelled("OID-2", reason="timeout")
        rec2 = store.get("OID-2")
        assert rec2.status == "cancelled"
        assert rec2.last_error == "timeout"
        assert rec2.is_terminal


# -- Recovery queries ---------------------------------------------------


class TestRecoveryQueries:
    def test_list_open_excludes_terminal(self, store) -> None:
        store.record_placement("O-pending", symbol="TX", side="buy", lots=1.0)
        store.record_placement("O-ack", symbol="TX", side="buy", lots=1.0)
        store.record_ack("O-ack")
        store.record_placement("O-filled", symbol="TX", side="buy", lots=1.0)
        store.record_filled("O-filled", fill_price=20000.0, fill_qty=1.0)
        store.record_placement("O-cancelled", symbol="TX", side="buy", lots=1.0)
        store.record_cancelled("O-cancelled", reason="timeout")

        open_ids = {rec.order_id for rec in store.list_open()}
        assert open_ids == {"O-pending", "O-ack"}

    def test_list_by_session(self, store) -> None:
        store.record_placement(
            "O-1", symbol="TX", side="buy", lots=1.0, session_id="sess-A",
        )
        store.record_placement(
            "O-2", symbol="TX", side="buy", lots=1.0, session_id="sess-B",
        )
        a = [r.order_id for r in store.list_by_session("sess-A")]
        b = [r.order_id for r in store.list_by_session("sess-B")]
        assert a == ["O-1"]
        assert b == ["O-2"]

    def test_list_by_status(self, store) -> None:
        store.record_placement("O-1", symbol="TX", side="buy", lots=1.0)
        store.record_placement("O-2", symbol="TX", side="buy", lots=1.0)
        store.record_filled("O-2", fill_price=20000.0, fill_qty=1.0)
        pending = store.list_by_status(["pending"])
        filled = store.list_by_status(["filled"])
        assert [r.order_id for r in pending] == ["O-1"]
        assert [r.order_id for r in filled] == ["O-2"]


# -- Crash safety --------------------------------------------------------


class TestCrashSafety:
    def test_state_survives_close_reopen(self, tmp_path) -> None:
        path = tmp_path / "trading.db"
        s1 = OrderStateStore(db_path=path)
        s1.record_placement("O-1", symbol="TX", side="buy", lots=1.0)
        s1.record_ack("O-1", broker_order_id="SJ-1")
        s1.close()
        # Simulate a process restart by opening a fresh store handle.
        s2 = OrderStateStore(db_path=path)
        rec = s2.get("O-1")
        assert rec is not None
        assert rec.status == "ack"
        assert rec.broker_order_id == "SJ-1"
        # Reconciler would see this in list_open()
        open_recs = s2.list_open()
        assert [r.order_id for r in open_recs] == ["O-1"]
        s2.close()

    def test_unknown_transition_is_logged_not_raised(self, store) -> None:
        # Non-existent order_id transition should warn, not crash, so a
        # spurious broker callback for an order we never placed doesn't
        # take down the executor.
        store.record_ack("NEVER-PLACED")
        store.record_filled("NEVER-PLACED", fill_price=1.0, fill_qty=1.0)

    def test_repeat_placement_resets_to_pending(self, store) -> None:
        # Simulates a retry path where the same order_id is reused.
        store.record_placement("O-1", symbol="TX", side="buy", lots=1.0)
        store.record_filled("O-1", fill_price=20000.0, fill_qty=1.0)
        store.record_placement("O-1", symbol="TX", side="buy", lots=1.0)
        rec = store.get("O-1")
        assert rec.status == "pending"
        assert rec.last_error is None
