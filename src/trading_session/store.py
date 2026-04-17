"""SQLite persistence for session and account equity snapshots."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

_TAIPEI_TZ = timezone(timedelta(hours=8))
from pathlib import Path

from src.trading_session.session import SessionSnapshot

_DB_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "trading.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS session_snapshots (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id    TEXT NOT NULL,
    timestamp     TEXT NOT NULL,
    equity        REAL NOT NULL,
    unrealized_pnl REAL NOT NULL DEFAULT 0,
    realized_pnl  REAL NOT NULL DEFAULT 0,
    drawdown_pct  REAL NOT NULL DEFAULT 0,
    peak_equity   REAL NOT NULL DEFAULT 0,
    trade_count   INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_snapshots_session_ts ON session_snapshots(session_id, timestamp);
CREATE TABLE IF NOT EXISTS account_equity_history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id  TEXT NOT NULL,
    timestamp   TEXT NOT NULL,
    equity      REAL NOT NULL,
    margin_used REAL NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_acct_equity_ts ON account_equity_history(account_id, timestamp);
CREATE TABLE IF NOT EXISTS live_fills (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp       TEXT NOT NULL,
    account_id      TEXT NOT NULL,
    session_id      TEXT NOT NULL,
    strategy_slug   TEXT NOT NULL,
    symbol          TEXT NOT NULL,
    side            TEXT NOT NULL,
    price           REAL NOT NULL,
    quantity        INTEGER NOT NULL,
    fee             REAL NOT NULL DEFAULT 0,
    pnl_realized    REAL NOT NULL DEFAULT 0,
    is_session_close INTEGER NOT NULL DEFAULT 0,
    signal_reason   TEXT NOT NULL DEFAULT '',
    slippage_bps    REAL
);
CREATE INDEX IF NOT EXISTS idx_live_fills_acct_ts ON live_fills(account_id, timestamp);
"""


class SnapshotStore:
    """Read/write session snapshots to trading.db."""

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

    def write_snapshot(self, session_id: str, snap: SessionSnapshot) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO session_snapshots "
                "(session_id, timestamp, equity, unrealized_pnl, realized_pnl, drawdown_pct, peak_equity, trade_count) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (session_id, snap.timestamp.isoformat(), snap.equity, snap.unrealized_pnl,
                 snap.realized_pnl, snap.drawdown_pct, snap.peak_equity, snap.trade_count),
            )

    def get_equity_curve(self, session_id: str, days: int = 30) -> list[tuple[datetime, float]]:
        cutoff = (datetime.now(_TAIPEI_TZ) - timedelta(days=days)).isoformat()
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT timestamp, equity FROM session_snapshots "
                "WHERE session_id = ? AND timestamp >= ? ORDER BY timestamp",
                (session_id, cutoff),
            ).fetchall()
        return [(datetime.fromisoformat(r["timestamp"]), r["equity"]) for r in rows]

    def get_latest_snapshot(self, session_id: str) -> dict | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM session_snapshots WHERE session_id = ? ORDER BY timestamp DESC LIMIT 1",
                (session_id,),
            ).fetchone()
        return dict(row) if row else None


class AccountEquityStore:
    """Records and retrieves per-account equity snapshots over time."""

    # Minimum seconds between consecutive writes for the same account (throttle)
    _MIN_INTERVAL_SECS: int = 60

    def __init__(self, db_path: Path | None = None) -> None:
        self._db_path = db_path or _DB_PATH
        self._last_write: dict[str, float] = {}
        self._ensure_schema()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_schema(self) -> None:
        with self._conn() as conn:
            conn.executescript(_SCHEMA)

    def record(self, account_id: str, equity: float, margin_used: float = 0.0) -> None:
        """Write an equity data point, throttled to once per minute per account."""
        import time
        now = time.monotonic()
        if now - self._last_write.get(account_id, 0.0) < self._MIN_INTERVAL_SECS:
            return
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO account_equity_history (account_id, timestamp, equity, margin_used) "
                "VALUES (?, ?, ?, ?)",
                (account_id, datetime.now(_TAIPEI_TZ).isoformat(), equity, margin_used),
            )
        self._last_write[account_id] = now

    def get_equity_curve(
        self, account_id: str, days: int = 30
    ) -> list[tuple[datetime, float]]:
        cutoff = (datetime.now(_TAIPEI_TZ) - timedelta(days=days)).isoformat()
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT timestamp, equity FROM account_equity_history "
                "WHERE account_id = ? AND timestamp >= ? ORDER BY timestamp",
                (account_id, cutoff),
            ).fetchall()
        return [(datetime.fromisoformat(r["timestamp"]), r["equity"]) for r in rows]

    def get_today_open(self, account_id: str) -> float | None:
        """Return the first equity value recorded today, for daily PnL calculation."""
        today = datetime.now(_TAIPEI_TZ).date().isoformat()
        with self._conn() as conn:
            row = conn.execute(
                "SELECT equity FROM account_equity_history "
                "WHERE account_id = ? AND timestamp >= ? ORDER BY timestamp LIMIT 1",
                (account_id, today),
            ).fetchone()
        return float(row["equity"]) if row else None

    def has_history(self, account_id: str) -> bool:
        """Check if account has any equity history."""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT 1 FROM account_equity_history WHERE account_id = ? LIMIT 1",
                (account_id,),
            ).fetchone()
        return row is not None

    def seed_sandbox_equity(
        self,
        account_id: str,
        days: int = 30,
        starting: float = 2_000_000.0,
        seed: int = 42,
    ) -> int:
        """Bulk-insert synthetic equity history for sandbox accounts.

        Uses direct executemany (bypasses _MIN_INTERVAL_SECS throttle).
        Caller must check has_history() first for idempotency.
        Generates one point per trading day using geometric Brownian motion.
        """
        import math
        import random

        rng = random.Random(seed)
        now = datetime.now(_TAIPEI_TZ)
        points: list[tuple[str, str, float, float]] = []
        equity = starting

        # Generate one equity point per day for the past N days
        for d in range(days, 0, -1):
            ts = now - timedelta(days=d)
            # GBM: equity *= exp((drift - 0.5*vol^2) + vol*Z)
            drift, vol = 0.0001, 0.02
            z = rng.gauss(0, 1)
            equity *= math.exp((drift - 0.5 * vol**2) + vol * z)
            points.append((account_id, ts.isoformat(), equity, 0.0))

        with self._conn() as conn:
            conn.executemany(
                "INSERT OR IGNORE INTO account_equity_history "
                "(account_id, timestamp, equity, margin_used) VALUES (?, ?, ?, ?)",
                points,
            )
        return len(points)


class FillStore:
    """Persists live execution fills to trading.db for war room display."""

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

    def record_fill(
        self,
        timestamp: str,
        account_id: str,
        session_id: str,
        strategy_slug: str,
        symbol: str,
        side: str,
        price: float,
        quantity: int,
        fee: float = 0.0,
        pnl_realized: float = 0.0,
        is_session_close: bool = False,
        signal_reason: str = "",
        slippage_bps: float | None = None,
    ) -> None:
        """Persist a single fill event."""
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO live_fills "
                "(timestamp, account_id, session_id, strategy_slug, symbol, side, "
                "price, quantity, fee, pnl_realized, is_session_close, signal_reason, slippage_bps) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    timestamp,
                    account_id,
                    session_id,
                    strategy_slug,
                    symbol,
                    side,
                    price,
                    quantity,
                    fee,
                    pnl_realized,
                    1 if is_session_close else 0,
                    signal_reason,
                    slippage_bps,
                ),
            )

    def get_recent_fills(self, account_id: str, limit: int = 200) -> list[dict]:
        """Retrieve recent fills for an account, newest first."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM live_fills WHERE account_id = ? "
                "ORDER BY timestamp DESC LIMIT ?",
                (account_id, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_fills_since(self, account_id: str, since: str, limit: int = 200) -> list[dict]:
        """Retrieve fills after a given timestamp."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM live_fills WHERE account_id = ? AND timestamp > ? "
                "ORDER BY timestamp DESC LIMIT ?",
                (account_id, since, limit),
            ).fetchall()
        return [dict(r) for r in rows]
