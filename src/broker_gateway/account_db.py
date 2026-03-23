"""SQLite persistence for non-secret account configurations."""
from __future__ import annotations

import sqlite3
from pathlib import Path

from src.broker_gateway.types import AccountConfig

_DB_PATH = Path(__file__).resolve().parent.parent.parent / "trading.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (
    id            TEXT PRIMARY KEY,
    broker        TEXT NOT NULL,
    display_name  TEXT NOT NULL,
    gateway_class TEXT NOT NULL,
    sandbox_mode  INTEGER NOT NULL DEFAULT 0,
    demo_trading  INTEGER NOT NULL DEFAULT 0,
    guards_json   TEXT NOT NULL DEFAULT '{}',
    strategies_json TEXT NOT NULL DEFAULT '[]'
);
"""


class AccountDB:
    """CRUD operations for broker account metadata in trading.db."""

    def __init__(self, db_path: Path | None = None) -> None:
        self._db_path = db_path or _DB_PATH
        self._ensure_schema()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_schema(self) -> None:
        with self._conn() as conn:
            conn.executescript(_SCHEMA)

    def save_account(self, config: AccountConfig) -> None:
        row = config.to_db_row()
        with self._conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO accounts "
                "(id, broker, display_name, gateway_class, sandbox_mode, demo_trading, guards_json, strategies_json) "
                "VALUES (:id, :broker, :display_name, :gateway_class, :sandbox_mode, :demo_trading, :guards_json, :strategies_json)",
                row,
            )

    def load_all_accounts(self) -> list[AccountConfig]:
        with self._conn() as conn:
            rows = conn.execute("SELECT * FROM accounts ORDER BY id").fetchall()
        return [AccountConfig.from_db_row(dict(r)) for r in rows]

    def load_account(self, account_id: str) -> AccountConfig | None:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM accounts WHERE id = ?", (account_id,)).fetchone()
        return AccountConfig.from_db_row(dict(row)) if row else None

    def delete_account(self, account_id: str) -> bool:
        with self._conn() as conn:
            cursor = conn.execute("DELETE FROM accounts WHERE id = ?", (account_id,))
        return cursor.rowcount > 0

    def update_account(self, config: AccountConfig) -> None:
        self.save_account(config)
