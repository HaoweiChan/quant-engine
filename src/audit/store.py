"""SQLite-based audit store with append-only enforcement."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from src.core.types import AccountState, AuditRecord, AuditConfig
from src.audit.trail import AuditStore, GENESIS_HASH


class SQLiteAuditStore(AuditStore):
    def __init__(self, db_path: str = "audit.db") -> None:
        self._db_path = db_path
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._create_tables()

    def _create_tables(self) -> None:
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS audit_records (
                sequence_id INTEGER PRIMARY KEY,
                timestamp TEXT NOT NULL,
                event_type TEXT NOT NULL,
                engine_state_hash TEXT NOT NULL,
                account_equity REAL NOT NULL,
                account_unrealized_pnl REAL NOT NULL,
                account_realized_pnl REAL NOT NULL,
                account_margin_used REAL NOT NULL,
                account_margin_available REAL NOT NULL,
                account_margin_ratio REAL NOT NULL,
                account_drawdown_pct REAL NOT NULL,
                account_positions TEXT NOT NULL,
                event_data TEXT NOT NULL,
                prev_hash TEXT NOT NULL,
                record_hash TEXT NOT NULL,
                git_commit TEXT
            )
        """)
        self._conn.commit()

    def append(self, record: AuditRecord) -> None:
        positions_json = str(record.account_state.positions)
        event_data_json = str(record.event_data)

        try:
            self._conn.execute(
                """
                INSERT INTO audit_records (
                    sequence_id, timestamp, event_type, engine_state_hash,
                    account_equity, account_unrealized_pnl, account_realized_pnl,
                    account_margin_used, account_margin_available, account_margin_ratio,
                    account_drawdown_pct, account_positions, event_data,
                    prev_hash, record_hash, git_commit
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    record.sequence_id,
                    record.timestamp.isoformat(),
                    record.event_type,
                    record.engine_state_hash,
                    record.account_state.equity,
                    record.account_state.unrealized_pnl,
                    record.account_state.realized_pnl,
                    record.account_state.margin_used,
                    record.account_state.margin_available,
                    record.account_state.margin_ratio,
                    record.account_state.drawdown_pct,
                    positions_json,
                    event_data_json,
                    record.prev_hash,
                    record.record_hash,
                    record.git_commit,
                ),
            )
            self._conn.commit()
        except sqlite3.IntegrityError:
            raise ValueError("Cannot insert record with duplicate sequence_id")

    def get_range(self, start_seq: int, end_seq: int) -> list[AuditRecord]:
        cursor = self._conn.execute(
            """
            SELECT * FROM audit_records
            WHERE sequence_id >= ? AND sequence_id < ?
            ORDER BY sequence_id ASC
        """,
            (start_seq, end_seq),
        )
        rows = cursor.fetchall()
        return [self._row_to_record(row) for row in rows]

    def get_latest(self) -> AuditRecord | None:
        cursor = self._conn.execute("""
            SELECT * FROM audit_records
            ORDER BY sequence_id DESC
            LIMIT 1
        """)
        row = cursor.fetchone()
        return self._row_to_record(row) if row else None

    def count(self) -> int:
        cursor = self._conn.execute("SELECT COUNT(*) FROM audit_records")
        result = cursor.fetchone()
        return int(result[0]) if result else 0

    def clear(self) -> None:
        import os
        if not os.environ.get("QUANT_TESTING"):
            raise RuntimeError(
                "clear() is forbidden on an immutable audit store. "
                "Set QUANT_TESTING=1 for test environments only."
            )
        self._conn.execute("DELETE FROM audit_records")
        self._conn.commit()

    def _row_to_record(self, row: tuple[Any, ...]) -> AuditRecord:
        positions_str = row[11]
        import ast

        positions = ast.literal_eval(positions_str) if positions_str else []

        event_data_str = row[12]
        event_data = ast.literal_eval(event_data_str) if event_data_str else {}

        account_state = AccountState(
            equity=row[4],
            unrealized_pnl=row[5],
            realized_pnl=row[6],
            margin_used=row[7],
            margin_available=row[8],
            margin_ratio=row[9],
            drawdown_pct=row[10],
            positions=positions,
            timestamp=datetime.fromisoformat(row[1]),
        )

        return AuditRecord(
            sequence_id=row[0],
            timestamp=datetime.fromisoformat(row[1]),
            event_type=row[2],
            engine_state_hash=row[3],
            account_state=account_state,
            event_data=event_data,
            prev_hash=row[13],
            record_hash=row[14],
            git_commit=row[15],
        )
