"""WebSocket blotter — streams fill/order events to connected dashboard clients."""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect


logger = logging.getLogger(__name__)
router = APIRouter()


class BlotterBroadcaster:
    """Manages WebSocket connections for the order blotter feed."""

    def __init__(self, trailing_window: int = 20, alert_multiplier: float = 2.0) -> None:
        self._clients: set[WebSocket] = set()
        self._lock = asyncio.Lock()
        self._recent: list[dict[str, Any]] = []
        self._max_recent = 200
        self._trailing_window = trailing_window
        self._alert_multiplier = alert_multiplier
        self._fill_slippages: list[float] = []
        self.trailing_avg_slippage_bps: float = 0.0

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        async with self._lock:
            self._clients.add(ws)
        # Send recent events on connect so client isn't blank
        if self._recent:
            try:
                await ws.send_text(json.dumps({"type": "snapshot", "events": self._recent[-50:]}))
            except Exception:
                pass
        logger.info("blotter client connected (%d total)", len(self._clients))

    async def disconnect(self, ws: WebSocket) -> None:
        async with self._lock:
            self._clients.discard(ws)

    def _update_slippage(self, event: dict[str, Any]) -> None:
        """Track trailing average slippage from fill events."""
        if event.get("type") != "fill":
            return
        slippage_bps = event.get("slippage_bps")
        if slippage_bps is None:
            price = event.get("price", 0)
            expected = event.get("expected_price", 0)
            if price and expected:
                slippage_bps = abs(price - expected) / expected * 10_000
            else:
                return
        self._fill_slippages.append(slippage_bps)
        if len(self._fill_slippages) > self._trailing_window:
            self._fill_slippages = self._fill_slippages[-self._trailing_window:]
        self.trailing_avg_slippage_bps = sum(self._fill_slippages) / len(self._fill_slippages)

    async def broadcast(self, event: dict[str, Any]) -> None:
        """Broadcast a single blotter event to all connected clients."""
        event.setdefault("timestamp", time.time())
        self._update_slippage(event)
        # Inject slippage alert if trailing avg exceeds threshold
        cost_assumption = event.get("cost_model_slippage_bps", 0)
        if cost_assumption > 0 and self.trailing_avg_slippage_bps > self._alert_multiplier * cost_assumption:
            event["slippage_alert"] = True
            event["trailing_avg_slippage_bps"] = round(self.trailing_avg_slippage_bps, 2)
        self._recent.append(event)
        if len(self._recent) > self._max_recent:
            self._recent = self._recent[-self._max_recent:]
        payload = json.dumps({"type": "event", "event": event})
        async with self._lock:
            dead: list[WebSocket] = []
            for ws in self._clients:
                try:
                    await ws.send_text(payload)
                except Exception:
                    dead.append(ws)
            for ws in dead:
                self._clients.discard(ws)


blotter_broadcaster = BlotterBroadcaster()


@router.websocket("/ws/blotter")
async def ws_blotter(ws: WebSocket) -> None:
    await blotter_broadcaster.connect(ws)
    try:
        while True:
            # Keep connection alive; ignore client messages
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        await blotter_broadcaster.disconnect(ws)
