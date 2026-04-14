#!/usr/bin/env python3
"""Rollback helper: drop all mock War Room tables.

Usage:
    python scripts/warroom_wipe_mock.py

This is safe to run repeatedly. It only touches tables prefixed with
`mock_`, leaving production `session_snapshots` / `account_equity_history`
intact.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

_DB_PATH = Path(__file__).resolve().parent.parent / "data" / "trading.db"

_DROP_SQL = """
DROP TABLE IF EXISTS mock_session_snapshots;
DROP TABLE IF EXISTS mock_fills;
DROP TABLE IF EXISTS mock_positions;
"""


def main() -> int:
    if not _DB_PATH.exists():
        print(f"[warroom_wipe_mock] no database at {_DB_PATH}; nothing to do")
        return 0
    conn = sqlite3.connect(str(_DB_PATH))
    try:
        before_counts: dict[str, int] = {}
        for table in ("mock_session_snapshots", "mock_fills", "mock_positions"):
            try:
                row = conn.execute(f"SELECT COUNT(1) FROM {table}").fetchone()
                before_counts[table] = int(row[0]) if row else 0
            except sqlite3.Error:
                before_counts[table] = 0
        conn.executescript(_DROP_SQL)
        conn.commit()
    finally:
        conn.close()
    print(f"[warroom_wipe_mock] dropped mock tables in {_DB_PATH}")
    for name, count in before_counts.items():
        print(f"  - {name}: removed {count} rows")
    return 0


if __name__ == "__main__":
    sys.exit(main())
