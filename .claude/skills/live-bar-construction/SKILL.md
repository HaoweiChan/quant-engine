---
name: live-bar-construction
description: "Build real-time OHLCV bars from shioaji tick callbacks. Unify historical SQLite bars with live session bars for seamless charting."
license: MIT
metadata:
  author: quant-engine
  version: "1.0"
---

## The Architecture Problem
TAIFEX historical data from shioaji API is only available up to the **previous trading day**.
Today's bars must be constructed in real-time from tick-level callback data.

This means the chart has TWO data sources that must be unified seamlessly:
```
Historical bars (D-1 and earlier)    ←── shioaji get_kbars() / SQLite cache
Live bars (today, current session)   ←── shioaji tick callback → in-memory bar builder
         ↓                                        ↓
              Unified bar stream → WebSocket → React chart
```

The boundary between these two sources must be invisible to the user.

---

## shioaji Subscription Pattern

```python
# src/live/tick_subscriber.py
import shioaji as sj
from datetime import datetime, timezone
from dataclasses import dataclass, field
from typing import Callable
import threading

@dataclass
class LiveBar:
    """A bar being constructed from ticks. Not complete until bar_close() called."""
    symbol: str
    bar_open_ts: datetime      # bar open time (floored to bar interval)
    interval_minutes: int
    open: float = 0.0
    high: float = 0.0
    low: float = float('inf')
    close: float = 0.0
    volume: int = 0
    tick_count: int = 0
    is_closed: bool = False

    def update(self, price: float, qty: int) -> None:
        """Ingest a single tick."""
        if self.tick_count == 0:
            self.open = price
            self.high = price
            self.low = price
        else:
            self.high = max(self.high, price)
            self.low = min(self.low, price)
        self.close = price
        self.volume += qty
        self.tick_count += 1

    def to_ohlcv(self) -> dict:
        return {
            "timestamp": int(self.bar_open_ts.timestamp()),
            "open": self.open,
            "high": self.high,
            "low": self.low if self.low != float('inf') else self.open,
            "close": self.close,
            "volume": self.volume,
            "is_live": not self.is_closed,
        }


class LiveBarBuilder:
    """
    Converts shioaji tick callbacks into OHLCV bars.
    Thread-safe. Emits completed bars via on_bar_closed callback.
    Emits live (in-progress) bar updates via on_bar_update callback.
    """

    def __init__(
        self,
        symbol: str,
        interval_minutes: int = 1,
        on_bar_closed: Callable[[dict], None] | None = None,
        on_bar_update: Callable[[dict], None] | None = None,
    ):
        self.symbol = symbol
        self.interval = interval_minutes
        self.on_bar_closed = on_bar_closed
        self.on_bar_update = on_bar_update
        self._current_bar: LiveBar | None = None
        self._lock = threading.Lock()

    def _floor_to_bar(self, ts: datetime) -> datetime:
        """Floor timestamp to the bar's open time."""
        minute = (ts.minute // self.interval) * self.interval
        return ts.replace(minute=minute, second=0, microsecond=0)

    def on_tick(self, price: float, qty: int, ts: datetime) -> None:
        """Call this from the shioaji tick callback."""
        bar_open = self._floor_to_bar(ts)

        with self._lock:
            if self._current_bar is None:
                # First tick of the session
                self._current_bar = LiveBar(
                    symbol=self.symbol,
                    bar_open_ts=bar_open,
                    interval_minutes=self.interval,
                )

            if bar_open > self._current_bar.bar_open_ts:
                # New bar started — close the previous one
                self._current_bar.is_closed = True
                closed = self._current_bar.to_ohlcv()
                if self.on_bar_closed:
                    self.on_bar_closed(closed)

                # Persist closed bar to SQLite
                _persist_bar(self.symbol, closed)

                # Start new bar
                self._current_bar = LiveBar(
                    symbol=self.symbol,
                    bar_open_ts=bar_open,
                    interval_minutes=self.interval,
                )

            # Update current bar
            self._current_bar.update(price, qty)
            live = self._current_bar.to_ohlcv()

        # Emit live update (outside lock to avoid blocking)
        if self.on_bar_update:
            self.on_bar_update(live)

    def get_current_bar(self) -> dict | None:
        with self._lock:
            return self._current_bar.to_ohlcv() if self._current_bar else None
```

---

## shioaji Callback Wiring

```python
# src/live/session.py
import shioaji as sj
from datetime import datetime, timezone

api = sj.Shioaji()
# ... login ...

builder_1m = LiveBarBuilder(
    symbol="TXF",
    interval_minutes=1,
    on_bar_closed=lambda bar: ws_broadcast("bar_closed", bar),
    on_bar_update=lambda bar: ws_broadcast("bar_update", bar),
)
builder_5m = LiveBarBuilder(
    symbol="TXF",
    interval_minutes=5,
    on_bar_closed=lambda bar: ws_broadcast("bar_closed_5m", bar),
    on_bar_update=lambda bar: ws_broadcast("bar_update_5m", bar),
)

@api.on_tick_stk_v1()
def tick_callback(exchange, tick):
    if tick.code != "TXF":
        return
    ts = datetime.fromtimestamp(tick.datetime / 1e9, tz=timezone.utc)
    price = tick.close
    qty = tick.volume
    builder_1m.on_tick(price, qty, ts)
    builder_5m.on_tick(price, qty, ts)

api.quote.subscribe(
    api.Contracts.Futures.TXF["TXF"],
    quote_type=sj.constant.QuoteType.Tick,
    version=sj.constant.QuoteVersion.v1,
)
```

---

## Unified Bar Stream (Historical + Live)

```python
# src/live/bar_stream.py
"""
Provides a unified bar stream merging historical SQLite bars
with today's live bars from LiveBarBuilder.
"""
from datetime import datetime, date
from src.data.sqlite_store import load_bars_from_sqlite
from src.live.tick_subscriber import LiveBarBuilder

def get_unified_bars(
    symbol: str,
    interval_minutes: int,
    start: datetime,
    builder: LiveBarBuilder,
) -> list[dict]:
    """
    Returns historical bars from SQLite up to yesterday,
    then appends the in-progress live bars from today's session.
    The live bar (is_closed=False) is always the last element.
    """
    # 1. Historical bars from DB (up to end of yesterday)
    end_of_yesterday = datetime.combine(date.today(), datetime.min.time())
    historical = load_bars_from_sqlite(symbol, start, end_of_yesterday, interval_minutes)

    # 2. Today's completed bars (already persisted by on_bar_closed)
    today_start = datetime.combine(date.today(), datetime.min.time())
    todays_closed = load_bars_from_sqlite(symbol, today_start, datetime.utcnow(), interval_minutes)

    # 3. Current live (in-progress) bar
    live_bar = builder.get_current_bar()

    result = historical + todays_closed
    if live_bar:
        result.append(live_bar)
    return result
```

---

## React Chart Update Pattern

The frontend must handle two WebSocket message types differently:

```typescript
// frontend/src/hooks/useBarStream.ts
import { useEffect, useRef, useState } from 'react';
import { ISeriesApi } from 'lightweight-charts';

export function useBarStream(series: ISeriesApi<'Candlestick'> | null) {
  const ws = useRef<WebSocket | null>(null);

  useEffect(() => {
    ws.current = new WebSocket('ws://localhost:8000/ws/bars');

    ws.current.onmessage = (event) => {
      const msg = JSON.parse(event.data);

      if (msg.type === 'bar_closed') {
        // Finalized bar — update normally
        series?.update({
          time: msg.data.timestamp,
          open: msg.data.open,
          high: msg.data.high,
          low: msg.data.low,
          close: msg.data.close,
        });
      } else if (msg.type === 'bar_update') {
        // Live in-progress bar — update the SAME time slot repeatedly
        // TradingView handles repeated updates to the same timestamp correctly
        series?.update({
          time: msg.data.timestamp,
          open: msg.data.open,
          high: msg.data.high,
          low: msg.data.low,
          close: msg.data.close,
        });
      } else if (msg.type === 'initial_bars') {
        // Full history on connect — set all at once
        series?.setData(msg.data.map((b: any) => ({
          time: b.timestamp,
          open: b.open, high: b.high, low: b.low, close: b.close,
        })));
      }
    };

    return () => ws.current?.close();
  }, [series]);
}
```

---

## Persistence of Today's Bars

Closed bars must be persisted immediately so they survive reconnects and restarts:

```python
import sqlite3
from pathlib import Path

_DB = Path("data/live_bars.db")

def _persist_bar(symbol: str, bar: dict) -> None:
    """Write a closed bar to SQLite. Called by on_bar_closed callback."""
    with sqlite3.connect(str(_DB)) as conn:
        conn.execute("""
            INSERT OR REPLACE INTO ohlcv_bars
              (symbol, timestamp, open, high, low, close, volume, interval_minutes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            symbol,
            bar["timestamp"],
            bar["open"], bar["high"], bar["low"], bar["close"],
            bar["volume"],
            bar.get("interval_minutes", 1),
        ))
```

---

## Critical Edge Cases

1. **Tick arrives after bar close time**: Can happen due to network latency.
   Always use tick's own timestamp (from shioaji `tick.datetime`), never `datetime.now()`.

2. **Reconnect mid-session**: On reconnect, reload today's persisted bars from SQLite,
   then resume tick subscription. Do NOT assume the live builder state survived the reconnect.

3. **Session boundary**: When a tick arrives at 08:45 after a night session,
   the LiveBarBuilder must detect the session gap and NOT continue the previous bar.
   Check `is_new_session(prev_ts, curr_ts)` before `_floor_to_bar()`.

4. **Zero-volume ticks**: shioaji sometimes emits ticks with qty=0 (quote updates, not trades).
   Filter: `if tick.volume == 0: return` in the callback.
