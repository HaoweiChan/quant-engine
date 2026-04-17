"""R1-R2 spread monitor for contract rolling optimization.

Tracks the price differential between near-month (R1) and next-month (R2)
contracts to identify optimal roll windows. Spread = R1_price - R2_price.

A negative spread (contango) means R2 trades at a premium (R1 < R2).
A positive spread (backwardation) means R2 trades at a discount (R1 > R2).

For rolling long positions, the best time to roll is when the spread
(cost of carry) is minimized. The monitor records spread history and
provides optimal-window detection.

Also provides LiveSpreadBuffer for real-time tick pairing used by the
war room spread visualization.
"""
from __future__ import annotations

import sqlite3
import structlog
import time
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
    spread: float          # R1 - R2 (absolute points)
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


# -- Live spread buffer for war room visualization --

@dataclass
class LiveSpreadTick:
    """Single paired spread tick for real-time visualization."""
    timestamp_ms: int
    symbol: str
    r1_price: float
    r2_price: float
    spread: float
    offset: float


class LiveSpreadBuffer:
    """Buffer R1/R2 ticks, emit spread only on matched timestamps.

    Used by the war room spread visualization to pair R1/R2 ticks and
    compute live spread values with a session-scoped offset for z-score
    continuity.

    Tick pairing uses 200ms buckets to handle timing jitter between legs.
    """

    def __init__(
        self,
        symbol: str = "TX",
        bucket_ms: int = 200,
        max_lag_ms: int = 2000,
        stale_threshold_ms: int = 5000,
        warmup_bars: int = 60,
        max_buffer_per_leg: int = 1000,
    ) -> None:
        self._symbol = symbol
        self._bucket_ms = bucket_ms
        self._max_lag_ms = max_lag_ms
        self._stale_threshold_ms = stale_threshold_ms
        self._warmup_bars = warmup_bars
        self._max_buffer = max_buffer_per_leg

        self._r1_buffer: dict[int, float] = {}
        self._r2_buffer: dict[int, float] = {}
        self._spread_history: list[float] = []
        self._session_offset: float | None = None
        self._last_emit_ms: int = 0
        self._last_r1_ms: int = 0
        self._last_r2_ms: int = 0

    def on_tick(
        self, code: str, price: float, ts_ms: int
    ) -> LiveSpreadTick | None:
        """Process an R1 or R2 tick. Returns a spread tick if pair matched."""
        bucket = (ts_ms // self._bucket_ms) * self._bucket_ms

        if code.endswith("R1"):
            self._r1_buffer[bucket] = price
            self._last_r1_ms = ts_ms
        elif code.endswith("R2"):
            self._r2_buffer[bucket] = price
            self._last_r2_ms = ts_ms
        else:
            return None

        # Check for matched pair in this bucket
        if bucket in self._r1_buffer and bucket in self._r2_buffer:
            r1 = self._r1_buffer.pop(bucket)
            r2 = self._r2_buffer.pop(bucket)
            spread = r1 - r2

            # Track spread history for warmup offset computation
            self._spread_history.append(spread)
            if len(self._spread_history) > self._warmup_bars * 2:
                self._spread_history = self._spread_history[-self._warmup_bars:]

            # Compute session offset from first warmup_bars spreads
            if self._session_offset is None and len(self._spread_history) >= self._warmup_bars:
                min_spread = min(self._spread_history[:self._warmup_bars])
                self._session_offset = max(0.0, -min_spread + 100.0)

            offset = self._session_offset if self._session_offset is not None else 100.0
            self._last_emit_ms = ts_ms

            return LiveSpreadTick(
                timestamp_ms=ts_ms,
                symbol=self._symbol,
                r1_price=r1,
                r2_price=r2,
                spread=spread,
                offset=offset,
            )

        # Prune stale entries to prevent memory growth
        self._prune_stale(ts_ms)
        return None

    def _prune_stale(self, now_ms: int) -> None:
        """Remove tick entries older than max_lag_ms."""
        cutoff = now_ms - self._max_lag_ms
        self._r1_buffer = {k: v for k, v in self._r1_buffer.items() if k > cutoff}
        self._r2_buffer = {k: v for k, v in self._r2_buffer.items() if k > cutoff}

        # Enforce max buffer size with hysteresis (prune to 50% on overflow)
        if len(self._r1_buffer) > self._max_buffer:
            sorted_keys = sorted(self._r1_buffer.keys())
            keep = sorted_keys[-(self._max_buffer // 2):]
            self._r1_buffer = {k: self._r1_buffer[k] for k in keep}
        if len(self._r2_buffer) > self._max_buffer:
            sorted_keys = sorted(self._r2_buffer.keys())
            keep = sorted_keys[-(self._max_buffer // 2):]
            self._r2_buffer = {k: self._r2_buffer[k] for k in keep}

    def is_stale(self, now_ms: int | None = None) -> tuple[bool, str | None]:
        """Check if spread feed is stale (no paired emit in threshold).

        Returns (is_stale, missing_leg) where missing_leg is 'R1', 'R2', or 'BOTH'.
        """
        if now_ms is None:
            now_ms = int(time.time() * 1000)

        if self._last_emit_ms == 0:
            # Never emitted - check if we have any ticks at all
            if self._last_r1_ms == 0 and self._last_r2_ms == 0:
                return True, "BOTH"
            elif self._last_r1_ms == 0:
                return True, "R1"
            elif self._last_r2_ms == 0:
                return True, "R2"
            return False, None

        if now_ms - self._last_emit_ms > self._stale_threshold_ms:
            # Determine which leg is missing
            r1_stale = now_ms - self._last_r1_ms > self._stale_threshold_ms
            r2_stale = now_ms - self._last_r2_ms > self._stale_threshold_ms
            if r1_stale and r2_stale:
                return True, "BOTH"
            elif r1_stale:
                return True, "R1"
            elif r2_stale:
                return True, "R2"
            return True, None  # Both legs active but not pairing

        return False, None

    def get_session_offset(self) -> float:
        """Get current session offset (default 100.0 if warmup incomplete)."""
        return self._session_offset if self._session_offset is not None else 100.0

    def reset_session(self) -> None:
        """Reset buffer state for new trading session."""
        self._r1_buffer.clear()
        self._r2_buffer.clear()
        self._spread_history.clear()
        self._session_offset = None
        self._last_emit_ms = 0
        self._last_r1_ms = 0
        self._last_r2_ms = 0
        logger.info("live_spread_buffer_reset", symbol=self._symbol)

    @property
    def symbol(self) -> str:
        return self._symbol

    @property
    def warmup_complete(self) -> bool:
        return self._session_offset is not None


# Singleton instance for war room
_live_buffers: dict[str, LiveSpreadBuffer] = {}


def get_live_buffer(symbol: str = "TX") -> LiveSpreadBuffer:
    """Get or create a per-symbol LiveSpreadBuffer instance."""
    global _live_buffers
    if symbol not in _live_buffers:
        _live_buffers[symbol] = LiveSpreadBuffer(symbol=symbol)
    return _live_buffers[symbol]


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
