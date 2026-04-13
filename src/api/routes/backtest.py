"""Backtest execution endpoint."""
from __future__ import annotations

import asyncio
import json
from functools import partial

from fastapi import APIRouter
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

router = APIRouter(prefix="/api", tags=["backtest"])


class BacktestRequest(BaseModel):
    strategy: str
    symbol: str = "TX"
    start: str = "2025-08-01"
    end: str = "2026-03-14"
    params: dict | None = None
    max_loss: float = 500_000.0
    initial_capital: float = 2_000_000.0
    slippage_bps: float = 0.0
    commission_bps: float = 0.0
    commission_fixed_per_contract: float = 0.0
    provenance: dict | None = None
    intraday: bool = False


def _merge_strategy_params(req: BacktestRequest) -> dict:
    """Build the merged strategy_params dict used by both cache lookup and full run."""
    merged = dict(req.params or {})
    merged["max_loss"] = req.max_loss
    if req.slippage_bps:
        merged["slippage_bps"] = req.slippage_bps
    if req.commission_bps:
        merged["commission_bps"] = req.commission_bps
    if req.commission_fixed_per_contract:
        merged["commission_fixed_per_contract"] = req.commission_fixed_per_contract
    return merged


@router.post("/backtest/run", response_model=None)
async def run_backtest(req: BacktestRequest):
    """Run a backtest — returns cached result instantly or streams heartbeats for fresh runs."""
    loop = asyncio.get_running_loop()

    # Step 1: Fast cache check in a thread (~10ms SQLite read).
    from src.mcp_server.facade import lookup_backtest_cache

    merged_params = _merge_strategy_params(req)
    cached = await loop.run_in_executor(
        None,
        partial(
            lookup_backtest_cache,
            symbol=req.symbol,
            start=req.start,
            end=req.end,
            strategy=req.strategy,
            strategy_params=merged_params,
            intraday=req.intraday,
        ),
    )
    if cached is not None:
        if req.provenance:
            cached["provenance"] = req.provenance
        return JSONResponse(cached)

    # Step 2: Check if this is a constrained environment (VPS with limited resources).
    # If so, refuse to run compute-heavy backtests — user must run via MCP on dev machine.
    from src.mcp_server.facade import _classify_hardware
    if _classify_hardware() == "constrained":
        return JSONResponse({
            "status": "compute_required",
            "cached": False,
            "message": "VPS cannot run backtests due to limited resources. "
                       "Run via MCP tools on dev machine, then view cached results here.",
        })

    # Step 3: Cache miss — run full backtest in thread pool (no fork, no pickle).
    from src.api.helpers import run_strategy_backtest

    future = loop.run_in_executor(
        None,
        partial(
            run_strategy_backtest,
            strategy_slug=req.strategy,
            symbol=req.symbol,
            start_str=req.start,
            end_str=req.end,
            initial_equity=req.initial_capital,
            strategy_params=req.params,
            max_loss=req.max_loss,
            slippage_bps=req.slippage_bps,
            commission_bps=req.commission_bps,
            commission_fixed_per_contract=req.commission_fixed_per_contract,
            provenance=req.provenance,
            intraday=req.intraday,
        ),
    )

    async def _stream():
        """Yield a space every 5s while the backtest runs, then the JSON result."""
        while True:
            try:
                result = await asyncio.wait_for(asyncio.shield(future), timeout=5.0)
                yield json.dumps(result)
                return
            except asyncio.TimeoutError:
                yield " "
            except ValueError as exc:
                yield json.dumps({"detail": str(exc)})
                return
            except Exception as exc:
                yield json.dumps({"detail": f"Backtest error: {exc}"})
                return

    return StreamingResponse(_stream(), media_type="application/json")
