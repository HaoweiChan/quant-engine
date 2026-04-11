"""Entry point for the standalone TAIFEX data ingestion daemon.

Usage:
    python scripts/run_data_daemon.py
    python scripts/run_data_daemon.py --db data/market.db
    python scripts/run_data_daemon.py --simulation
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import structlog

structlog.configure(
    processors=[
        structlog.stdlib.add_log_level,
        structlog.dev.ConsoleRenderer(),
    ],
    wrapper_class=structlog.stdlib.BoundLogger,
    logger_factory=structlog.PrintLoggerFactory(),
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    stream=sys.stdout,
)

from src.data.daemon import DataDaemon
from src.secrets.manager import get_secret_manager


def main() -> None:
    parser = argparse.ArgumentParser(
        description="TAIFEX data ingestion daemon — subscribes to ticks, builds 1m bars",
    )
    parser.add_argument(
        "--db", type=str, default=None,
        help="Path to market.db (default: data/market.db)",
    )
    parser.add_argument(
        "--simulation", action="store_true",
        help="Connect to shioaji in simulation mode",
    )
    args = parser.parse_args()

    db_path = Path(args.db) if args.db else None

    # Load credentials from GSM
    sm = get_secret_manager()
    creds = sm.get_group("sinopac")

    daemon = DataDaemon(db_path=db_path)
    daemon.start(
        api_key=creds["api_key"],
        secret_key=creds["secret_key"],
        simulation=args.simulation,
    )


if __name__ == "__main__":
    main()
