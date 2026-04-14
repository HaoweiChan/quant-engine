"""MockGateway — synthetic account data for dashboard development."""
from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

_TAIPEI_TZ = timezone(timedelta(hours=8))

import numpy as np

from src.broker_gateway.abc import BrokerGateway
from src.broker_gateway.types import AccountSnapshot, Fill, LivePosition, OpenOrder, OrderEvent


def _mock_db_path() -> Path:
    return Path(__file__).resolve().parent.parent.parent / "data" / "trading.db"


def _load_mock_positions_from_db(account_id: str = "mock-dev") -> list[LivePosition]:
    db = _mock_db_path()
    if not db.exists():
        return []
    try:
        conn = sqlite3.connect(str(db))
        try:
            rows = conn.execute(
                """
                SELECT symbol, side, quantity, avg_entry_price, current_price,
                       unrealized_pnl
                FROM mock_positions WHERE account_id = ?
                """,
                (account_id,),
            ).fetchall()
        finally:
            conn.close()
    except sqlite3.Error:
        return []
    return [
        LivePosition(
            symbol=r[0],
            side=r[1],
            quantity=int(r[2]),
            avg_entry_price=float(r[3]),
            current_price=float(r[4]),
            unrealized_pnl=float(r[5]),
            margin_required=0.0,
        )
        for r in rows
    ]


def _load_mock_fills_from_db(account_id: str = "mock-dev", limit: int = 50) -> list[Fill]:
    db = _mock_db_path()
    if not db.exists():
        return []
    try:
        conn = sqlite3.connect(str(db))
        try:
            rows = conn.execute(
                """
                SELECT timestamp, symbol, side, price, quantity, fee
                FROM mock_fills
                WHERE account_id = ?
                ORDER BY timestamp DESC
                LIMIT ?
                """,
                (account_id, limit),
            ).fetchall()
        finally:
            conn.close()
    except sqlite3.Error:
        return []
    fills: list[Fill] = []
    for r in rows:
        try:
            ts = datetime.fromisoformat(r[0])
        except ValueError:
            ts = datetime.now(_TAIPEI_TZ)
        fills.append(
            Fill(
                ts,
                r[1],
                r[2],
                float(r[3]),
                float(r[4]),
                f"mock-hist-{r[0]}",
                float(r[5]),
            )
        )
    return fills


class MockGateway(BrokerGateway):
    """Always-connected gateway returning synthetic data for dev/testing."""

    def __init__(
        self,
        initial_equity: float = 2_000_000.0,
        seed: int = 42,
        cache_ttl: float = 5.0,
    ) -> None:
        super().__init__(cache_ttl=cache_ttl)
        self._initial = initial_equity
        self._rng = np.random.default_rng(seed)
        self._equity_path: list[float] = [initial_equity]
        self._step = 0
        self._cursor = 0
        self._events: list[OrderEvent] = []

    @property
    def broker_name(self) -> str:
        return "Mock"

    @property
    def is_connected(self) -> bool:
        return True

    def connect(self) -> None:
        pass

    def disconnect(self) -> None:
        pass

    def _fetch_snapshot(self) -> AccountSnapshot:
        self._step += 1
        ret = self._rng.normal(0.0003, 0.012)
        new_eq = self._equity_path[-1] * (1 + ret)
        self._equity_path.append(new_eq)
        peak = max(self._equity_path)
        dd = (peak - new_eq) / peak * 100 if peak > 0 else 0.0
        use_seeded = os.environ.get("QUANT_WARROOM_SEED") == "1"
        positions: list[LivePosition] = []
        fills: list[Fill] = []
        if use_seeded:
            positions = _load_mock_positions_from_db("mock-dev")
            fills = _load_mock_fills_from_db("mock-dev", limit=50)
        if not positions:
            positions = [
                LivePosition("TX", "long", 3, 20150.0, 20150.0 + self._rng.normal(0, 100),
                             self._rng.normal(20000, 15000), 400_000.0),
                LivePosition("MTX", "long", 4, 20450.0, 20450.0 + self._rng.normal(0, 80),
                             self._rng.normal(8000, 5000), 50_000.0),
            ]
        unrealized = sum(p.unrealized_pnl for p in positions)
        margin_used = sum(getattr(p, "margin_required", 0.0) for p in positions)
        if not fills:
            fills = [
                Fill(datetime.now(_TAIPEI_TZ) - timedelta(minutes=int(self._rng.integers(5, 120))),
                     "TX", "buy", 20100.0 + self._rng.normal(0, 50), 1.0, f"mock-{self._step}", 25.0),
            ]
        open_orders = [
            OpenOrder(
                order_id=f"open-{self._step}",
                symbol="TX",
                side="buy",
                quantity=1.0,
                remaining_quantity=1.0,
                limit_price=20000.0,
                status="submitted",
                updated_at=datetime.now(_TAIPEI_TZ),
            ),
        ]
        self._cursor += 1
        self._events.append(
            OrderEvent(
                broker_event_id=f"evt-{self._cursor}",
                order_id=f"open-{self._step}",
                event_type="ack",
                price=None,
                quantity=1.0,
                timestamp=datetime.now(_TAIPEI_TZ),
            )
        )
        return AccountSnapshot(
            connected=True,
            timestamp=datetime.now(_TAIPEI_TZ),
            equity=new_eq,
            cash=new_eq - margin_used,
            unrealized_pnl=unrealized,
            realized_pnl_today=self._rng.normal(5000, 20000),
            margin_used=margin_used,
            margin_available=new_eq - margin_used,
            positions=positions,
            recent_fills=fills,
            open_orders=open_orders,
            continuity_cursor=str(self._cursor),
        )

    def get_equity_history(self, days: int = 30) -> list[tuple[datetime, float]]:
        rng = np.random.default_rng(99)
        eq = self._initial
        result: list[tuple[datetime, float]] = []
        now = datetime.now(_TAIPEI_TZ)
        for i in range(days):
            eq *= 1 + rng.normal(0.0003, 0.012)
            result.append((now - timedelta(days=days - i), eq))
        return result

    def get_order_events_since(self, cursor: str | None) -> tuple[list[OrderEvent], str | None]:
        if cursor is None:
            return list(self._events), str(self._cursor)
        try:
            cursor_id = int(cursor)
        except ValueError:
            return [], str(self._cursor)
        events = [
            event for event in self._events
            if int(event.broker_event_id.split("-")[-1]) > cursor_id
        ]
        return events, str(self._cursor)
