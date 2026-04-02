"""Live 1m OHLCV aggregation and persistence for streaming ticks."""
from __future__ import annotations

import sqlite3
import structlog
import threading
from pathlib import Path
from zoneinfo import ZoneInfo
from datetime import datetime
from dataclasses import dataclass

logger = structlog.get_logger(__name__)
TAIPEI_TZ = ZoneInfo("Asia/Taipei")
DEFAULT_DB_PATH = Path(__file__).resolve().parents[2] / "data" / "taifex_data.db"
NIGHT_START_MIN = 15 * 60
NIGHT_END_MIN = 5 * 60
DAY_START_MIN = 8 * 60 + 45
DAY_END_MIN = 13 * 60 + 45


@dataclass
class MinuteBar:
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int


class LiveMinuteBarStore:
    """Build and upsert live 1m bars keyed by symbol."""

    def __init__(self, db_path: Path | None = None) -> None:
        self._db_path = db_path or DEFAULT_DB_PATH
        self._bars: dict[str, MinuteBar] = {}
        self._lock = threading.Lock()

    def ingest_tick(self, symbol: str, price: float, volume: int, tick_ts: datetime) -> None:
        if price <= 0:
            return
        local_ts = tick_ts if tick_ts.tzinfo else tick_ts.replace(tzinfo=TAIPEI_TZ)
        minute_ts = local_ts.astimezone(TAIPEI_TZ).replace(second=0, microsecond=0)
        minute_of_day = minute_ts.hour * 60 + minute_ts.minute
        if not self._is_trading_minute(minute_of_day):
            return
        tick_volume = max(int(volume), 0)
        with self._lock:
            current = self._bars.get(symbol)
            if current is None or current.timestamp != minute_ts:
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
            self._upsert_locked(symbol, current)

    @staticmethod
    def _is_trading_minute(minute_of_day: int) -> bool:
        return (
            minute_of_day >= NIGHT_START_MIN
            or minute_of_day <= NIGHT_END_MIN
            or (DAY_START_MIN <= minute_of_day <= DAY_END_MIN)
        )

    def _upsert_locked(self, symbol: str, bar: MinuteBar) -> None:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        timestamp = bar.timestamp.strftime("%Y-%m-%d %H:%M:%S.%f")
        with sqlite3.connect(str(self._db_path)) as conn:
            conn.execute(
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
            conn.commit()
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
