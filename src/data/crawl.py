"""Historical OHLCV data crawl pipeline: Shioaji → validate → DB."""
from __future__ import annotations

import time
from datetime import date, timedelta

import structlog

from src.data.connector import SinopacConnector
from src.data.db import Database, OHLCVBar

logger = structlog.get_logger(__name__)

MAX_CHUNK_DAYS = 60
DEFAULT_DELAY = 1.0


def crawl_historical(
    symbol: str,
    start: date,
    end: date,
    db: Database,
    connector: SinopacConnector,
    delay: float = DEFAULT_DELAY,
    db_symbol: str | None = None,
) -> int:
    """Fetch 1-min OHLCV from Shioaji in chunks and upsert to DB.

    *symbol* is the Shioaji contract path (e.g. ``Futures.TXF.TXFR1``).
    *db_symbol* is the short name stored in the DB (e.g. ``TX``); defaults
    to *symbol* when not provided.

    Returns total number of bars stored.
    """
    store_as = db_symbol or symbol
    connector.ensure_session()
    total_bars = 0
    chunks = _date_chunks(start, end, MAX_CHUNK_DAYS)
    for i, (chunk_start, chunk_end) in enumerate(chunks):
        logger.info(
            "Fetching %s 1m %s to %s (chunk %d/%d)",
            store_as, chunk_start, chunk_end, i + 1, len(chunks),
        )
        df = connector.fetch_minute(symbol, chunk_start, chunk_end)
        if df.is_empty():
            logger.info("no_data", symbol=store_as, start=str(chunk_start), end=str(chunk_end))
            if i < len(chunks) - 1:
                time.sleep(delay)
            continue
        report = connector.validate(df)
        if not report.is_clean:
            logger.warning(
                "Validation issues for %s %s-%s: %s",
                store_as, chunk_start, chunk_end,
                {"gaps": report.gaps[:3], "nulls": report.nulls[:3]},
            )
        bars = [
            OHLCVBar(
                symbol=store_as,
                timestamp=row["timestamp"],
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=int(row["volume"]),
            )
            for row in df.iter_rows(named=True)
        ]
        if bars:
            db.add_ohlcv_bars(bars)
            total_bars += len(bars)
            logger.info(
                "Stored %d bars for %s (%s to %s)",
                len(bars), store_as, chunk_start, chunk_end,
            )
        if i < len(chunks) - 1:
            time.sleep(delay)
    logger.info("crawl_complete", total_bars=total_bars, symbol=store_as)
    return total_bars


def crawl_with_resume(
    contract_symbol: str,
    db_symbol: str,
    earliest_start: date,
    db: Database,
    connector: SinopacConnector,
    delay: float = 2.0,
) -> int:
    """Smart crawl: only fetch date ranges not already in the DB.

    Checks existing data range and crawls gaps before/after, avoiding
    redundant API calls for dates already stored.
    """
    today = date.today()
    existing = db.get_ohlcv_range(db_symbol)

    if not existing:
        logger.info("%s: no existing data — full crawl from %s", db_symbol, earliest_start)
        return crawl_historical(
            symbol=contract_symbol, start=earliest_start, end=today,
            db=db, connector=connector, delay=delay, db_symbol=db_symbol,
        )

    existing_min, existing_max = existing
    earliest_db = existing_min.date() if hasattr(existing_min, 'date') else existing_min
    latest_db = existing_max.date() if hasattr(existing_max, 'date') else existing_max
    logger.info("%s: existing data %s to %s", db_symbol, earliest_db, latest_db)

    total = 0
    # Backfill before existing data (skip overlap day — upsert handles dupes)
    if earliest_start < earliest_db:
        logger.info("%s: backfilling %s to %s", db_symbol, earliest_start, earliest_db)
        total += crawl_historical(
            symbol=contract_symbol, start=earliest_start, end=earliest_db,
            db=db, connector=connector, delay=delay, db_symbol=db_symbol,
        )
    # Forward-fill after existing data
    if latest_db < today:
        logger.info("%s: forward-filling %s to %s", db_symbol, latest_db, today)
        total += crawl_historical(
            symbol=contract_symbol, start=latest_db, end=today,
            db=db, connector=connector, delay=delay, db_symbol=db_symbol,
        )
    if total == 0:
        logger.info("%s: data is up to date", db_symbol)
    return total


def create_crawl_pipeline(db: Database | None = None) -> tuple[SinopacConnector, Database]:
    """Create a ready-to-use connector (logged in via GSM) and database."""
    from src.pipeline.config import create_sinopac_connector
    connector = create_sinopac_connector()
    if db is None:
        db = Database()
    return connector, db


def _date_chunks(start: date, end: date, max_days: int) -> list[tuple[date, date]]:
    chunks: list[tuple[date, date]] = []
    cursor = start
    while cursor <= end:
        chunk_end = min(cursor + timedelta(days=max_days - 1), end)
        chunks.append((cursor, chunk_end))
        cursor = chunk_end + timedelta(days=1)
    return chunks
