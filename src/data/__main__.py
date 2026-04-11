"""CLI for TAIFEX data operations.

Usage:
    python -m src.data crawl                     # crawl all contracts with smart resume
    python -m src.data backfill                   # populate 5m/1h tables from 1m data
    python -m src.data gaps                       # detect missing minutes
    python -m src.data gaps --symbol TX           # scan TX only
    python -m src.data gaps --repair              # re-crawl detected gaps
"""
from __future__ import annotations

import argparse
import logging
import sys
import time

import structlog

from src.data.contracts import ALL_SYMBOLS, CONTRACTS, CONTRACTS_BY_SYMBOL
from src.data.db import Database

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)


def _cmd_crawl(args: argparse.Namespace) -> None:
    from src.data.crawl import crawl_with_resume, create_crawl_pipeline

    logger.info("=== TAIFEX Historical Data Crawl ===")
    connector, db = create_crawl_pipeline()

    for contract in CONTRACTS:
        try:
            total = crawl_with_resume(
                contract_symbol=contract.shioaji_path,
                db_symbol=contract.db_symbol,
                earliest_start=contract.earliest_data,
                db=db, connector=connector,
            )
            logger.info("=== %s complete: %d bars stored ===", contract.db_symbol, total)
        except Exception:
            logger.exception("Error crawling %s", contract.db_symbol)

    logger.info("=== Crawl finished ===")
    for contract in CONTRACTS:
        rng = db.get_ohlcv_range(contract.db_symbol)
        if rng:
            logger.info("Final: %s %s to %s", contract.db_symbol, rng[0], rng[1])


def _cmd_backfill(args: argparse.Namespace) -> None:
    from src.data.aggregator import build_5m_bars, build_1h_bars

    db = Database()
    for symbol in ALL_SYMBOLS:
        rng = db.get_ohlcv_range(symbol)
        if rng is None:
            print(f"{symbol}: no 1m data, skipping")
            continue
        print(f"\n{'='*60}")
        print(f"{symbol}: 1m data from {rng[0]} to {rng[1]}")
        count_1m = db.count_ohlcv_tf(symbol, 1)
        print(f"  1m bars: {count_1m:,}")

        t0 = time.time()
        n5 = build_5m_bars(db, symbol)
        print(f"  5m bars: {db.count_ohlcv_tf(symbol, 5):,} (new: {n5:,}, took {time.time()-t0:.1f}s)")

        t0 = time.time()
        n1h = build_1h_bars(db, symbol)
        print(f"  1h bars: {db.count_ohlcv_tf(symbol, 60):,} (new: {n1h:,}, took {time.time()-t0:.1f}s)")

    print(f"\n{'='*60}\nBackfill complete.")


def _cmd_gaps(args: argparse.Namespace) -> None:
    from src.data.gap_detector import detect_gaps, gap_summary

    db = Database()
    symbols = [args.symbol] if args.symbol else ALL_SYMBOLS

    for symbol in symbols:
        rng = db.get_ohlcv_range(symbol)
        if rng is None:
            print(f"\n{symbol}: no data in database, skipping")
            continue

        start_date = rng[0].date() if hasattr(rng[0], 'date') else rng[0]
        end_date = rng[1].date() if hasattr(rng[1], 'date') else rng[1]

        print(f"\n{'=' * 60}")
        print(f"{symbol}: scanning {start_date} to {end_date}")
        print(f"{'=' * 60}")

        gaps = detect_gaps(symbol, start_date, end_date, db)
        summary = gap_summary(gaps)

        print(f"  Total gap ranges: {summary['total_gaps']}")
        print(f"  Data gaps (not holidays): {summary['data_gaps']}")
        print(f"  Likely holidays: {summary['likely_holidays']}")
        print(f"  Missing data minutes: {summary['total_missing_minutes']:,}")
        print(f"  Holiday minutes: {summary['holiday_missing_minutes']:,}")

        data_gaps = [g for g in gaps if not g.likely_holiday]
        if data_gaps:
            print(f"\n  Top data gaps (showing first {min(10, len(data_gaps))}):")
            for g in data_gaps[:10]:
                print(f"    {g.start} to {g.end} ({g.gap_minutes} minutes)")

        if args.repair and data_gaps:
            _repair_gaps(symbol, data_gaps, db)

    print(f"\n{'=' * 60}\nGap detection complete.")


def _repair_gaps(symbol: str, gaps: list, db: Database) -> None:
    contract = CONTRACTS_BY_SYMBOL.get(symbol)
    if not contract:
        print(f"  Cannot repair {symbol}: not in contract registry")
        return

    print(f"\n  Repairing {len(gaps)} gaps for {symbol}...")
    try:
        from src.data.crawl import crawl_historical, create_crawl_pipeline
        connector, _ = create_crawl_pipeline(db)

        total_recovered = 0
        for g in gaps:
            start = g.start.date() if hasattr(g.start, 'date') else g.start
            end = g.end.date() if hasattr(g.end, 'date') else g.end
            try:
                n = crawl_historical(
                    symbol=contract.shioaji_path,
                    start=start, end=end,
                    db=db, connector=connector,
                    delay=2.0, db_symbol=symbol,
                )
                total_recovered += n
                print(f"    Recovered {n} bars for {start} to {end}")
            except Exception:
                logger.exception("Error repairing gap %s-%s", start, end)

        print(f"  Total recovered: {total_recovered} bars")
    except ImportError:
        print("  shioaji not installed — cannot repair.")


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m src.data", description="TAIFEX data operations")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("crawl", help="Crawl historical 1m bars for all contracts")
    sub.add_parser("backfill", help="Populate 5m/1h tables from 1m data")

    gaps_parser = sub.add_parser("gaps", help="Detect missing 1m bars")
    gaps_parser.add_argument("--symbol", type=str, help="Scan a specific symbol (TX, MTX, TMF)")
    gaps_parser.add_argument("--repair", action="store_true", help="Re-crawl detected gaps")

    args = parser.parse_args()
    {"crawl": _cmd_crawl, "backfill": _cmd_backfill, "gaps": _cmd_gaps}[args.command](args)


if __name__ == "__main__":
    main()
