"""Parameter registry endpoints — active params, run history, activation."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/api/params", tags=["params"])


@router.get("/active/{strategy}")
async def get_active_params(strategy: str) -> dict:
    """Return active optimized params or PARAM_SCHEMA defaults."""
    from src.strategies.param_registry import ParamRegistry
    registry = ParamRegistry()
    detail = registry.get_active_detail(strategy)
    registry.close()
    if detail:
        return {**detail, "source": "registry"}
    # Fallback to schema defaults
    slug = "pyramid_wrapper" if strategy == "pyramid" else strategy
    try:
        from src.strategies.registry import get_defaults
        defaults = get_defaults(slug)
        return {"params": defaults, "source": "defaults"}
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Unknown strategy '{strategy}'")


@router.get("/runs/{strategy}")
async def get_run_history(strategy: str, limit: int = 20) -> dict:
    """Return optimization run history for a strategy."""
    from src.strategies.param_registry import ParamRegistry
    registry = ParamRegistry()
    runs = registry.get_run_history(strategy, limit=limit)
    registry.close()
    return {"runs": runs, "count": len(runs)}


@router.post("/activate/{candidate_id}")
async def activate_candidate(candidate_id: int) -> dict:
    """Activate a parameter candidate."""
    from src.strategies.param_registry import ParamRegistry
    registry = ParamRegistry()
    try:
        registry.activate(candidate_id)
    except ValueError as exc:
        registry.close()
        raise HTTPException(status_code=404, detail=str(exc))
    detail = registry.get_active_detail(
        registry._conn.execute(
            "SELECT strategy FROM param_candidates WHERE id = ?", (candidate_id,),
        ).fetchone()["strategy"]
    )
    registry.close()
    return {"status": "activated", "candidate_id": candidate_id, **(detail or {})}
