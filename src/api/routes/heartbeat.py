"""Heartbeat endpoint — ping broker gateways and report latency."""
from __future__ import annotations

import threading
import time

from fastapi import APIRouter

from src.api.helpers import get_gateway_registry, get_session_manager, get_subscriber_stats


router = APIRouter(prefix="/api", tags=["heartbeat"])


@router.get("/heartbeat")
async def heartbeat() -> dict:
    registry = get_gateway_registry()
    mgr = get_session_manager()
    brokers: list[dict] = []
    for account_id, gw in registry._gateways.items():
        start = time.monotonic()
        try:
            snap = gw.get_account_snapshot()
            latency_ms = round((time.monotonic() - start) * 1000, 1)
            connected = snap.connected
        except Exception:
            latency_ms = None
            connected = False
        brokers.append({
            "account_id": account_id,
            "broker": gw.broker_name,
            "connected": connected,
            "latency_ms": latency_ms,
        })
    sub_stats = get_subscriber_stats()
    sub_thread = next((t for t in threading.enumerate() if t.name == "market-data-subscriber"), None)
    sub_stats["thread_alive"] = sub_thread.is_alive() if sub_thread else False
    return {
        "brokers": brokers,
        "halt_active": mgr.halt_active,
        "market_data": sub_stats,
        "timestamp": time.time(),
    }
