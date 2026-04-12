"""SQLite persistence for trading sessions and deployment log."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone, timedelta

_TAIPEI_TZ = timezone(timedelta(hours=8))
from pathlib import Path
from typing import Any

import structlog

from src.trading_session.session import TradingSession

logger = structlog.get_logger(__name__)

_DB_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "trading.db"

_SESSION_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    session_id            TEXT PRIMARY KEY,
    account_id            TEXT NOT NULL,
    strategy_slug         TEXT NOT NULL,
    symbol                TEXT NOT NULL,
    status                TEXT NOT NULL DEFAULT 'stopped',
    started_at            TEXT NOT NULL,
    initial_equity        REAL NOT NULL DEFAULT 0,
    peak_equity           REAL NOT NULL DEFAULT 0,
    deployed_candidate_id INTEGER,
    equity_share          REAL NOT NULL DEFAULT 1.0,
    updated_at            TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_sessions_acct_strat_sym
    ON sessions(account_id, strategy_slug, symbol);
CREATE TABLE IF NOT EXISTS deployment_log (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    deployed_at  TEXT NOT NULL,
    account_id   TEXT NOT NULL,
    session_id   TEXT NOT NULL,
    strategy     TEXT NOT NULL,
    symbol       TEXT NOT NULL,
    candidate_id INTEGER NOT NULL,
    params       TEXT NOT NULL,
    source       TEXT NOT NULL DEFAULT 'dashboard'
);
CREATE INDEX IF NOT EXISTS idx_deploy_log_acct ON deployment_log(account_id, deployed_at);
"""

_VALID_TRANSITIONS: dict[str, set[str]] = {
    "stopped": {"active"},
    "active": {"paused", "stopped"},
    "paused": {"active", "stopped"},
    "halted": {"stopped"},
    "flattening": {"stopped"},
}


class SessionDB:
    """CRUD for trading sessions and deployment log in trading.db."""

    def __init__(self, db_path: Path | None = None) -> None:
        self._db_path = db_path or _DB_PATH
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        # check_same_thread=False so FastAPI worker threads can share this
        # connection with the route handlers that mutate sessions. The DB
        # is write-light and all mutations go through the SessionManager,
        # which serializes access at the Python level.
        self._conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SESSION_SCHEMA)
        self._migrate_schema()

    def _migrate_schema(self) -> None:
        """Idempotent migrations for legacy sessions tables.

        The sessions table pre-dated the equity_share allocation field.
        Add it in place so legacy rows default to 1.0 (full allocation).
        """
        cols = {
            row["name"]
            for row in self._conn.execute("PRAGMA table_info(sessions)").fetchall()
        }
        if "equity_share" not in cols:
            self._conn.execute(
                "ALTER TABLE sessions ADD COLUMN equity_share REAL NOT NULL DEFAULT 1.0"
            )
            self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def save(self, session: TradingSession) -> None:
        now = datetime.now(_TAIPEI_TZ).isoformat()
        self._conn.execute(
            """INSERT OR REPLACE INTO sessions
               (session_id, account_id, strategy_slug, symbol, status,
                started_at, initial_equity, peak_equity, deployed_candidate_id,
                equity_share, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                session.session_id, session.account_id, session.strategy_slug,
                session.symbol, session.status, session.started_at.isoformat(),
                session.initial_equity, session.peak_equity,
                session.deployed_candidate_id, session.equity_share, now,
            ),
        )
        self._conn.commit()

    def update_status(self, session_id: str, status: str) -> None:
        now = datetime.now(_TAIPEI_TZ).isoformat()
        self._conn.execute(
            "UPDATE sessions SET status = ?, updated_at = ? WHERE session_id = ?",
            (status, now, session_id),
        )
        self._conn.commit()

    def update_deployed(self, session_id: str, candidate_id: int) -> None:
        now = datetime.now(_TAIPEI_TZ).isoformat()
        self._conn.execute(
            "UPDATE sessions SET deployed_candidate_id = ?, updated_at = ? WHERE session_id = ?",
            (candidate_id, now, session_id),
        )
        self._conn.commit()

    def update_equity_share(self, session_id: str, share: float) -> None:
        """Persist a new equity_share for the session.

        Raises ValueError if the share is outside the valid (0, 1] range.
        Call sites that need to enforce per-account sum-of-shares invariants
        should do so before calling this method.
        """
        if not (0.0 < share <= 1.0):
            raise ValueError(f"equity_share must be in (0, 1], got {share!r}")
        now = datetime.now(_TAIPEI_TZ).isoformat()
        self._conn.execute(
            "UPDATE sessions SET equity_share = ?, updated_at = ? WHERE session_id = ?",
            (share, now, session_id),
        )
        self._conn.commit()

    def sum_equity_share_for_account(
        self, account_id: str, exclude_session_id: str | None = None
    ) -> float:
        """Total equity_share for all sessions on an account.

        Used by the allocation API to validate that adding/updating a
        session's share will not push the account over 1.0.
        """
        if exclude_session_id is None:
            row = self._conn.execute(
                "SELECT COALESCE(SUM(equity_share), 0.0) FROM sessions WHERE account_id = ?",
                (account_id,),
            ).fetchone()
        else:
            row = self._conn.execute(
                "SELECT COALESCE(SUM(equity_share), 0.0) FROM sessions "
                "WHERE account_id = ? AND session_id != ?",
                (account_id, exclude_session_id),
            ).fetchone()
        return float(row[0]) if row and row[0] is not None else 0.0

    @staticmethod
    def _row_equity_share(row) -> float:
        # sqlite3.Row exposes column names via .keys() only. Pre-migration rows
        # have no equity_share column, so fall back to 1.0 (full allocation).
        if "equity_share" in row.keys():  # noqa: SIM118
            return float(row["equity_share"])
        return 1.0

    def load_all(self) -> list[TradingSession]:
        rows = self._conn.execute("SELECT * FROM sessions").fetchall()
        sessions: list[TradingSession] = []
        for r in rows:
            sessions.append(TradingSession(
                session_id=r["session_id"],
                account_id=r["account_id"],
                strategy_slug=r["strategy_slug"],
                symbol=r["symbol"],
                status=r["status"],
                started_at=datetime.fromisoformat(r["started_at"]),
                initial_equity=r["initial_equity"],
                peak_equity=r["peak_equity"],
                deployed_candidate_id=r["deployed_candidate_id"],
                equity_share=self._row_equity_share(r),
            ))
        return sessions

    def find_session(
        self, account_id: str, strategy_slug: str, symbol: str,
    ) -> TradingSession | None:
        row = self._conn.execute(
            "SELECT * FROM sessions WHERE account_id = ? AND strategy_slug = ? AND symbol = ?",
            (account_id, strategy_slug, symbol),
        ).fetchone()
        if not row:
            return None
        return TradingSession(
            session_id=row["session_id"],
            account_id=row["account_id"],
            strategy_slug=row["strategy_slug"],
            symbol=row["symbol"],
            status=row["status"],
            started_at=datetime.fromisoformat(row["started_at"]),
            initial_equity=row["initial_equity"],
            peak_equity=row["peak_equity"],
            deployed_candidate_id=row["deployed_candidate_id"],
            equity_share=self._row_equity_share(row),
        )

    def log_deployment(
        self,
        account_id: str,
        session_id: str,
        strategy: str,
        symbol: str,
        candidate_id: int,
        params: dict[str, Any],
        source: str = "dashboard",
    ) -> int:
        now = datetime.now(_TAIPEI_TZ).isoformat()
        cur = self._conn.execute(
            """INSERT INTO deployment_log
               (deployed_at, account_id, session_id, strategy, symbol, candidate_id, params, source)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (now, account_id, session_id, strategy, symbol, candidate_id, json.dumps(params), source),
        )
        self._conn.commit()
        return cur.lastrowid  # type: ignore[return-value]

    def get_deploy_history(self, account_id: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
        if account_id:
            rows = self._conn.execute(
                "SELECT * FROM deployment_log WHERE account_id = ? ORDER BY deployed_at DESC LIMIT ?",
                (account_id, limit),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM deployment_log ORDER BY deployed_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    def delete_session(self, session_id: str) -> None:
        self._conn.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))
        self._conn.commit()

    @staticmethod
    def validate_transition(current: str, target: str) -> bool:
        return target in _VALID_TRANSITIONS.get(current, set())
