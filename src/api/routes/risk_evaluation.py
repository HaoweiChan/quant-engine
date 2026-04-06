"""Risk evaluation endpoints: walk-forward validation and risk report."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/api", tags=["risk-evaluation"])


class WalkForwardRequest(BaseModel):
    strategy: str
    symbol: str = "TX"
    start: str = "2025-08-01"
    end: str = "2026-03-14"
    n_folds: int = 3
    session: str = "all"
    strategy_params: dict | None = None
    initial_equity: float = 2_000_000.0


@router.post("/walk-forward/{strategy_name:path}")
async def run_walk_forward(strategy_name: str, req: WalkForwardRequest) -> dict:
    """Run walk-forward OOS validation for a strategy."""
    try:
        from src.mcp_server.facade import run_walk_forward_for_mcp

        result = run_walk_forward_for_mcp(
            strategy=strategy_name,
            n_folds=req.n_folds,
            session=req.session,
            strategy_params=req.strategy_params,
            symbol=req.symbol,
            start=req.start,
            end=req.end,
            initial_equity=req.initial_equity,
        )
        if "error" in result:
            raise HTTPException(status_code=400, detail=result["error"])
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/risk-report/{strategy_name:path}")
async def get_risk_report(strategy_name: str, instrument: str = "TX") -> dict:
    """Get the risk sign-off report for a strategy."""
    try:
        from src.mcp_server.facade import run_risk_report_for_mcp

        result = run_risk_report_for_mcp(
            strategy=strategy_name,
            instrument=instrument,
        )
        if "error" in result:
            raise HTTPException(status_code=404, detail=result["error"])
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
