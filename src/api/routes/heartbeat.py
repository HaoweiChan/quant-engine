"""Heartbeat endpoint — ping broker gateways and report latency."""
from __future__ import annotations

import time

from fastapi import APIRouter

from src.api.helpers import get_gateway_registry, get_session_manager


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
    return {
        "brokers": brokers,
        "halt_active": mgr.halt_active,
        "timestamp": time.time(),
    }
