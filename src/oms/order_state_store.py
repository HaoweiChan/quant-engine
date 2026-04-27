"""Persistent order-state machine for crash-safe live execution.

The in-memory ``LiveExecutor._pending`` dict is lost on every Python
process restart, so an order placed-but-not-filled at the broker
becomes invisible after a crash. This module persists every order
state transition (`pending → ack → partial → filled | rejected |
cancelled`) to ``trading.db`` so the reconciler can detect orphans on
startup and the ``BrokerGateway.get_order_events_since`` continuity
cursor can be matched against local state.

The store is intentionally narrow: append-only state transitions plus
a query for non-terminal rows. It owns the ``orders`` table; nothing
else writes to it. ``LiveExecutor`` writes through every callback;
``Reconciler`` reads on startup; tests use the same DB path with a tmp
override.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import structlog

logger = structlog.get_logger(__name__)

_DEFAULT_DB_PATH = (
    Path(__file__).resolve().parent.parent.parent / "data" / "trading.db"
)

OrderStatus = (
    "pending"
    "|ack"
    "|partial"
    "|filled"
    "|rejected"
    "|cancelled"
)
_TERMINAL_STATUSES = frozenset({"filled", "rejected", "cancelled"})

_SCHEMA = """
CREATE TABLE IF NOT EXISTS orders (
    order_id           TEXT PRIMARY KEY,
    parent_position_id TEXT,
    session_id         TEXT,
    symbol             TEXT NOT NULL,
    side               TEXT NOT NULL,
    lots               REAL NOT NULL,
    price              REAL,
    status             TEXT NOT NULL,
    broker_order_id    TEXT,
    reason             TEXT,
    created_at         TEXT NOT NULL,
    updated_at         TEXT NOT NULL,
    fills_json         TEXT NOT NULL DEFAULT '[]',
    last_error         TEXT
);
CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status);
CREATE INDEX IF NOT EXISTS idx_orders_session ON orders(session_id);
"""


@dataclass
class OrderRecord:
    order_id: str
    symbol: str
    side: str
    lots: float
    status: str
    parent_position_id: str | None = None
    session_id: str | None = None
    price: float | None = None
    broker_order_id: str | None = None
    reason: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    fills: list[dict[str, Any]] = field(default_factory=list)
    last_error: str | None = None

    @property
    def is_terminal(self) -> bool:
        return self.status in _TERMINAL_STATUSES

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "OrderRecord":
        return cls(
            order_id=row["order_id"],
            symbol=row["symbol"],
            side=row["side"],
            lots=float(row["lots"]),
            status=row["status"],
            parent_position_id=row["parent_position_id"],
            session_id=row["session_id"],
            price=row["price"],
            broker_order_id=row["broker_order_id"],
            reason=row["reason"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            fills=json.loads(row["fills_json"]) if row["fills_json"] else [],
            last_error=row["last_error"],
        )


class OrderStateStore:
    """SQLite-backed store for the live order-state FSM.

    Thread-safe: all writes serialize on a per-instance lock so the
    shioaji callback thread and the asyncio executor thread don't
    interleave updates to the same order_id.
    """

    def __init__(self, db_path: Path | None = None) -> None:
        self._db_path = db_path or _DEFAULT_DB_PATH
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._conn.commit()
        self._lock = threading.Lock()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # ------------------------------------------------------------------
    # Writes
    # ------------------------------------------------------------------

    def record_placement(
        self,
        order_id: str,
        symbol: str,
        side: str,
        lots: float,
        *,
        price: float | None = None,
        parent_position_id: str | None = None,
        session_id: str | None = None,
        reason: str | None = None,
    ) -> None:
        """Insert a new order row in the ``pending`` state."""
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO orders (
                    order_id, parent_position_id, session_id, symbol, side,
                    lots, price, status, reason, created_at, updated_at, fills_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?, '[]')
                ON CONFLICT(order_id) DO UPDATE SET
                    status = 'pending', updated_at = excluded.updated_at,
                    last_error = NULL
                """,
                (
                    order_id, parent_position_id, session_id, symbol, side,
                    lots, price, reason, now, now,
                ),
            )
            self._conn.commit()
        logger.debug(
            "order_state_pending",
            order_id=order_id, symbol=symbol, side=side, lots=lots,
        )

    def record_ack(self, order_id: str, broker_order_id: str | None = None) -> None:
        self._transition(order_id, status="ack", broker_order_id=broker_order_id)

    def record_partial(
        self, order_id: str, fill_price: float, fill_qty: float,
    ) -> None:
        self._append_fill(order_id, status="partial", price=fill_price, qty=fill_qty)

    def record_filled(
        self, order_id: str, fill_price: float, fill_qty: float,
    ) -> None:
        self._append_fill(order_id, status="filled", price=fill_price, qty=fill_qty)

    def record_rejected(self, order_id: str, reason: str) -> None:
        self._transition(order_id, status="rejected", last_error=reason)

    def record_cancelled(self, order_id: str, reason: str | None = None) -> None:
        self._transition(order_id, status="cancelled", last_error=reason)

    def _transition(
        self,
        order_id: str,
        status: str,
        broker_order_id: str | None = None,
        last_error: str | None = None,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            cur = self._conn.execute("SELECT 1 FROM orders WHERE order_id = ?", (order_id,))
            if cur.fetchone() is None:
                logger.warning(
                    "order_state_transition_no_row",
                    order_id=order_id, target_status=status,
                )
                return
            sets = ["status = ?", "updated_at = ?"]
            params: list[Any] = [status, now]
            if broker_order_id is not None:
                sets.append("broker_order_id = ?")
                params.append(broker_order_id)
            if last_error is not None:
                sets.append("last_error = ?")
                params.append(last_error)
            params.append(order_id)
            self._conn.execute(
                f"UPDATE orders SET {', '.join(sets)} WHERE order_id = ?", params,
            )
            self._conn.commit()
        logger.debug("order_state_transition", order_id=order_id, status=status)

    def _append_fill(
        self, order_id: str, status: str, price: float, qty: float,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        fill_record = {"price": price, "qty": qty, "ts": now}
        with self._lock:
            cur = self._conn.execute(
                "SELECT fills_json FROM orders WHERE order_id = ?", (order_id,),
            )
            row = cur.fetchone()
            if row is None:
                logger.warning(
                    "order_state_fill_no_row", order_id=order_id, status=status,
                )
                return
            fills = json.loads(row["fills_json"]) if row["fills_json"] else []
            fills.append(fill_record)
            self._conn.execute(
                """
                UPDATE orders
                SET status = ?, updated_at = ?, fills_json = ?
                WHERE order_id = ?
                """,
                (status, now, json.dumps(fills), order_id),
            )
            self._conn.commit()
        logger.debug(
            "order_state_fill",
            order_id=order_id, status=status, price=price, qty=qty,
        )

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    def get(self, order_id: str) -> OrderRecord | None:
        cur = self._conn.execute(
            "SELECT * FROM orders WHERE order_id = ?", (order_id,),
        )
        row = cur.fetchone()
        return OrderRecord.from_row(row) if row else None

    def list_open(self) -> list[OrderRecord]:
        """Non-terminal rows that the reconciler must reconcile against the broker."""
        placeholders = ",".join("?" for _ in _TERMINAL_STATUSES)
        cur = self._conn.execute(
            f"SELECT * FROM orders WHERE status NOT IN ({placeholders}) "
            "ORDER BY created_at ASC",
            tuple(_TERMINAL_STATUSES),
        )
        return [OrderRecord.from_row(row) for row in cur.fetchall()]

    def list_by_session(self, session_id: str) -> list[OrderRecord]:
        cur = self._conn.execute(
            "SELECT * FROM orders WHERE session_id = ? ORDER BY created_at ASC",
            (session_id,),
        )
        return [OrderRecord.from_row(row) for row in cur.fetchall()]

    def list_by_status(self, statuses: Iterable[str]) -> list[OrderRecord]:
        statuses = list(statuses)
        if not statuses:
            return []
        placeholders = ",".join("?" for _ in statuses)
        cur = self._conn.execute(
            f"SELECT * FROM orders WHERE status IN ({placeholders}) "
            "ORDER BY created_at ASC",
            tuple(statuses),
        )
        return [OrderRecord.from_row(row) for row in cur.fetchall()]
