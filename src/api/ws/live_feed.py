"""WebSocket live feed — broadcasts tick/order data to connected clients."""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)
router = APIRouter()


class Broadcaster:
    """Manages a set of connected WebSocket clients and broadcasts messages."""

    def __init__(self) -> None:
        self._clients: set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        async with self._lock:
            self._clients.add(ws)
        logger.info("live-feed client connected (%d total)", len(self._clients))

    async def disconnect(self, ws: WebSocket) -> None:
        async with self._lock:
            self._clients.discard(ws)
        logger.info("live-feed client disconnected (%d remaining)", len(self._clients))

    async def broadcast(self, message: dict) -> None:
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


live_broadcaster = Broadcaster()


async def push_tick(symbol: str, price: float, volume: int) -> None:
    """Called from Shioaji callback bridge to push tick data."""
    await live_broadcaster.broadcast({
        "type": "tick",
        "symbol": symbol,
        "price": price,
        "volume": volume,
        "timestamp": datetime.now().isoformat(),
    })


async def push_order(order_data: dict) -> None:
    """Called from Shioaji callback bridge to push order updates."""
    await live_broadcaster.broadcast({"type": "order", **order_data})


@router.websocket("/ws/live-feed")
async def live_feed_ws(ws: WebSocket) -> None:
    await live_broadcaster.connect(ws)
    try:
        while True:
            # Keep connection alive; clients don't send data, just receive
            data = await ws.receive_text()
            if data == "ping":
                await ws.send_json({"type": "pong"})
    except WebSocketDisconnect:
        pass
    finally:
        await live_broadcaster.disconnect(ws)
