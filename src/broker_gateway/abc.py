"""Abstract base class for broker gateways with TTL-based caching."""
from __future__ import annotations

import time
from abc import ABC, abstractmethod
from datetime import datetime

from src.broker_gateway.types import AccountSnapshot, OrderEvent


class BrokerGateway(ABC):
    """Unified read-only interface for querying broker account state."""

    def __init__(self, cache_ttl: float = 10.0) -> None:
        self._cache_ttl = cache_ttl
        self._cached_snapshot: AccountSnapshot | None = None
        self._cache_ts: float = 0.0

    @abstractmethod
    def connect(self) -> None:
        """Establish connection to the broker API."""

    @abstractmethod
    def disconnect(self) -> None:
        """Close the broker connection."""

    @abstractmethod
    def _fetch_snapshot(self) -> AccountSnapshot:
        """Fetch a fresh account snapshot from the broker. Subclasses implement this."""

    @abstractmethod
    def get_equity_history(self, days: int = 30) -> list[tuple[datetime, float]]:
        """Return historical equity data points for the last N days."""

    @abstractmethod
    def get_order_events_since(self, cursor: str | None) -> tuple[list[OrderEvent], str | None]:
        """Return deterministic order/fill events newer than cursor and next cursor."""

    @property
    @abstractmethod
    def broker_name(self) -> str:
        """Human-readable broker identifier (e.g., 'Sinopac', 'Binance')."""

    @property
    @abstractmethod
    def is_connected(self) -> bool:
        """Whether the gateway currently has an active broker session."""

    def get_account_snapshot(self) -> AccountSnapshot:
        """Return cached or fresh account snapshot (respects TTL)."""
        now = time.monotonic()
        if self._cached_snapshot is not None and (now - self._cache_ts) < self._cache_ttl:
            return self._cached_snapshot
        try:
            snapshot = self._fetch_snapshot()
        except Exception:
            snapshot = AccountSnapshot.disconnected()
        self._cached_snapshot = snapshot
        self._cache_ts = now
        return snapshot

    def invalidate_cache(self) -> None:
        """Force next get_account_snapshot() to fetch fresh data."""
        self._cache_ts = 0.0
