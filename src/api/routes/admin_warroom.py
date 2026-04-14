"""Admin endpoints for War Room mock state.

Gated three ways (ENV != prod, port != 8000, QUANT_WARROOM_SEED == "1")
so production traffic can never trigger a reseed by accident.
"""
from __future__ import annotations

import asyncio
import os

from fastapi import APIRouter, HTTPException, Request

from src.trading_session.warroom_seeder import seed_mock_warroom

router = APIRouter(prefix="/api/admin", tags=["admin"])


def _assert_dev_environment(request: Request | None) -> None:
    if os.environ.get("ENV") == "prod":
        raise HTTPException(status_code=403, detail="reseed disabled in prod")
    if request is not None and request.url.port == 8000:
        raise HTTPException(status_code=403, detail="reseed disabled on port 8000")
    if os.environ.get("QUANT_WARROOM_SEED") != "1":
        raise HTTPException(status_code=403, detail="QUANT_WARROOM_SEED != 1")


@router.post("/warroom/reseed")
async def admin_reseed(request: Request, force: bool = False) -> dict:
    _assert_dev_environment(request)
    report = await asyncio.to_thread(seed_mock_warroom, "mock-dev", 30, force)
    # Invalidate the route-level cache so the next GET /api/war-room reflects
    # the freshly seeded data immediately.
    try:
        from src.api.routes.war_room import invalidate_warroom_cache

        invalidate_warroom_cache()
    except Exception:
        pass
    return report
