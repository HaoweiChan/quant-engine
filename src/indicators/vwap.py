"""Streaming Volume-Weighted Average Price (VWAP).

Resets on session boundary (date change). Matches the _update_vwap pattern
used across ta_orb, keltner_vwap_breakout, atr_mean_reversion, etc.
"""
from __future__ import annotations

from datetime import date, datetime


PARAM_SPEC: dict[str, dict] = {}


class VWAP:
    """Session-resetting VWAP.

    Automatically resets cumulative sums when the date portion of the
    timestamp changes. For TAIFEX night sessions that span midnight,
    callers should pass the *session date* (the date the session opened),
    not the wall-clock date.
    """

    __slots__ = ("_cum_pv", "_cum_vol", "_session_date", "_value")

    def __init__(self) -> None:
        self._cum_pv = 0.0
        self._cum_vol = 0.0
        self._session_date: date | None = None
        self._value: float | None = None

    def update(
        self,
        price: float,
        volume: float,
        timestamp: datetime | None = None,
        session_date: date | None = None,
    ) -> float | None:
        """Feed one bar and return current VWAP.

        Pass either ``timestamp`` (date extracted automatically) or
        ``session_date`` for explicit session control.
        """
        sd = session_date if session_date is not None else (
            timestamp.date() if timestamp is not None else None
        )
        if sd is not None and sd != self._session_date:
            self._cum_pv = 0.0
            self._cum_vol = 0.0
            self._session_date = sd

        vol = max(volume, 0.0)
        self._cum_pv += price * vol
        self._cum_vol += vol
        self._value = self._cum_pv / self._cum_vol if self._cum_vol > 0 else None
        return self._value

    @property
    def value(self) -> float | None:
        return self._value

    @property
    def ready(self) -> bool:
        return self._value is not None

    def reset(self) -> None:
        self._cum_pv = 0.0
        self._cum_vol = 0.0
        self._session_date = None
        self._value = None
