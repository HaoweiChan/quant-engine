"""One-time backfill: populate ohlcv_5m and ohlcv_1h from raw 1m data."""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.data.db import Database
from src.data.aggregator import build_5m_bars, build_1h_bars


def main():
    db_path = Path(__file__).resolve().parents[1] / "data" / "taifex_data.db"
    if not db_path.exists():
        print(f"Database not found: {db_path}")
        sys.exit(1)

    db = Database(f"sqlite:///{db_path}")

    for symbol in ("TX", "MTX"):
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
        elapsed_5 = time.time() - t0
        count_5m = db.count_ohlcv_tf(symbol, 5)
        print(f"  5m bars: {count_5m:,} (new: {n5:,}, took {elapsed_5:.1f}s)")

        t0 = time.time()
        n1h = build_1h_bars(db, symbol)
        elapsed_1h = time.time() - t0
        count_1h = db.count_ohlcv_tf(symbol, 60)
        print(f"  1h bars: {count_1h:,} (new: {n1h:,}, took {elapsed_1h:.1f}s)")

    print(f"\n{'='*60}")
    print("Backfill complete.")


if __name__ == "__main__":
    main()
