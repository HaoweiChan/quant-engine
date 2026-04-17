"""WebSocket spread feed — broadcasts R1/R2 spread ticks to connected clients.

Used by the war room SpreadView component for real-time spread visualization.
Separate from live_feed.py to avoid polluting the main tick stream with spread data.
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from src.data.spread_monitor import LiveSpreadTick

logger = logging.getLogger(__name__)
router = APIRouter()


class SpreadBroadcaster:
    """Manages spread feed WebSocket clients with throttling."""

    def __init__(self, max_per_sec: int = 10) -> None:
        self._clients: set[WebSocket] = set()
        self._lock = asyncio.Lock()
        self._min_interval_ms = 1000 // max_per_sec
        self._last_broadcast_ms: int = 0

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        async with self._lock:
            self._clients.add(ws)
        logger.info("spread-feed client connected (%d total)", len(self._clients))

    async def disconnect(self, ws: WebSocket) -> None:
        async with self._lock:
            self._clients.discard(ws)
        logger.info("spread-feed client disconnected (%d remaining)", len(self._clients))

    async def broadcast(self, message: dict) -> bool:
        """Broadcast message with throttling. Returns True if sent, False if throttled."""
        now_ms = int(time.time() * 1000)
        if now_ms - self._last_broadcast_ms < self._min_interval_ms:
            return False

        self._last_broadcast_ms = now_ms
        async with self._lock:
            dead: list[WebSocket] = []
            for ws in self._clients:
                try:
                    await ws.send_json(message)
                except Exception:
                    dead.append(ws)
            for ws in dead:
                self._clients.discard(ws)
        return True

    async def broadcast_immediate(self, message: dict) -> None:
        """Broadcast without throttling (for stale/reset signals)."""
        async with self._lock:
            dead: list[WebSocket] = []
            for ws in self._clients:
                try:
                    await ws.send_json(message)
                except Exception:
                    dead.append(ws)
            for ws in dead:
                self._clients.discard(ws)

    @property
    def client_count(self) -> int:
        return len(self._clients)


spread_broadcaster = SpreadBroadcaster()


async def push_spread_tick(tick: LiveSpreadTick) -> bool:
    """Broadcast a paired spread tick. Returns True if sent."""
    ts_iso = datetime.fromtimestamp(
        tick.timestamp_ms / 1000, tz=ZoneInfo("Asia/Taipei")
    ).isoformat()
    return await spread_broadcaster.broadcast({
        "type": "spread_tick",
        "symbol": tick.symbol,
        "r1": tick.r1_price,
        "r2": tick.r2_price,
        "spread": tick.spread,
        "offset": tick.offset,
        "ts": ts_iso,
    })


async def push_spread_stale(symbol: str, missing_leg: str | None) -> None:
    """Broadcast a stale signal when spread feed is stale."""
    await spread_broadcaster.broadcast_immediate({
        "type": "spread_stale",
        "symbol": symbol,
        "missing_leg": missing_leg,
    })


async def push_session_reset(symbol: str) -> None:
    """Broadcast session reset signal."""
    await spread_broadcaster.broadcast_immediate({
        "type": "session_reset",
        "symbol": symbol,
    })


@router.websocket("/ws/spread-feed")
async def spread_feed_ws(ws: WebSocket) -> None:
    """WebSocket endpoint for spread tick stream."""
    await spread_broadcaster.connect(ws)
    try:
        while True:
            data = await ws.receive_text()
            if data == "ping":
                await ws.send_json({"type": "pong"})
    except WebSocketDisconnect:
        pass
    finally:
        await spread_broadcaster.disconnect(ws)
