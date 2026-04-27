"""SQLite persistence for non-secret account configurations."""
from __future__ import annotations

import sqlite3
from pathlib import Path

from src.broker_gateway.types import AccountConfig


class AccountAlreadyExistsError(ValueError):
    """Raised when ``save_account`` is called with an id that already exists.

    The caller is expected to either pick a different id or call
    :meth:`AccountDB.update_account` if a real update was intended. The
    previous ``INSERT OR REPLACE`` form silently overwrote rows, which
    is how the original 100k Sinopac account was wiped out when a second
    Sinopac account was added under the same default id ``sinopac-main``.
    """

    def __init__(self, account_id: str) -> None:
        super().__init__(f"account '{account_id}' already exists")
        self.account_id = account_id

_DB_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "trading.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (
    id            TEXT PRIMARY KEY,
    broker        TEXT NOT NULL,
    display_name  TEXT NOT NULL,
    gateway_class TEXT NOT NULL,
    sandbox_mode  INTEGER NOT NULL DEFAULT 0,
    guards_json   TEXT NOT NULL DEFAULT '{}',
    strategies_json TEXT NOT NULL DEFAULT '[]'
);
"""


def _migrate_drop_demo_trading(conn: sqlite3.Connection) -> None:
    """Idempotent migration: collapse legacy ``demo_trading`` into ``sandbox_mode``.

    Keeps the schema clean (single connection-mode flag) without losing the
    intent of any existing row that had ``demo_trading=1`` but
    ``sandbox_mode=0``.
    """
    cols = {row[1] for row in conn.execute("PRAGMA table_info(accounts)").fetchall()}
    if "demo_trading" not in cols:
        return
    # Fold demo_trading=1 into sandbox_mode=1 for any rows that need it.
    conn.execute(
        "UPDATE accounts SET sandbox_mode = 1 "
        "WHERE demo_trading = 1 AND sandbox_mode = 0",
    )
    try:
        conn.execute("ALTER TABLE accounts DROP COLUMN demo_trading")
    except sqlite3.OperationalError:
        # SQLite < 3.35: rebuild the table.
        conn.executescript(
            """
            CREATE TABLE accounts__new (
                id            TEXT PRIMARY KEY,
                broker        TEXT NOT NULL,
                display_name  TEXT NOT NULL,
                gateway_class TEXT NOT NULL,
                sandbox_mode  INTEGER NOT NULL DEFAULT 0,
                guards_json   TEXT NOT NULL DEFAULT '{}',
                strategies_json TEXT NOT NULL DEFAULT '[]'
            );
            INSERT INTO accounts__new
                (id, broker, display_name, gateway_class, sandbox_mode,
                 guards_json, strategies_json)
            SELECT id, broker, display_name, gateway_class, sandbox_mode,
                   guards_json, strategies_json
            FROM accounts;
            DROP TABLE accounts;
            ALTER TABLE accounts__new RENAME TO accounts;
            """
        )
    conn.commit()


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
            _migrate_drop_demo_trading(conn)

    def save_account(self, config: AccountConfig) -> None:
        """Insert a brand-new account row.

        Raises :class:`AccountAlreadyExistsError` when ``config.id`` is
        already present. Callers that want to mutate an existing row
        must call :meth:`update_account` instead — the silent-overwrite
        path no longer exists at this layer.
        """
        row = config.to_db_row()
        with self._conn() as conn:
            try:
                conn.execute(
                    "INSERT INTO accounts "
                    "(id, broker, display_name, gateway_class, sandbox_mode, "
                    "guards_json, strategies_json) "
                    "VALUES (:id, :broker, :display_name, :gateway_class, "
                    ":sandbox_mode, :guards_json, :strategies_json)",
                    row,
                )
            except sqlite3.IntegrityError as exc:
                raise AccountAlreadyExistsError(config.id) from exc

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
        """Update an existing account row in place.

        Returns silently if no row matches — callers that need a hard
        existence check should call :meth:`load_account` first.
        """
        row = config.to_db_row()
        with self._conn() as conn:
            conn.execute(
                "UPDATE accounts SET broker = :broker, display_name = :display_name, "
                "gateway_class = :gateway_class, sandbox_mode = :sandbox_mode, "
                "guards_json = :guards_json, strategies_json = :strategies_json "
                "WHERE id = :id",
                row,
            )
