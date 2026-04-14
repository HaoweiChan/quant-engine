"""Subprocess entry point for crawl operations.

Runs the shioaji-dependent crawl in a separate process to isolate C++ crashes
from the main API server. Called by src.api.helpers._crawl_worker.

Usage: python -m src.data.crawl_cli <shioaji_path> <db_symbol> <start> <end>
Prints progress to stdout. Last line: TOTAL=<n>
"""
from __future__ import annotations

import sys
from datetime import date

from src.data.crawl import crawl_historical
from src.data.db import DEFAULT_DB_PATH, Database
from src.pipeline.config import create_sinopac_connector


def main() -> None:
    if len(sys.argv) != 5:
        print(f"Usage: {sys.argv[0]} <shioaji_path> <db_symbol> <start> <end>", file=sys.stderr)
        sys.exit(1)
    shioaji_path, db_symbol, start_str, end_str = sys.argv[1:5]
    print(f"Connecting to Sinopac API...")
    connector = create_sinopac_connector()
    print("Login successful")
    db = Database(f"sqlite:///{DEFAULT_DB_PATH}")
    start_date = date.fromisoformat(start_str)
    end_date = date.fromisoformat(end_str)
    print(f"Fetching 1-min kbars for {shioaji_path} → DB symbol: {db_symbol}")
    total = crawl_historical(
        symbol=shioaji_path, start=start_date, end=end_date,
        db=db, connector=connector, db_symbol=db_symbol,
    )
    print(f"TOTAL={total}")


if __name__ == "__main__":
    main()
