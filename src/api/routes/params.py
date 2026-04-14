"""Parameter registry endpoints — active params, run history, activation."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/api/params", tags=["params"])


def _resolve_full_strategy_path(registry, strategy: str) -> str:
    """Resolve a short strategy name to its full path if needed.

    If strategy contains '/', it's already a full path. Otherwise,
    look for a matching full path in param_runs.
    """
    if "/" in strategy:
        return strategy
    row = registry._conn.execute(
        "SELECT DISTINCT strategy FROM param_runs WHERE strategy LIKE ? LIMIT 1",
        (f"%/{strategy}",),
    ).fetchone()
    return row["strategy"] if row else strategy


@router.get("/active/{strategy:path}")
async def get_active_params(strategy: str) -> dict:
    """Return active optimized params or PARAM_SCHEMA defaults.

    Supports both full paths and short names (resolved via fallback lookup).
    """
    from src.strategies.param_registry import ParamRegistry

    registry = ParamRegistry()

    # Try to resolve short name to full path
    resolved_strategy = _resolve_full_strategy_path(registry, strategy)

    detail = registry.get_active_detail(resolved_strategy)
    if detail:
        code_changed = None
        try:
            from src.strategies.code_hash import compute_strategy_hash

            current_hash, _ = compute_strategy_hash(resolved_strategy)
            code_changed = registry.check_code_hash_match(resolved_strategy, current_hash) is False
        except FileNotFoundError:
            code_changed = None
        finally:
            registry.close()
        return {**detail, "source": "registry", "code_changed": code_changed}
    registry.close()
    # Fallback to schema defaults
    try:
        from src.strategies.registry import get_defaults

        defaults = get_defaults(resolved_strategy)
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


@router.get("/runs/{run_id:int}/result")
async def get_run_result(run_id: int) -> dict:
    """Return cached backtest result for a specific run.

    This allows viewing historical run results without re-running the backtest.
    Returns the full BacktestResult stored in result_json, or 404 if not cached.
    """
    from src.strategies.param_registry import ParamRegistry

    registry = ParamRegistry()
    result = registry.get_result_by_run_id(run_id)
    registry.close()
    if result is None:
        raise HTTPException(
            status_code=404,
            detail=f"No cached result for run {run_id}. Run the backtest to generate and cache the result.",
        )
    result["run_id"] = run_id
    result["cache_hit"] = True
    return result


@router.get("/runs/{strategy:path}")
async def get_run_history(strategy: str, limit: int = 20) -> dict:
    """Return optimization run history for a strategy.

    Supports both full paths (e.g. 'short_term/trend_following/night_session_long')
    and short names (e.g. 'night_session_long'). Short names are resolved to full paths.
    """
    from src.strategies.param_registry import ParamRegistry

    registry = ParamRegistry()
    resolved_strategy = _resolve_full_strategy_path(registry, strategy)
    runs = registry.get_run_history(resolved_strategy, limit=limit)
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
