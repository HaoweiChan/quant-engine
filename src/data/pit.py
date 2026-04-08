"""Point-in-Time query layer: AS_OF(knowledge_time) semantics for look-ahead-safe backtesting."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from src.data.db import MarginSnapshot


class PITQuery:
    """Builds PIT-aware queries with bi-temporal filtering."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def as_of(self, knowledge_time: datetime) -> PITQueryBuilder:
        return PITQueryBuilder(self._session, knowledge_time=knowledge_time)

    def at_event(self, event_time: datetime) -> PITQueryBuilder:
        return PITQueryBuilder(self._session, event_time=event_time)

    def range(self, start: datetime, end: datetime) -> PITQueryBuilder:
        return PITQueryBuilder(self._session, range_start=start, range_end=end)


class PITQueryBuilder:
    """Builds filtered queries for margin snapshots with PIT semantics."""

    def __init__(
        self,
        session: Session,
        knowledge_time: datetime | None = None,
        event_time: datetime | None = None,
        range_start: datetime | None = None,
        range_end: datetime | None = None,
    ) -> None:
        self._session = session
        self._knowledge_time = knowledge_time
        self._event_time = event_time
        self._range_start = range_start
        self._range_end = range_end

    def get_margin(self, symbol: str) -> MarginSnapshot | None:
        q = self._session.query(MarginSnapshot).filter(MarginSnapshot.symbol == symbol)
        if self._knowledge_time is not None:
            q = q.filter(
                (MarginSnapshot.knowledge_time.is_(None))
                | (MarginSnapshot.knowledge_time <= self._knowledge_time)
            )
        if self._event_time is not None:
            q = q.filter(MarginSnapshot.scraped_at <= self._event_time)
        if self._range_start is not None:
            q = q.filter(MarginSnapshot.scraped_at >= self._range_start)
        if self._range_end is not None:
            q = q.filter(MarginSnapshot.scraped_at <= self._range_end)
        return q.order_by(MarginSnapshot.scraped_at.desc()).first()

    def get_margin_history(self, symbol: str) -> list[MarginSnapshot]:
        q = self._session.query(MarginSnapshot).filter(MarginSnapshot.symbol == symbol)
        if self._knowledge_time is not None:
            q = q.filter(
                (MarginSnapshot.knowledge_time.is_(None))
                | (MarginSnapshot.knowledge_time <= self._knowledge_time)
            )
        if self._range_start is not None:
            q = q.filter(MarginSnapshot.scraped_at >= self._range_start)
        if self._range_end is not None:
            q = q.filter(MarginSnapshot.scraped_at <= self._range_end)
        return list(q.order_by(MarginSnapshot.scraped_at.asc()).all())
