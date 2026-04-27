"""Live OHLCV aggregation and persistence for streaming ticks.

Ticks land in a per-symbol 1m builder. On each 1m close, the completed
bar is folded into per-symbol streaming builders for every higher TF in
:data:`_STREAMING_TFS` (5m, 1h today) and upserted to its matching table.
Session-boundary safety is inherited from :mod:`src.data.session_utils`:
all bucketing is session-relative, so no higher-TF bar ever spans the
13:45-15:00 day/night gap or the 05:00-08:45 night/day gap.
"""
from __future__ import annotations

import sqlite3
import structlog
import threading
from pathlib import Path
from zoneinfo import ZoneInfo
from datetime import datetime, timedelta
from typing import Callable
from dataclasses import dataclass

from src.data.db import DEFAULT_DB_PATH
from src.data.session_utils import session_id, session_open_dt

logger = structlog.get_logger(__name__)
TAIPEI_TZ = ZoneInfo("Asia/Taipei")
NIGHT_START_MIN = 15 * 60
NIGHT_END_MIN = 5 * 60
DAY_START_MIN = 8 * 60 + 45
DAY_END_MIN = 13 * 60 + 45

# Higher timeframes aggregated in-memory from the 1m stream. To add a new
# TF, append (tf_minutes, table_name) here; the table must share the 1m
# schema (symbol, timestamp, open, high, low, close, volume) and a
# (symbol, timestamp) unique constraint.
_STREAMING_TFS: tuple[tuple[int, str], ...] = (
    (5, "ohlcv_5m"),
    (60, "ohlcv_1h"),
)

BarCompleteCallback = Callable[[str, "MinuteBar"], None]


@dataclass
class MinuteBar:
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int


@dataclass
class _AggregateBuilder:
    """In-memory streaming OHLCV builder for one higher-TF window."""
    timestamp: datetime   # left-aligned window start, naive Taipei
    session_id: str
    bucket_index: int
    open: float
    high: float
    low: float
    close: float
    volume: int


class LiveMinuteBarStore:
    """Build and upsert live 1m bars, streaming-aggregate to 5m and 1h.

    On every 1m bar close the outgoing 1m bar is folded into per-symbol
    builders for each higher TF listed in :data:`_STREAMING_TFS`. The
    current builder state is upserted to the TF's table on each fold so
    War Room charts see the forming window with the same freshness as
    the 1m chart. A bar is emitted via :py:meth:`register_tf_callback`
    subscribers only when the incoming 1m crosses the window boundary
    (or the session changes), matching the semantics of the offline
    aggregator in :mod:`src.data.aggregator`.
    """

    def __init__(self, db_path: Path | None = None) -> None:
        self._db_path = db_path or DEFAULT_DB_PATH
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._bars: dict[str, MinuteBar] = {}
        self._builders: dict[int, dict[str, _AggregateBuilder]] = {
            tf: {} for tf, _ in _STREAMING_TFS
        }
        self._lock = threading.Lock()
        self._tf_callbacks: dict[int, list[BarCompleteCallback]] = {
            1: [],
            **{tf: [] for tf, _ in _STREAMING_TFS},
        }
        # Per-symbol last-tick wall-clock epoch for the feed-staleness
        # watchdog. Recorded inside ``ingest_tick`` regardless of whether
        # the tick rolls a bar; the watchdog calls ``is_stale`` to halt
        # sessions when the broker feed silently drops.
        self._last_tick_epoch: dict[str, float] = {}

    def last_tick_epoch(self, symbol: str) -> float | None:
        """Wall-clock epoch of the most recent tick for ``symbol``, or None."""
        return self._last_tick_epoch.get(symbol)

    def tracked_symbols(self) -> list[str]:
        """Symbols that have ever received a tick. Used by the watchdog."""
        return list(self._last_tick_epoch.keys())

    def is_stale(
        self, symbol: str, now_epoch: float, max_silence_secs: float = 3.0,
    ) -> bool:
        """True when ``symbol`` has not received a tick in ``max_silence_secs``.

        Returns False when no tick has ever been recorded — startup before
        the first tick is not staleness, it's a not-yet-alive condition
        that the connection-state machine handles separately.
        """
        last = self._last_tick_epoch.get(symbol)
        if last is None:
            return False
        return (now_epoch - last) > max_silence_secs

    def register_bar_callback(self, callback: BarCompleteCallback) -> None:
        """Subscribe to 1m bar completions. Equivalent to
        ``register_tf_callback(1, callback)``.
        """
        self.register_tf_callback(1, callback)

    def register_tf_callback(self, tf_minutes: int, callback: BarCompleteCallback) -> None:
        """Subscribe to bar completions for a given timeframe in minutes."""
        if tf_minutes not in self._tf_callbacks:
            raise ValueError(f"unsupported timeframe: {tf_minutes}m")
        self._tf_callbacks[tf_minutes].append(callback)

    def ingest_tick(self, symbol: str, price: float, volume: int, tick_ts: datetime) -> None:
        if price <= 0:
            return
        local_ts = tick_ts if tick_ts.tzinfo else tick_ts.replace(tzinfo=TAIPEI_TZ)
        # Record wall-clock arrival time for the staleness watchdog
        # BEFORE the trading-minute filter, so a feed that's emitting
        # ticks during the closed window still counts as alive.
        self._last_tick_epoch[symbol] = local_ts.timestamp()
        minute_ts = (
            local_ts.astimezone(TAIPEI_TZ)
            .replace(second=0, microsecond=0, tzinfo=None)
        )
        minute_of_day = minute_ts.hour * 60 + minute_ts.minute
        if not self._is_trading_minute(minute_of_day):
            return
        tick_volume = max(int(volume), 0)
        completed_bar: MinuteBar | None = None
        higher_tf_closed: list[tuple[int, MinuteBar]] = []
        with self._lock:
            current = self._bars.get(symbol)
            if current is None or current.timestamp != minute_ts:
                if current is not None and current.timestamp != minute_ts:
                    completed_bar = MinuteBar(
                        timestamp=current.timestamp,
                        open=current.open,
                        high=current.high,
                        low=current.low,
                        close=current.close,
                        volume=current.volume,
                    )
                    self._check_gap(symbol, current.timestamp, minute_ts)
                current = MinuteBar(
                    timestamp=minute_ts,
                    open=price,
                    high=price,
                    low=price,
                    close=price,
                    volume=tick_volume,
                )
                self._bars[symbol] = current
            else:
                current.high = max(current.high, price)
                current.low = min(current.low, price)
                current.close = price
                current.volume += tick_volume
            self._upsert_1m_locked(symbol, current)
            if completed_bar is not None:
                higher_tf_closed = self._fold_into_higher_tfs_locked(symbol, completed_bar)
        # Fire callbacks outside the lock so a slow subscriber cannot
        # stall the tick thread — matches the pre-existing 1m behavior.
        if completed_bar is not None:
            self._fire_callbacks(1, symbol, completed_bar)
        for tf_minutes, bar in higher_tf_closed:
            self._fire_callbacks(tf_minutes, symbol, bar)

    def _fold_into_higher_tfs_locked(
        self, symbol: str, bar_1m: MinuteBar
    ) -> list[tuple[int, MinuteBar]]:
        """Fold a just-closed 1m bar into the 5m/1h builders.

        Upserts current builder state to each TF's table so chart queries
        see the forming window. Returns ``(tf_minutes, closed_bar)`` for
        any window that rolled over as a result of this bar. Called with
        :attr:`_lock` held.
        """
        closed: list[tuple[int, MinuteBar]] = []
        ts = (
            bar_1m.timestamp.replace(tzinfo=None)
            if bar_1m.timestamp.tzinfo
            else bar_1m.timestamp
        )
        sid = session_id(ts)
        if sid == "CLOSED":
            # 1m ingest already filters CLOSED minutes, so this is defensive.
            return closed
        sopen = session_open_dt(sid)
        offset_secs = int((ts - sopen).total_seconds())
        if offset_secs < 0:
            return closed

        for tf_minutes, table in _STREAMING_TFS:
            bucket_secs = tf_minutes * 60
            bucket_index = offset_secs // bucket_secs
            bar_ts = sopen + timedelta(seconds=bucket_index * bucket_secs)

            builders = self._builders[tf_minutes]
            current = builders.get(symbol)
            if current is not None and (
                current.session_id != sid or current.bucket_index != bucket_index
            ):
                closed.append((tf_minutes, MinuteBar(
                    timestamp=current.timestamp,
                    open=current.open,
                    high=current.high,
                    low=current.low,
                    close=current.close,
                    volume=current.volume,
                )))
                current = None
            if current is None:
                current = _AggregateBuilder(
                    timestamp=bar_ts,
                    session_id=sid,
                    bucket_index=bucket_index,
                    open=bar_1m.open,
                    high=bar_1m.high,
                    low=bar_1m.low,
                    close=bar_1m.close,
                    volume=bar_1m.volume,
                )
                builders[symbol] = current
            else:
                current.high = max(current.high, bar_1m.high)
                current.low = min(current.low, bar_1m.low)
                current.close = bar_1m.close
                current.volume += bar_1m.volume
            self._upsert_higher_tf_locked(table, symbol, current)
        return closed

    def _fire_callbacks(self, tf_minutes: int, symbol: str, bar: MinuteBar) -> None:
        for cb in self._tf_callbacks[tf_minutes]:
            try:
                cb(symbol, bar)
            except Exception:
                logger.exception(
                    "bar_complete_callback_error",
                    symbol=symbol,
                    tf_minutes=tf_minutes,
                )

    @staticmethod
    def _is_trading_minute(minute_of_day: int) -> bool:
        return (
            minute_of_day >= NIGHT_START_MIN
            or minute_of_day <= NIGHT_END_MIN
            or (DAY_START_MIN <= minute_of_day <= DAY_END_MIN)
        )

    def _check_gap(self, symbol: str, prev_ts: datetime, new_ts: datetime) -> None:
        """Detect and auto-repair gaps between consecutive 1m bars."""
        try:
            from src.data.gap_repair import async_repair_gap, check_live_continuity
            gap_min = check_live_continuity(symbol, prev_ts, new_ts)
            if gap_min is not None:
                threading.Thread(
                    target=async_repair_gap,
                    args=(symbol, prev_ts, new_ts),
                    daemon=True,
                    name=f"gap-repair-{symbol}",
                ).start()
        except Exception:
            logger.exception("live_gap_check_error", symbol=symbol)

    def _upsert_1m_locked(self, symbol: str, bar: MinuteBar) -> None:
        ts = bar.timestamp.replace(tzinfo=None) if bar.timestamp.tzinfo else bar.timestamp
        timestamp = ts.strftime("%Y-%m-%d %H:%M:%S.%f")
        self._conn.execute(
            """
            INSERT INTO ohlcv_bars (symbol, timestamp, open, high, low, close, volume)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(symbol, timestamp) DO UPDATE SET
                open = COALESCE(ohlcv_bars.open, excluded.open),
                high = MAX(ohlcv_bars.high, excluded.high),
                low = MIN(ohlcv_bars.low, excluded.low),
                close = excluded.close,
                volume = MAX(ohlcv_bars.volume, excluded.volume)
            """,
            (symbol, timestamp, bar.open, bar.high, bar.low, bar.close, bar.volume),
        )
        self._conn.commit()
        logger.debug(
            "live_minute_bar_upserted",
            symbol=symbol,
            timestamp=timestamp,
            open=bar.open,
            high=bar.high,
            low=bar.low,
            close=bar.close,
            volume=bar.volume,
        )

    def _upsert_higher_tf_locked(
        self, table: str, symbol: str, bar: _AggregateBuilder
    ) -> None:
        """Upsert current higher-TF builder to its table.

        MAX/MIN on high/low/volume guards against a mid-window process
        restart: a fresh builder restarts from zero volume and a single
        1m's extrema, but the pre-restart values already in the table
        remain authoritative until the re-streamed builder surpasses them.
        ``excluded.close`` wins so the forming bar's close tracks reality.
        """
        timestamp = bar.timestamp.strftime("%Y-%m-%d %H:%M:%S.%f")
        self._conn.execute(
            f"""
            INSERT INTO {table} (symbol, timestamp, open, high, low, close, volume)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(symbol, timestamp) DO UPDATE SET
                open = excluded.open,
                high = MAX({table}.high, excluded.high),
                low = MIN({table}.low, excluded.low),
                close = excluded.close,
                volume = MAX({table}.volume, excluded.volume)
            """,
            (symbol, timestamp, bar.open, bar.high, bar.low, bar.close, bar.volume),
        )
        self._conn.commit()
