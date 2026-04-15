"""R1-R2 spread monitor for contract rolling optimization.

Tracks the price differential between near-month (R1) and next-month (R2)
contracts to identify optimal roll windows. Spread = R2_price - R1_price.

A positive spread (contango) means R2 trades at a premium.
A negative spread (backwardation) means R2 trades at a discount.

For rolling long positions, the best time to roll is when the spread
(cost of carry) is minimized. The monitor records spread history and
provides optimal-window detection.
"""
from __future__ import annotations

import sqlite3
import structlog
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal

logger = structlog.get_logger(__name__)

_TAIPEI_TZ = timezone(timedelta(hours=8))
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_DEFAULT_DB = _PROJECT_ROOT / "data" / "market.db"

# Tick window for live spread stats (last N observations)
_DEFAULT_WINDOW = 120


@dataclass(frozen=True)
class SpreadSnapshot:
    """Single spread observation."""
    timestamp: datetime
    symbol: str
    r1_price: float
    r2_price: float
    spread: float          # R2 - R1 (absolute points)
    spread_pct: float      # spread / R1 * 100 (%)


@dataclass(frozen=True)
class SpreadStats:
    """Rolling spread statistics for a symbol."""
    symbol: str
    current: float
    mean: float
    std: float
    min: float
    max: float
    percentile: float       # current spread's percentile in the window
    n_obs: int
    favorable: bool         # True if current spread <= 25th percentile


@dataclass
class SpreadWindow:
    """Maintains a rolling window of spread observations per symbol."""
    symbol: str
    maxlen: int = _DEFAULT_WINDOW
    _spreads: deque[SpreadSnapshot] = field(default_factory=deque)

    def __post_init__(self) -> None:
        self._spreads = deque(maxlen=self.maxlen)

    def add(self, snap: SpreadSnapshot) -> None:
        self._spreads.append(snap)

    def stats(self) -> SpreadStats | None:
        if len(self._spreads) < 2:
            return None
        vals = [s.spread for s in self._spreads]
        current = vals[-1]
        mean = sum(vals) / len(vals)
        variance = sum((v - mean) ** 2 for v in vals) / len(vals)
        std = variance ** 0.5
        lo, hi = min(vals), max(vals)
        below = sum(1 for v in vals if v <= current)
        pct = below / len(vals) * 100
        return SpreadStats(
            symbol=self.symbol,
            current=current,
            mean=mean,
            std=std,
            min=lo,
            max=hi,
            percentile=pct,
            n_obs=len(vals),
            favorable=(pct <= 25),
        )

    @property
    def latest(self) -> SpreadSnapshot | None:
        return self._spreads[-1] if self._spreads else None


class SpreadMonitor:
    """Manages spread tracking for all traded symbols."""

    def __init__(self, window_size: int = _DEFAULT_WINDOW) -> None:
        self._windows: dict[str, SpreadWindow] = {}
        self._window_size = window_size

    def record(
        self,
        symbol: str,
        r1_price: float,
        r2_price: float,
        timestamp: datetime | None = None,
    ) -> SpreadSnapshot:
        """Record a new spread observation. Returns the snapshot."""
        ts = timestamp or datetime.now(_TAIPEI_TZ)
        spread = r2_price - r1_price
        spread_pct = (spread / r1_price * 100) if r1_price > 0 else 0.0
        snap = SpreadSnapshot(
            timestamp=ts,
            symbol=symbol,
            r1_price=r1_price,
            r2_price=r2_price,
            spread=spread,
            spread_pct=spread_pct,
        )
        if symbol not in self._windows:
            self._windows[symbol] = SpreadWindow(symbol=symbol, maxlen=self._window_size)
        self._windows[symbol].add(snap)
        return snap

    def get_stats(self, symbol: str) -> SpreadStats | None:
        """Get rolling spread statistics for a symbol."""
        window = self._windows.get(symbol)
        if not window:
            return None
        return window.stats()

    def is_favorable(self, symbol: str) -> bool:
        """True if current spread is in the lowest 25th percentile of window."""
        stats = self.get_stats(symbol)
        return stats.favorable if stats else False

    def latest(self, symbol: str) -> SpreadSnapshot | None:
        """Most recent spread snapshot for a symbol."""
        window = self._windows.get(symbol)
        return window.latest if window else None


# -- DB persistence for historical spread analysis --

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS spread_history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp   TEXT    NOT NULL,
    symbol      TEXT    NOT NULL,
    r1_price    REAL    NOT NULL,
    r2_price    REAL    NOT NULL,
    spread      REAL    NOT NULL,
    spread_pct  REAL    NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_spread_sym_ts ON spread_history(symbol, timestamp);
"""


def ensure_schema(db_path: Path | None = None) -> None:
    """Create the spread_history table if it doesn't exist."""
    path = db_path or _DEFAULT_DB
    conn = sqlite3.connect(str(path))
    try:
        conn.executescript(_SCHEMA_SQL)
        conn.commit()
    finally:
        conn.close()


def persist_snapshot(snap: SpreadSnapshot, db_path: Path | None = None) -> None:
    """Write a single spread snapshot to the DB."""
    path = db_path or _DEFAULT_DB
    conn = sqlite3.connect(str(path))
    try:
        conn.execute(
            """INSERT INTO spread_history (timestamp, symbol, r1_price, r2_price, spread, spread_pct)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (snap.timestamp.isoformat(), snap.symbol, snap.r1_price,
             snap.r2_price, snap.spread, snap.spread_pct),
        )
        conn.commit()
    finally:
        conn.close()


def persist_batch(snapshots: list[SpreadSnapshot], db_path: Path | None = None) -> int:
    """Write a batch of spread snapshots. Returns count persisted."""
    if not snapshots:
        return 0
    path = db_path or _DEFAULT_DB
    ensure_schema(path)
    conn = sqlite3.connect(str(path))
    try:
        conn.executemany(
            """INSERT INTO spread_history (timestamp, symbol, r1_price, r2_price, spread, spread_pct)
               VALUES (?, ?, ?, ?, ?, ?)""",
            [(s.timestamp.isoformat(), s.symbol, s.r1_price,
              s.r2_price, s.spread, s.spread_pct) for s in snapshots],
        )
        conn.commit()
        return len(snapshots)
    finally:
        conn.close()


def load_spread_history(
    symbol: str,
    start: datetime | None = None,
    end: datetime | None = None,
    db_path: Path | None = None,
) -> list[SpreadSnapshot]:
    """Load historical spread snapshots from DB."""
    path = db_path or _DEFAULT_DB
    if not path.exists():
        return []
    conn = sqlite3.connect(str(path))
    try:
        query = "SELECT timestamp, symbol, r1_price, r2_price, spread, spread_pct FROM spread_history WHERE symbol = ?"
        params: list = [symbol]
        if start:
            query += " AND timestamp >= ?"
            params.append(start.isoformat())
        if end:
            query += " AND timestamp <= ?"
            params.append(end.isoformat())
        query += " ORDER BY timestamp"
        rows = conn.execute(query, params).fetchall()
        return [
            SpreadSnapshot(
                timestamp=datetime.fromisoformat(r[0]),
                symbol=r[1],
                r1_price=r[2],
                r2_price=r[3],
                spread=r[4],
                spread_pct=r[5],
            )
            for r in rows
        ]
    finally:
        conn.close()


def compute_spread_from_bars(
    symbol: str,
    start: datetime | None = None,
    end: datetime | None = None,
    db_path: Path | None = None,
) -> list[SpreadSnapshot]:
    """Compute historical spread from stored OHLCV bars (R1 vs R2 close prices).

    Useful for backtesting roll cost estimation when no tick-level spread data
    was recorded.
    """
    path = db_path or _DEFAULT_DB
    if not path.exists():
        return []
    r2_symbol = f"{symbol}_R2"
    conn = sqlite3.connect(str(path))
    try:
        def _fetch(sym: str) -> dict[str, float]:
            q = "SELECT timestamp, close FROM ohlcv_bars WHERE symbol = ?"
            p: list = [sym]
            if start:
                q += " AND timestamp >= ?"
                p.append(start.isoformat())
            if end:
                q += " AND timestamp <= ?"
                p.append(end.isoformat())
            rows = conn.execute(q, p).fetchall()
            return {r[0]: r[1] for r in rows}

        r1_prices = _fetch(symbol)
        r2_prices = _fetch(r2_symbol)
        common_ts = sorted(set(r1_prices.keys()) & set(r2_prices.keys()))
        results = []
        for ts_str in common_ts:
            r1 = r1_prices[ts_str]
            r2 = r2_prices[ts_str]
            ts = datetime.fromisoformat(ts_str)
            spread = r2 - r1
            spread_pct = (spread / r1 * 100) if r1 > 0 else 0.0
            results.append(SpreadSnapshot(
                timestamp=ts,
                symbol=symbol,
                r1_price=r1,
                r2_price=r2,
                spread=spread,
                spread_pct=spread_pct,
            ))
        return results
    finally:
        conn.close()
