"""Parameter registry endpoints — active params, run history, activation."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/api/params", tags=["params"])


@router.get("/active/{strategy:path}")
async def get_active_params(strategy: str) -> dict:
    """Return active optimized params or PARAM_SCHEMA defaults."""
    from src.strategies.param_registry import ParamRegistry

    registry = ParamRegistry()
    detail = registry.get_active_detail(strategy)
    registry.close()
    if detail:
        code_changed = None
        try:
            from src.strategies.code_hash import compute_strategy_hash

            current_hash, _ = compute_strategy_hash(strategy)
            code_changed = registry.check_code_hash_match(strategy, current_hash) is False
        except FileNotFoundError:
            code_changed = None
        return {**detail, "source": "registry", "code_changed": code_changed}
    # Fallback to schema defaults
    slug = "pyramid_wrapper" if strategy == "pyramid" else strategy
    try:
        from src.strategies.registry import get_defaults

        defaults = get_defaults(slug)
        return {"params": defaults, "source": "defaults"}
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Unknown strategy '{strategy}'")


@router.get("/runs/{run_id:int}/code")
async def get_run_code(run_id: int) -> dict:
    """Return the stored strategy source code for a specific run."""
    from src.strategies.param_registry import ParamRegistry

    registry = ParamRegistry()
    row = registry._conn.execute(
        "SELECT strategy_hash, strategy_code, strategy FROM param_runs WHERE id = ?",
        (run_id,),
    ).fetchone()
    registry.close()
    if row is None:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
    return {
        "run_id": run_id,
        "strategy": row["strategy"],
        "strategy_hash": row["strategy_hash"],
        "strategy_code": row["strategy_code"],
    }


@router.get("/runs/{strategy:path}")
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
            "SELECT strategy FROM param_candidates WHERE id = ?",
            (candidate_id,),
        ).fetchone()["strategy"]
    )
    registry.close()
    return {"status": "activated", "candidate_id": candidate_id, **(detail or {})}


@router.delete("/runs/{run_id}")
async def delete_run(run_id: int) -> dict:
    """Delete a run and its associated trials and candidates.

    If the deleted run held the active candidate, auto-activates the
    remaining candidate with the highest sortino.
    """
    from src.strategies.param_registry import ParamRegistry

    registry = ParamRegistry()
    try:
        info = registry.delete_run(run_id)
    except ValueError as exc:
        registry.close()
        raise HTTPException(status_code=404, detail=str(exc))
    registry.close()
    return {"status": "deleted", "run_id": run_id, **info}


@router.get("/compare")
async def compare_runs(run_ids: str) -> list[dict]:
    """Compare multiple runs side-by-side. run_ids is comma-separated."""
    from src.strategies.param_registry import ParamRegistry

    ids = [int(x.strip()) for x in run_ids.split(",") if x.strip().isdigit()]
    if not ids:
        return []
    registry = ParamRegistry()
    results = registry.compare_runs(ids)
    registry.close()
    return results
