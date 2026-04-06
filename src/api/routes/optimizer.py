"""Optimizer execution and status endpoints."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.api.helpers import (
    get_strategy_registry,
    get_optimizer_state,
    get_param_grid_for_strategy,
    start_optimizer_run,
)

router = APIRouter(prefix="/api", tags=["optimizer"])


class OptimizerRequest(BaseModel):
    strategy: str
    symbol: str = "TX"
    start: str = "2025-08-01"
    end: str = "2026-03-14"
    param_grid: dict[str, list]
    is_fraction: float = 0.8
    objective: str = "sortino"
    n_jobs: int = 1
    slippage_bps: float = 0.0
    commission_bps: float = 0.0
    commission_fixed_per_contract: float = 0.0


@router.post("/optimizer/run", status_code=202)
async def run_optimizer(req: OptimizerRequest) -> dict:
    from src.strategies.registry import get_info as _get_info
    try:
        _get_info(req.strategy)
    except KeyError:
        raise HTTPException(status_code=400, detail=f"Unknown strategy: {req.strategy}")
    started = start_optimizer_run(
        symbol=req.symbol,
        start_str=req.start,
        end_str=req.end,
        param_grid=req.param_grid,
        is_fraction=req.is_fraction,
        objective=req.objective,
        n_jobs=req.n_jobs,
        factory_module=info.module,
        factory_name=info.factory,
        slippage_bps=req.slippage_bps,
        commission_bps=req.commission_bps,
        commission_fixed_per_contract=req.commission_fixed_per_contract,
    )
    if not started:
        raise HTTPException(status_code=409, detail="Optimizer already running")
    return {"status": "started"}


@router.get("/optimizer/status")
async def optimizer_status() -> dict:
    return get_optimizer_state()
