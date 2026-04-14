"""Schema for isolated War Room mock tables.

These tables are distinct from production `session_snapshots` /
`account_equity_history` so mock seeding never mutates live-trading state.
Drop them with scripts/warroom_wipe_mock.py to cleanly reset mock state.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

_DB_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "trading.db"


def mock_warroom_db_path() -> Path:
    """Canonical path to the SQLite database that holds mock_* tables."""
    return _DB_PATH


_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS mock_session_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    strategy_slug TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    equity REAL NOT NULL,
    unrealized_pnl REAL NOT NULL,
    realized_pnl REAL NOT NULL,
    drawdown_pct REAL NOT NULL,
    peak_equity REAL NOT NULL,
    trade_count INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_mock_snap_sid_ts
    ON mock_session_snapshots(session_id, timestamp);

CREATE TABLE IF NOT EXISTS mock_fills (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    account_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    strategy_slug TEXT NOT NULL,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    price REAL NOT NULL,
    quantity INTEGER NOT NULL,
    fee REAL NOT NULL,
    pnl_realized REAL NOT NULL,
    is_session_close INTEGER NOT NULL DEFAULT 0,
    signal_reason TEXT NOT NULL DEFAULT '',
    triggered INTEGER NOT NULL DEFAULT 1
);

CREATE INDEX IF NOT EXISTS idx_mock_fills_sid
    ON mock_fills(session_id);

CREATE INDEX IF NOT EXISTS idx_mock_fills_acct_ts
    ON mock_fills(account_id, timestamp);

CREATE TABLE IF NOT EXISTS mock_positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    strategy_slug TEXT NOT NULL,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    quantity INTEGER NOT NULL,
    avg_entry_price REAL NOT NULL,
    current_price REAL NOT NULL,
    unrealized_pnl REAL NOT NULL,
    opened_at TEXT NOT NULL
);
"""


def ensure_mock_warroom_schema(conn: sqlite3.Connection) -> None:
    """Create mock_* tables and their indexes if they do not exist.

    Also runs lightweight migrations to add columns introduced after the initial
    schema was deployed (ALTER TABLE is idempotent via the try/except pattern
    because SQLite raises OperationalError when the column already exists).
    """
    conn.executescript(_SCHEMA_SQL)
    # Migration: add signal_reason and triggered to pre-existing mock_fills tables.
    for col, ddl in [
        ("signal_reason", "ALTER TABLE mock_fills ADD COLUMN signal_reason TEXT NOT NULL DEFAULT ''"),
        ("triggered", "ALTER TABLE mock_fills ADD COLUMN triggered INTEGER NOT NULL DEFAULT 1"),
    ]:
        existing = {row[1] for row in conn.execute("PRAGMA table_info(mock_fills)").fetchall()}
        if col not in existing:
            conn.execute(ddl)
    conn.commit()
