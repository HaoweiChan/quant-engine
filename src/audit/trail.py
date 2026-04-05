"""Immutable SHA-256 hash-chain audit trail implementation."""

from __future__ import annotations

import hashlib
import subprocess
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

_TAIPEI_TZ = timezone(timedelta(hours=8))
from typing import Any

from src.core.types import AccountState, AuditRecord, AuditConfig


class AuditStore(ABC):
    @abstractmethod
    def append(self, record: AuditRecord) -> None: ...

    @abstractmethod
    def get_range(self, start_seq: int, end_seq: int) -> list[AuditRecord]: ...

    @abstractmethod
    def get_latest(self) -> AuditRecord | None: ...

    @abstractmethod
    def count(self) -> int: ...

    @abstractmethod
    def clear(self) -> None:
        """Clear all records. Only permitted in test environments (QUANT_TESTING=1)."""
        ...


GENESIS_HASH = "0" * 64


def compute_record_hash(
    sequence_id: int,
    timestamp: datetime,
    event_type: str,
    engine_state_hash: str,
    account_state: AccountState,
    event_data: dict[str, Any],
    prev_hash: str,
) -> str:
    state_str = (
        f"{account_state.equity}:{account_state.unrealized_pnl}:{account_state.realized_pnl}"
    )
    content = f"{sequence_id}{timestamp.isoformat()}{event_type}{engine_state_hash}{state_str}{event_data}{prev_hash}"
    return hashlib.sha256(content.encode()).hexdigest()


def get_git_commit() -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError, Exception):
        pass
    return None


class AuditTrail:
    def __init__(self, store: AuditStore, config: AuditConfig | None = None) -> None:
        self._store = store
        self._config = config or AuditConfig()
        self._git_commit = get_git_commit() if self._config.include_git_commit else None

    def append(
        self,
        event_type: str,
        account: AccountState,
        event_data: dict[str, Any],
    ) -> AuditRecord | None:
        if not self._config.enabled:
            return None

        latest = self._store.get_latest()
        prev_hash = latest.record_hash if latest else GENESIS_HASH

        sequence_id = (latest.sequence_id + 1) if latest else 0

        timestamp = datetime.now(_TAIPEI_TZ)

        engine_state_hash = hashlib.sha256(
            f"{account.equity}:{account.unrealized_pnl}".encode()
        ).hexdigest()

        record_hash = compute_record_hash(
            sequence_id=sequence_id,
            timestamp=timestamp,
            event_type=event_type,
            engine_state_hash=engine_state_hash,
            account_state=account,
            event_data=event_data,
            prev_hash=prev_hash,
        )

        record = AuditRecord(
            sequence_id=sequence_id,
            timestamp=timestamp,
            event_type=event_type,
            engine_state_hash=engine_state_hash,
            account_state=account,
            event_data=event_data,
            prev_hash=prev_hash,
            record_hash=record_hash,
            git_commit=self._git_commit,
        )

        self._store.append(record)
        return record

    def verify_chain(self, start_seq: int | None = None, end_seq: int | None = None) -> bool:
        records = self._store.get_range(start_seq or 0, end_seq or self._store.count())

        if not records:
            return True

        for i, record in enumerate(records):
            expected_prev_hash = records[i - 1].record_hash if i > 0 else GENESIS_HASH
            if record.prev_hash != expected_prev_hash:
                return False

            recomputed_hash = compute_record_hash(
                sequence_id=record.sequence_id,
                timestamp=record.timestamp,
                event_type=record.event_type,
                engine_state_hash=record.engine_state_hash,
                account_state=record.account_state,
                event_data=record.event_data,
                prev_hash=record.prev_hash,
            )
            if recomputed_hash != record.record_hash:
                return False

        return True

    def get_state_at(self, sequence_id: int) -> AuditRecord | None:
        records = self._store.get_range(sequence_id, sequence_id + 1)
        return records[0] if records else None

    def replay(self, start_seq: int, end_seq: int) -> list[AuditRecord]:
        return self._store.get_range(start_seq, end_seq)

    def deterministic_replay(
        self,
        start_seq: int,
        end_seq: int,
        event_engine: Any = None,
    ) -> tuple[bool, list[AuditRecord], str | None]:
        """Replay audit records and optionally verify state through EventEngine.

        Returns (success, records, error_message).
        When event_engine is provided, each record's engine_state_hash is
        re-verified against the replayed state.
        """
        records = self._store.get_range(start_seq, end_seq)
        if not records:
            return True, [], None

        # First verify the hash chain integrity of the segment
        for i, record in enumerate(records):
            if i == 0:
                if start_seq == 0:
                    expected_prev = GENESIS_HASH
                else:
                    prev_records = self._store.get_range(start_seq - 1, start_seq)
                    expected_prev = prev_records[0].record_hash if prev_records else record.prev_hash
            else:
                expected_prev = records[i - 1].record_hash

            if record.prev_hash != expected_prev:
                return False, records, f"Chain broken at sequence {record.sequence_id}"

            recomputed = compute_record_hash(
                sequence_id=record.sequence_id,
                timestamp=record.timestamp,
                event_type=record.event_type,
                engine_state_hash=record.engine_state_hash,
                account_state=record.account_state,
                event_data=record.event_data,
                prev_hash=record.prev_hash,
            )
            if recomputed != record.record_hash:
                return False, records, f"Hash mismatch at sequence {record.sequence_id}"

        # If an engine state verifier is provided, replay through it
        if event_engine is not None:
            for record in records:
                if hasattr(event_engine, "verify_state"):
                    current_hash = event_engine.verify_state(record)
                    if current_hash != record.engine_state_hash:
                        return (
                            False,
                            records,
                            f"State divergence at sequence {record.sequence_id}: "
                            f"expected {record.engine_state_hash}, got {current_hash}",
                        )

        return True, records, None

    def verify_replay(
        self,
        start_seq: int,
        end_seq: int,
        engine_state_verifier: Any = None,
    ) -> tuple[bool, str | None]:
        records = self._store.get_range(start_seq, end_seq)

        if not records:
            return True, None

        for i, record in enumerate(records):
            expected_state = record.engine_state_hash
            if engine_state_verifier:
                current_state = engine_state_verifier(record)
                if current_state != expected_state:
                    return (
                        False,
                        f"Divergence at sequence {record.sequence_id}: expected {expected_state}, got {current_state}",
                    )

        return True, None
