"""Crawl TAIFEX historical 1-min OHLCV data from Shioaji and store in DB."""
from __future__ import annotations

import logging
import sys
import time
from datetime import date

import shioaji as sj

from src.data.crawl import crawl_historical
from src.data.db import Database
from src.data.connector import SinopacConnector
from src.secrets.manager import get_secret_manager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)

SYMBOLS = ["Futures.TXF.TXFR1", "Futures.MXF.MXFR1"]
SYMBOL_SHORT = {"Futures.TXF.TXFR1": "TX", "Futures.MXF.MXFR1": "MTX"}
START = date(2020, 3, 22)
END = date(2026, 3, 14)


def main() -> None:
    logger.info("=== TAIFEX Historical Data Crawl ===")
    logger.info("Date range: %s to %s", START, END)
    logger.info("Symbols: %s", list(SYMBOL_SHORT.values()))

    sm = get_secret_manager()
    creds = sm.get_group("sinopac")

    api = sj.Shioaji()
    api.login(creds["api_key"], creds["secret_key"])
    logger.info("Shioaji login OK")

    connector = SinopacConnector(api=api)
    connector._logged_in = True
    connector._api_key = creds["api_key"]
    connector._secret_key = creds["secret_key"]

    db = Database(url="sqlite:///taifex_data.db")
    logger.info("Database: taifex_data.db")

    for symbol in SYMBOLS:
        short = SYMBOL_SHORT[symbol]
        existing = db.get_ohlcv_range(short)
        if existing:
            logger.info(
                "%s: existing data from %s to %s",
                short, existing[0], existing[1],
            )
        else:
            logger.info("%s: no existing data", short)

        logger.info("Starting crawl for %s (%s)", short, symbol)
        try:
            total = crawl_historical(
                symbol=symbol,
                start=START,
                end=END,
                db=db,
                connector=connector,
                delay=1.5,
                db_symbol=short,
            )
            logger.info("=== %s complete: %d bars stored ===", short, total)
        except Exception:
            logger.exception("Error crawling %s", short)
        time.sleep(2)

    api.logout()
    logger.info("=== Crawl finished ===")

    for short in SYMBOL_SHORT.values():
        rng = db.get_ohlcv_range(short)
        if rng:
            logger.info(
                "Final: %s has data from %s to %s",
                short, rng[0], rng[1],
            )


if __name__ == "__main__":
    main()
