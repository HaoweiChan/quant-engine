"""Backtest execution endpoint."""
from __future__ import annotations

import asyncio
import json
import multiprocessing
from concurrent.futures import ProcessPoolExecutor
from functools import partial

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

router = APIRouter(prefix="/api", tags=["backtest"])

# Use a process pool so CPU-bound backtests don't hold the GIL and block
# the event loop.  "fork" is required so the child can import the same
# modules without re-initialising the whole app.
_ctx = multiprocessing.get_context("fork")
_pool = ProcessPoolExecutor(max_workers=2, mp_context=_ctx)


def _run_backtest_in_worker(
    strategy_slug: str,
    symbol: str,
    start_str: str,
    end_str: str,
    initial_equity: float,
    strategy_params: dict | None,
    max_loss: float,
    slippage_bps: float,
    commission_bps: float,
    commission_fixed_per_contract: float,
    provenance: dict | None,
    intraday: bool,
) -> dict:
    """Runs inside a forked child process — free of GIL contention."""
    import numpy as np

    # Forked workers may hold a stale strategy registry / factory cache from
    # the moment they were forked — new strategies added since won't be
    # visible. Invalidate both caches on every call so the worker always
    # re-discovers strategies from disk.
    from src.strategies.registry import invalidate as _invalidate_registry
    from src.mcp_server import facade as _facade

    _invalidate_registry()
    _facade._factory_cache.clear()

    from src.api.helpers import run_strategy_backtest

    result = run_strategy_backtest(
        strategy_slug=strategy_slug,
        symbol=symbol,
        start_str=start_str,
        end_str=end_str,
        initial_equity=initial_equity,
        strategy_params=strategy_params,
        max_loss=max_loss,
        slippage_bps=slippage_bps,
        commission_bps=commission_bps,
        commission_fixed_per_contract=commission_fixed_per_contract,
        provenance=provenance,
        intraday=intraday,
    )
    # Convert numpy arrays to lists for JSON serialization (must happen
    # inside the worker because numpy arrays can't be pickled across processes).
    for key in ("daily_returns", "bnh_returns"):
        if key in result and isinstance(result[key], np.ndarray):
            result[key] = result[key].tolist()
    return result


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


@router.post("/backtest/run")
async def run_backtest(req: BacktestRequest) -> StreamingResponse:
    """Run a backtest, streaming whitespace heartbeats to keep the proxy alive."""
    loop = asyncio.get_running_loop()
    future = loop.run_in_executor(
        _pool,
        partial(
            _run_backtest_in_worker,
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
                # Done — yield the JSON payload
                yield json.dumps(result)
                return
            except asyncio.TimeoutError:
                # Backtest still running — send a whitespace heartbeat
                yield " "
            except ValueError as exc:
                yield json.dumps({"detail": str(exc)})
                return
            except Exception as exc:
                yield json.dumps({"detail": f"Backtest error: {exc}"})
                return

    return StreamingResponse(_stream(), media_type="application/json")
