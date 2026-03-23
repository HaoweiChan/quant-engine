"""Database coverage endpoint."""
from __future__ import annotations

from fastapi import APIRouter

from src.dashboard.helpers import get_db_coverage

router = APIRouter(prefix="/api", tags=["data"])


@router.get("/coverage")
async def get_coverage() -> list[dict]:
    return get_db_coverage()
