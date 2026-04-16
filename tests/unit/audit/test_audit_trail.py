"""Tests for audit trail hash chain and storage."""

from __future__ import annotations

import os
import tempfile
from datetime import datetime

from src.audit.store import AuditStore, SQLiteAuditStore
from src.audit.trail import (
    GENESIS_HASH,
    AuditTrail,
    compute_record_hash,
    get_git_commit,
)
from src.core.types import AccountState, AuditConfig, AuditRecord


class InMemoryAuditStore(AuditStore):
    def __init__(self) -> None:
        self._records: list[AuditRecord] = []

    def append(self, record: AuditRecord) -> None:
        self._records.append(record)

    def get_range(self, start_seq: int, end_seq: int) -> list[AuditRecord]:
        return [r for r in self._records if start_seq <= r.sequence_id < end_seq]

    def get_latest(self) -> AuditRecord | None:
        return self._records[-1] if self._records else None

    def count(self) -> int:
        return len(self._records)

    def clear(self) -> None:
        self._records.clear()


class TestHashChainIntegrity:
    def test_genesis_hash_is_64_zeros(self):
        assert GENESIS_HASH == "0" * 64

    def test_compute_record_hash_deterministic(self):
        account = AccountState(
            equity=1000000.0,
            unrealized_pnl=0.0,
            realized_pnl=0.0,
            margin_used=0.0,
            margin_available=1000000.0,
            margin_ratio=0.0,
            drawdown_pct=0.0,
            positions=[],
            timestamp=datetime.now(),
        )
        hash1 = compute_record_hash(
            sequence_id=0,
            timestamp=datetime(2024, 1, 1, 9, 0, 0),
            event_type="test_event",
            engine_state_hash="abc123",
            account_state=account,
            event_data={"key": "value"},
            prev_hash=GENESIS_HASH,
        )
        hash2 = compute_record_hash(
            sequence_id=0,
            timestamp=datetime(2024, 1, 1, 9, 0, 0),
            event_type="test_event",
            engine_state_hash="abc123",
            account_state=account,
            event_data={"key": "value"},
            prev_hash=GENESIS_HASH,
        )
        assert hash1 == hash2
        assert len(hash1) == 64

    def test_different_input_produces_different_hash(self):
        account1 = AccountState(
            equity=1000000.0,
            unrealized_pnl=0.0,
            realized_pnl=0.0,
            margin_used=0.0,
            margin_available=1000000.0,
            margin_ratio=0.0,
            drawdown_pct=0.0,
            positions=[],
            timestamp=datetime.now(),
        )
        account2 = AccountState(
            equity=2000000.0,
            unrealized_pnl=0.0,
            realized_pnl=0.0,
            margin_used=0.0,
            margin_available=2000000.0,
            margin_ratio=0.0,
            drawdown_pct=0.0,
            positions=[],
            timestamp=datetime.now(),
        )
        hash1 = compute_record_hash(
            sequence_id=0,
            timestamp=datetime(2024, 1, 1, 9, 0, 0),
            event_type="test_event",
            engine_state_hash="abc123",
            account_state=account1,
            event_data={},
            prev_hash=GENESIS_HASH,
        )
        hash2 = compute_record_hash(
            sequence_id=0,
            timestamp=datetime(2024, 1, 1, 9, 0, 0),
            event_type="test_event",
            engine_state_hash="abc123",
            account_state=account2,
            event_data={},
            prev_hash=GENESIS_HASH,
        )
        assert hash1 != hash2


class TestAuditTrailAppend:
    def test_append_creates_record(self):
        store = InMemoryAuditStore()
        trail = AuditTrail(store)

        account = AccountState(
            equity=1000000.0,
            unrealized_pnl=0.0,
            realized_pnl=0.0,
            margin_used=0.0,
            margin_available=1000000.0,
            margin_ratio=0.0,
            drawdown_pct=0.0,
            positions=[],
            timestamp=datetime.now(),
        )
        record = trail.append("test_event", account, {"key": "value"})

        assert record is not None
        assert record.sequence_id == 0
        assert record.event_type == "test_event"
        assert record.prev_hash == GENESIS_HASH

    def test_append_increments_sequence(self):
        store = InMemoryAuditStore()
        trail = AuditTrail(store)

        account = AccountState(
            equity=1000000.0,
            unrealized_pnl=0.0,
            realized_pnl=0.0,
            margin_used=0.0,
            margin_available=1000000.0,
            margin_ratio=0.0,
            drawdown_pct=0.0,
            positions=[],
            timestamp=datetime.now(),
        )
        record1 = trail.append("event1", account, {})
        record2 = trail.append("event2", account, {})
        record3 = trail.append("event3", account, {})

        assert record1.sequence_id == 0
        assert record2.sequence_id == 1
        assert record3.sequence_id == 2

    def test_prev_hash_links_to_previous_record(self):
        store = InMemoryAuditStore()
        trail = AuditTrail(store)

        account = AccountState(
            equity=1000000.0,
            unrealized_pnl=0.0,
            realized_pnl=0.0,
            margin_used=0.0,
            margin_available=1000000.0,
            margin_ratio=0.0,
            drawdown_pct=0.0,
            positions=[],
            timestamp=datetime.now(),
        )
        record1 = trail.append("event1", account, {})
        record2 = trail.append("event2", account, {})

        assert record1.prev_hash == GENESIS_HASH
        assert record2.prev_hash == record1.record_hash


class TestChainVerification:
    def test_verify_chain_returns_true_for_valid_chain(self):
        store = InMemoryAuditStore()
        trail = AuditTrail(store)

        account = AccountState(
            equity=1000000.0,
            unrealized_pnl=0.0,
            realized_pnl=0.0,
            margin_used=0.0,
            margin_available=1000000.0,
            margin_ratio=0.0,
            drawdown_pct=0.0,
            positions=[],
            timestamp=datetime.now(),
        )
        trail.append("event1", account, {})
        trail.append("event2", account, {})
        trail.append("event3", account, {})

        assert trail.verify_chain() is True

    def test_verify_chain_empty_returns_true(self):
        store = InMemoryAuditStore()
        trail = AuditTrail(store)

        assert trail.verify_chain() is True

    def test_verify_chain_detects_tampered_record(self):
        store = InMemoryAuditStore()
        trail = AuditTrail(store)

        account = AccountState(
            equity=1000000.0,
            unrealized_pnl=0.0,
            realized_pnl=0.0,
            margin_used=0.0,
            margin_available=1000000.0,
            margin_ratio=0.0,
            drawdown_pct=0.0,
            positions=[],
            timestamp=datetime.now(),
        )
        trail.append("event1", account, {})
        trail.append("event2", account, {})

        record = store.get_latest()
        assert record is not None
        store._records[1] = AuditRecord(
            sequence_id=record.sequence_id,
            timestamp=record.timestamp,
            event_type="tampered_event",
            engine_state_hash=record.engine_state_hash,
            account_state=record.account_state,
            event_data={"tampered": True},
            prev_hash=record.prev_hash,
            record_hash="tampered_hash_0000000000000000000000000000000000000000000000000000000000",
            git_commit=record.git_commit,
        )

        assert trail.verify_chain() is False


class TestSequenceContinuity:
    def test_sequence_ids_are_sequential(self):
        store = InMemoryAuditStore()
        trail = AuditTrail(store)

        account = AccountState(
            equity=1000000.0,
            unrealized_pnl=0.0,
            realized_pnl=0.0,
            margin_used=0.0,
            margin_available=1000000.0,
            margin_ratio=0.0,
            drawdown_pct=0.0,
            positions=[],
            timestamp=datetime.now(),
        )
        for i in range(10):
            record = trail.append(f"event_{i}", account, {})
            assert record is not None
            assert record.sequence_id == i


class TestGitCommit:
    def test_git_commit_tracking(self):
        store = InMemoryAuditStore()
        trail = AuditTrail(store, AuditConfig(include_git_commit=True))

        account = AccountState(
            equity=1000000.0,
            unrealized_pnl=0.0,
            realized_pnl=0.0,
            margin_used=0.0,
            margin_available=1000000.0,
            margin_ratio=0.0,
            drawdown_pct=0.0,
            positions=[],
            timestamp=datetime.now(),
        )
        record = trail.append("test_event", account, {})

        assert record is not None
        assert record.git_commit is not None
        assert len(record.git_commit) == 40

    def test_git_commit_disabled(self):
        store = InMemoryAuditStore()
        trail = AuditTrail(store, AuditConfig(include_git_commit=False))

        account = AccountState(
            equity=1000000.0,
            unrealized_pnl=0.0,
            realized_pnl=0.0,
            margin_used=0.0,
            margin_available=1000000.0,
            margin_ratio=0.0,
            drawdown_pct=0.0,
            positions=[],
            timestamp=datetime.now(),
        )
        record = trail.append("test_event", account, {})

        assert record is not None
        assert record.git_commit is None


class TestReplay:
    def test_replay_returns_records_in_range(self):
        store = InMemoryAuditStore()
        trail = AuditTrail(store)

        account = AccountState(
            equity=1000000.0,
            unrealized_pnl=0.0,
            realized_pnl=0.0,
            margin_used=0.0,
            margin_available=1000000.0,
            margin_ratio=0.0,
            drawdown_pct=0.0,
            positions=[],
            timestamp=datetime.now(),
        )
        for i in range(10):
            trail.append(f"event_{i}", account, {})

        records = trail.replay(3, 7)
        assert len(records) == 4
        assert records[0].sequence_id == 3
        assert records[-1].sequence_id == 6


class TestSQLiteAuditStore:
    def test_sqlite_store_insert_and_retrieve(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        try:
            store = SQLiteAuditStore(db_path)
            account = AccountState(
                equity=1000000.0,
                unrealized_pnl=0.0,
                realized_pnl=0.0,
                margin_used=0.0,
                margin_available=1000000.0,
                margin_ratio=0.0,
                drawdown_pct=0.0,
                positions=[],
                timestamp=datetime.now(),
            )
            record = AuditRecord(
                sequence_id=0,
                timestamp=datetime.now(),
                event_type="test_event",
                engine_state_hash="abc123",
                account_state=account,
                event_data={"key": "value"},
                prev_hash=GENESIS_HASH,
                record_hash="0" * 64,
                git_commit=None,
            )
            store.append(record)

            retrieved = store.get_latest()
            assert retrieved is not None
            assert retrieved.sequence_id == 0
            assert retrieved.event_type == "test_event"

            store.clear()
            assert store.count() == 0
        finally:
            os.unlink(db_path)

    def test_sqlite_count(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        try:
            store = SQLiteAuditStore(db_path)
            account = AccountState(
                equity=1000000.0,
                unrealized_pnl=0.0,
                realized_pnl=0.0,
                margin_used=0.0,
                margin_available=1000000.0,
                margin_ratio=0.0,
                drawdown_pct=0.0,
                positions=[],
                timestamp=datetime.now(),
            )
            for i in range(5):
                record = AuditRecord(
                    sequence_id=i,
                    timestamp=datetime.now(),
                    event_type=f"event_{i}",
                    engine_state_hash=f"hash_{i}",
                    account_state=account,
                    event_data={},
                    prev_hash=GENESIS_HASH,
                    record_hash=f"hash_{i}".zfill(64),
                    git_commit=None,
                )
                store.append(record)

            assert store.count() == 5
        finally:
            os.unlink(db_path)

    def test_get_git_commit_returns_hash(self):
        commit = get_git_commit()
        assert commit is not None
        assert len(commit) == 40
