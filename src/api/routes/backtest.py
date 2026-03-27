"""Backtest execution endpoint."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.api.helpers import run_strategy_backtest

router = APIRouter(prefix="/api", tags=["backtest"])


class BacktestRequest(BaseModel):
    strategy: str
    symbol: str = "TX"
    start: str = "2025-08-01"
    end: str = "2026-03-14"
    params: dict | None = None
    max_loss: float = 500_000.0
    initial_capital: float = 2_000_000.0


@router.post("/backtest/run")
async def run_backtest(req: BacktestRequest) -> dict:
    try:
        result = run_strategy_backtest(
            strategy_slug=req.strategy,
            symbol=req.symbol,
            start_str=req.start,
            end_str=req.end,
            initial_equity=req.initial_capital,
            strategy_params=req.params,
            max_loss=req.max_loss,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Backtest error: {exc}")
    # Convert numpy arrays to lists for JSON serialization
    import numpy as np
    for key in ("daily_returns", "bnh_returns"):
        if key in result and isinstance(result[key], np.ndarray):
            result[key] = result[key].tolist()
    return result
