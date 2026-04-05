"""Strategy listing endpoint."""
from __future__ import annotations

from fastapi import APIRouter

from src.api.helpers import get_strategy_registry, get_param_grid_for_strategy

router = APIRouter(prefix="/api", tags=["strategies"])


def _serialize_registry() -> list[dict]:
    result = []
    for slug, info in get_strategy_registry().items():
        grid = get_param_grid_for_strategy(slug)
        result.append({
            "slug": slug,
            "name": info.name,
            "param_grid": grid,
            "holding_period": info.holding_period,
            "signal_timeframe": info.signal_timeframe,
            "stop_architecture": info.stop_architecture,
            "category": info.category,
            "tradeable_sessions": info.tradeable_sessions,
        })
    return result


@router.get("/strategies")
async def list_strategies() -> list[dict]:
    return _serialize_registry()


@router.post("/strategies/reload")
async def reload_strategies() -> dict:
    """Invalidate the strategy registry cache and re-discover all strategies."""
    from src.strategies.registry import invalidate
    invalidate()
    strategies = _serialize_registry()
    return {"reloaded": len(strategies), "slugs": [s["slug"] for s in strategies]}
