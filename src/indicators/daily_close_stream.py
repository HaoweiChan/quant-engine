"""Daily close stream helper for intraday bar pipelines.

Converts a stream of intraday bars (e.g. 5m) into daily-close events by
detecting calendar-date rollovers.  This is a **helper utility**, not a
tunable indicator — it carries no PARAM_SPEC and should not appear in any
strategy PARAM_SCHEMA.  Use it to feed daily-close prices into indicators
that require a separate daily timeframe (e.g. daily ATR, daily SMA).
"""
from __future__ import annotations

from datetime import date, datetime


class DailyCloseStream:
    """Emit the prior day's closing price each time the calendar date rolls over.

    Feed every intraday bar's close price via :meth:`update`.  When the date
    changes, ``update`` returns the last price seen on the *previous* day (the
    daily close).  On all other bars it returns ``None``.

    The :attr:`closes` property exposes completed daily closes as an immutable
    tuple so callers cannot accidentally mutate internal state.

    Call :meth:`reset` at session boundaries if the stream is reused across
    separate backtests or live sessions.
    """

    __slots__ = ("_last_date", "_last_price", "_daily_closes")

    def __init__(self) -> None:
        self._last_date: date | None = None
        self._last_price: float = 0.0
        self._daily_closes: list[float] = []

    def update(self, price: float, timestamp: datetime) -> float | None:
        """Feed one bar price; return prior day's close on date rollover.

        Args:
            price: Close price of the current bar.
            timestamp: Bar timestamp (timezone-aware or naive, date only used).

        Returns:
            The previous day's close price when the calendar date changes,
            ``None`` otherwise.
        """
        current_date = timestamp.date()

        if self._last_date is None:
            self._last_date = current_date
            self._last_price = price
            return None

        if current_date != self._last_date:
            daily_close = self._last_price
            self._daily_closes.append(daily_close)
            self._last_date = current_date
            self._last_price = price
            return daily_close

        self._last_price = price
        return None

    @property
    def closes(self) -> tuple[float, ...]:
        """Completed daily closes in chronological order (immutable tuple)."""
        return tuple(self._daily_closes)

    def reset(self) -> None:
        """Clear all state; call between independent backtests or sessions."""
        self._last_date = None
        self._last_price = 0.0
        self._daily_closes = []
