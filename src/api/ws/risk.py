"""WebSocket risk alerts — pushes threshold breaches to connected clients."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

_TAIPEI_TZ = timezone(timedelta(hours=8))

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)
router = APIRouter()

_risk_clients: set[WebSocket] = set()
_lock = asyncio.Lock()
_HEARTBEAT_INTERVAL = 30  # seconds


async def push_risk_alert(severity: str, trigger: str, details: str) -> None:
    """Push a risk alert to all connected clients."""
    msg = {
        "type": "alert",
        "severity": severity,
        "trigger": trigger,
        "details": details,
        "timestamp": datetime.now(_TAIPEI_TZ).isoformat(),
    }
    async with _lock:
        dead: list[WebSocket] = []
        for ws in _risk_clients:
            try:
                await ws.send_json(msg)
            except Exception:
                dead.append(ws)
        for ws in dead:
            _risk_clients.discard(ws)


@router.websocket("/ws/risk-alerts")
async def risk_alerts_ws(ws: WebSocket) -> None:
    await ws.accept()
    async with _lock:
        _risk_clients.add(ws)
    logger.info("risk-alerts client connected")
    try:
        while True:
            # Heartbeat: send ping every N seconds to keep connection alive
            try:
                data = await asyncio.wait_for(
                    ws.receive_text(), timeout=_HEARTBEAT_INTERVAL
                )
                if data == "ping":
                    await ws.send_json({"type": "pong"})
            except asyncio.TimeoutError:
                await ws.send_json({
                    "type": "heartbeat",
                    "timestamp": datetime.now(_TAIPEI_TZ).isoformat(),
                })
    except WebSocketDisconnect:
        pass
    finally:
        async with _lock:
            _risk_clients.discard(ws)
        logger.info("risk-alerts client disconnected")
