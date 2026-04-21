"""LivePortfolio dataclass + SQLite persistence.

A LivePortfolio groups multiple TradingSessions under a shared mode
(paper/live). Per the design in
`.claude/plans/in-our-war-room-squishy-squirrel.md`, the portfolio is
the source of truth for mode when a session is bound — see
`src.trading_session.mode_resolver.resolve_session_mode` for the
precedence ladder.

Paper portfolios additionally own an ``initial_equity`` value: the
seed capital the user chose when creating the portfolio. The live
pipeline divides this across the portfolio's runners (per
``equity_share``) so paper equity is **per-portfolio**, not summed
across the whole account.
"""
from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal

import structlog

logger = structlog.get_logger(__name__)

_TAIPEI_TZ = timezone(timedelta(hours=8))
_DB_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "trading.db"

ExecutionMode = Literal["paper", "live"]

_PORTFOLIO_SCHEMA = """
CREATE TABLE IF NOT EXISTS live_portfolios (
    portfolio_id    TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    account_id      TEXT NOT NULL,
    mode            TEXT NOT NULL CHECK (mode IN ('paper','live')),
    initial_equity  REAL,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_live_portfolios_account
    ON live_portfolios(account_id);
"""


def _ensure_initial_equity_column(conn: sqlite3.Connection) -> None:
    """Idempotent migration adding ``initial_equity`` to legacy DBs."""
    cols = {row[1] for row in conn.execute("PRAGMA table_info(live_portfolios)").fetchall()}
    if "initial_equity" not in cols:
        conn.execute("ALTER TABLE live_portfolios ADD COLUMN initial_equity REAL")
        conn.commit()


@dataclass
class LivePortfolio:
    portfolio_id: str
    name: str
    account_id: str
    mode: ExecutionMode
    created_at: datetime
    updated_at: datetime
    initial_equity: float | None = None

    def __post_init__(self) -> None:
        if self.mode not in ("paper", "live"):
            raise ValueError(f"mode must be 'paper' or 'live', got {self.mode!r}")
        if self.initial_equity is not None and self.initial_equity <= 0:
            raise ValueError(
                f"initial_equity must be positive, got {self.initial_equity!r}"
            )

    @classmethod
    def create(
        cls,
        name: str,
        account_id: str,
        mode: ExecutionMode = "paper",
        portfolio_id: str | None = None,
        initial_equity: float | None = None,
    ) -> LivePortfolio:
        now = datetime.now(_TAIPEI_TZ)
        return cls(
            portfolio_id=portfolio_id or str(uuid.uuid4()),
            name=name,
            account_id=account_id,
            mode=mode,
            created_at=now,
            updated_at=now,
            initial_equity=initial_equity,
        )


class LivePortfolioStore:
    """CRUD for live_portfolios in trading.db."""

    def __init__(self, db_path: Path | None = None) -> None:
        self._db_path = db_path or _DB_PATH
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_PORTFOLIO_SCHEMA)
        _ensure_initial_equity_column(self._conn)

    def close(self) -> None:
        self._conn.close()

    def save(self, portfolio: LivePortfolio) -> None:
        now = datetime.now(_TAIPEI_TZ).isoformat()
        portfolio.updated_at = datetime.now(_TAIPEI_TZ)
        self._conn.execute(
            """INSERT OR REPLACE INTO live_portfolios
               (portfolio_id, name, account_id, mode, initial_equity, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                portfolio.portfolio_id,
                portfolio.name,
                portfolio.account_id,
                portfolio.mode,
                portfolio.initial_equity,
                portfolio.created_at.isoformat(),
                now,
            ),
        )
        self._conn.commit()

    def update_mode(self, portfolio_id: str, new_mode: ExecutionMode) -> None:
        if new_mode not in ("paper", "live"):
            raise ValueError(f"mode must be 'paper' or 'live', got {new_mode!r}")
        now = datetime.now(_TAIPEI_TZ).isoformat()
        cursor = self._conn.execute(
            "UPDATE live_portfolios SET mode = ?, updated_at = ? WHERE portfolio_id = ?",
            (new_mode, now, portfolio_id),
        )
        self._conn.commit()
        if cursor.rowcount == 0:
            raise ValueError(f"Portfolio not found: {portfolio_id}")

    def get(self, portfolio_id: str) -> LivePortfolio | None:
        row = self._conn.execute(
            "SELECT * FROM live_portfolios WHERE portfolio_id = ?",
            (portfolio_id,),
        ).fetchone()
        if not row:
            return None
        return self._row_to_portfolio(row)

    def load_all(self) -> list[LivePortfolio]:
        rows = self._conn.execute(
            "SELECT * FROM live_portfolios ORDER BY created_at ASC"
        ).fetchall()
        return [self._row_to_portfolio(r) for r in rows]

    def load_for_account(self, account_id: str) -> list[LivePortfolio]:
        rows = self._conn.execute(
            "SELECT * FROM live_portfolios WHERE account_id = ? ORDER BY created_at ASC",
            (account_id,),
        ).fetchall()
        return [self._row_to_portfolio(r) for r in rows]

    def delete(self, portfolio_id: str) -> bool:
        cursor = self._conn.execute(
            "DELETE FROM live_portfolios WHERE portfolio_id = ?",
            (portfolio_id,),
        )
        self._conn.commit()
        return cursor.rowcount > 0

    @staticmethod
    def _row_to_portfolio(row: sqlite3.Row) -> LivePortfolio:
        keys = row.keys() if hasattr(row, "keys") else []
        initial_equity = row["initial_equity"] if "initial_equity" in keys else None
        return LivePortfolio(
            portfolio_id=row["portfolio_id"],
            name=row["name"],
            account_id=row["account_id"],
            mode=row["mode"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            initial_equity=float(initial_equity) if initial_equity is not None else None,
        )
