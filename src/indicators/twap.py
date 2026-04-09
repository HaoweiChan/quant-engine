"""Streaming Time-Weighted Average Price (TWAP).

Session-aware average that weights each bar equally.
Unlike VWAP, doesn't require volume data.
"""
from __future__ import annotations

from datetime import datetime


class TWAP:
    """Streaming session-aware TWAP.

    Resets automatically on session date change (like VWAP).
    """

    __slots__ = ("_sum", "_count", "_value", "_session_date")

    def __init__(self) -> None:
        self._sum: float = 0.0
        self._count: int = 0
        self._value: float | None = None
        self._session_date: str | None = None

    def update(
        self,
        price: float,
        timestamp: datetime | None = None,
        session_date: str | None = None,
    ) -> float:
        """Feed one price, return current TWAP.

        Parameters
        ----------
        price : float
            Bar close (or typical) price.
        timestamp : datetime, optional
            If provided, extracts date for auto-reset.
        session_date : str, optional
            Explicit session date string for reset.
        """
        date_key = session_date or (
            timestamp.strftime("%Y-%m-%d") if timestamp else None
        )
        if date_key is not None and date_key != self._session_date:
            self._sum = 0.0
            self._count = 0
            self._session_date = date_key

        self._sum += price
        self._count += 1
        self._value = self._sum / self._count
        return self._value

    @property
    def value(self) -> float | None:
        return self._value

    @property
    def ready(self) -> bool:
        return self._value is not None

    def reset(self) -> None:
        self._sum = 0.0
        self._count = 0
        self._value = None
        self._session_date = None
