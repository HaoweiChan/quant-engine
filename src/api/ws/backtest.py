"""WebSocket backtest progress — streams progress to a single client."""
from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)
router = APIRouter()

_progress_clients: set[WebSocket] = set()
_lock = asyncio.Lock()


async def push_backtest_progress(pct: float, message: str) -> None:
    """Push progress update to all connected backtest progress clients."""
    async with _lock:
        dead: list[WebSocket] = []
        for ws in _progress_clients:
            try:
                await ws.send_json({"type": "progress", "pct": pct, "message": message})
            except Exception:
                dead.append(ws)
        for ws in dead:
            _progress_clients.discard(ws)


async def push_backtest_complete(result: dict) -> None:
    """Push completion with full results."""
    async with _lock:
        dead: list[WebSocket] = []
        for ws in _progress_clients:
            try:
                await ws.send_json({"type": "complete", "result": result})
            except Exception:
                dead.append(ws)
        for ws in dead:
            _progress_clients.discard(ws)


async def push_backtest_error(message: str) -> None:
    """Push error notification."""
    async with _lock:
        dead: list[WebSocket] = []
        for ws in _progress_clients:
            try:
                await ws.send_json({"type": "error", "message": message})
            except Exception:
                dead.append(ws)
        for ws in dead:
            _progress_clients.discard(ws)


@router.websocket("/ws/backtest-progress")
async def backtest_progress_ws(ws: WebSocket) -> None:
    await ws.accept()
    async with _lock:
        _progress_clients.add(ws)
    logger.info("backtest-progress client connected")
    try:
        while True:
            data = await ws.receive_text()
            if data == "ping":
                await ws.send_json({"type": "pong"})
    except WebSocketDisconnect:
        pass
    finally:
        async with _lock:
            _progress_clients.discard(ws)
        logger.info("backtest-progress client disconnected")
