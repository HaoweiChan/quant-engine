"""Broker gateway data types — account snapshots, positions, fills, config."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

_TAIPEI_TZ = timezone(timedelta(hours=8))
from dataclasses import dataclass, field


@dataclass
class LivePosition:
    symbol: str
    side: str  # "long" | "short"
    quantity: float
    avg_entry_price: float
    current_price: float
    unrealized_pnl: float
    margin_required: float


@dataclass
class Fill:
    timestamp: datetime
    symbol: str
    side: str
    price: float
    quantity: float
    order_id: str
    fee: float


@dataclass
class OpenOrder:
    order_id: str
    symbol: str
    side: str
    quantity: float
    remaining_quantity: float
    limit_price: float | None
    status: str
    updated_at: datetime


@dataclass
class OrderEvent:
    broker_event_id: str
    order_id: str
    event_type: str
    price: float | None
    quantity: float | None
    timestamp: datetime


@dataclass
class AccountSnapshot:
    connected: bool
    timestamp: datetime
    equity: float
    cash: float
    unrealized_pnl: float
    realized_pnl_today: float
    margin_used: float
    margin_available: float
    positions: list[LivePosition] = field(default_factory=list)
    recent_fills: list[Fill] = field(default_factory=list)
    open_orders: list[OpenOrder] = field(default_factory=list)
    continuity_cursor: str | None = None

    @classmethod
    def disconnected(cls) -> AccountSnapshot:
        """Return a sentinel snapshot for when the broker is unreachable."""
        return cls(
            connected=False,
            timestamp=datetime.now(_TAIPEI_TZ),
            equity=0.0,
            cash=0.0,
            unrealized_pnl=0.0,
            realized_pnl_today=0.0,
            margin_used=0.0,
            margin_available=0.0,
        )


@dataclass
class AccountConfig:
    id: str
    broker: str
    display_name: str
    gateway_class: str
    sandbox_mode: bool = False
    demo_trading: bool = False
    guards: dict[str, float] = field(default_factory=dict)
    strategies: list[dict[str, str]] = field(default_factory=list)

    def to_db_row(self) -> dict:
        return {
            "id": self.id,
            "broker": self.broker,
            "display_name": self.display_name,
            "gateway_class": self.gateway_class,
            "sandbox_mode": int(self.sandbox_mode),
            "demo_trading": int(self.demo_trading),
            "guards_json": json.dumps(self.guards),
            "strategies_json": json.dumps(self.strategies),
        }

    @classmethod
    def from_db_row(cls, row: dict) -> AccountConfig:
        return cls(
            id=row["id"],
            broker=row["broker"],
            display_name=row["display_name"],
            gateway_class=row["gateway_class"],
            sandbox_mode=bool(row.get("sandbox_mode", 0)),
            demo_trading=bool(row.get("demo_trading", 0)),
            guards=json.loads(row.get("guards_json", "{}")),
            strategies=json.loads(row.get("strategies_json", "[]")),
        )
