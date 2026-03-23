"""Strategy listing endpoint."""
from __future__ import annotations

from fastapi import APIRouter

from src.dashboard.helpers import STRATEGY_REGISTRY, get_param_grid_for_strategy

router = APIRouter(prefix="/api", tags=["strategies"])


@router.get("/strategies")
async def list_strategies() -> list[dict]:
    result = []
    for slug, info in STRATEGY_REGISTRY.items():
        grid = get_param_grid_for_strategy(slug)
        result.append({
            "slug": slug,
            "name": info.name,
            "param_grid": grid,
        })
    return result
