"""POST /api/monte-carlo — server-side block-bootstrap Monte Carlo simulation."""
from __future__ import annotations

from typing import Literal

import numpy as np
import structlog
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from src.api.helpers import run_strategy_backtest

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/api", tags=["monte-carlo"])


class MonteCarloRequest(BaseModel):
    strategy: str
    symbol: str = "TX"
    start: str = "2025-08-01"
    end: str = "2026-03-14"
    params: dict | None = None
    initial_capital: float = 2_000_000.0
    slippage_bps: float = 0.0
    commission_bps: float = 0.0
    commission_fixed_per_contract: float = 0.0
    n_paths: int = Field(500, ge=10, le=5000)
    n_days: int = Field(252, ge=20, le=1000)
    method: Literal["stationary", "circular", "garch"] = "stationary"
    block_length: int | None = None
    ruin_threshold: float = Field(0.5, ge=0.01, le=0.99)
    seed: int | None = None


@router.post("/monte-carlo")
async def run_monte_carlo(req: MonteCarloRequest) -> dict:
    # 1) Run the underlying backtest to get daily returns
    try:
        bt = run_strategy_backtest(
            strategy_slug=req.strategy,
            symbol=req.symbol,
            start_str=req.start,
            end_str=req.end,
            initial_equity=req.initial_capital,
            strategy_params=req.params,
            slippage_bps=req.slippage_bps,
            commission_bps=req.commission_bps,
            commission_fixed_per_contract=req.commission_fixed_per_contract,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Backtest error: {exc}")
    daily_returns = bt.get("daily_returns")
    if daily_returns is None or len(daily_returns) == 0:
        raise HTTPException(status_code=422, detail="Backtest produced no daily returns")
    returns = np.asarray(daily_returns, dtype=np.float64)
    if np.all(returns == 0) or np.nanstd(returns) < 1e-12:
        raise HTTPException(
            status_code=422,
            detail="Strategy produced no meaningful trades — daily returns are all zero. "
            "Check that the strategy generates trades in the backtest date range.",
        )
    if req.method == "garch" and len(returns) < 50:
        raise HTTPException(
            status_code=422,
            detail="Insufficient data for GARCH fitting (need >= 50 daily returns)",
        )
    # 2) Run the simulation
    from src.monte_carlo.block_bootstrap import BlockBootstrapMC
    mc = BlockBootstrapMC(
        returns=returns,
        initial_equity=req.initial_capital,
        ruin_threshold=req.ruin_threshold,
    )
    mc.fit(method=req.method)
    result = mc.simulate(
        n_paths=req.n_paths,
        n_days=req.n_days,
        method=req.method,
        seed=req.seed,
    )
    # 3) Build percentile bands for the fan chart (5th/25th/50th/75th/95th at each day)
    path_arr = np.array(result.paths)
    percentile_keys = [5, 25, 50, 75, 95]
    bands: dict[str, list[float]] = {}
    for p in percentile_keys:
        bands[f"p{p}"] = np.percentile(path_arr, p, axis=0).tolist()
    logger.info(
        "monte_carlo_completed",
        method=req.method,
        n_paths=req.n_paths,
        n_days=req.n_days,
        var_95=result.var_95,
    )
    return {
        "var_95": result.var_95,
        "var_99": result.var_99,
        "cvar_95": result.cvar_95,
        "cvar_99": result.cvar_99,
        "median_final": result.median_final,
        "prob_ruin": result.prob_ruin,
        "method": result.method,
        "n_paths": result.n_paths,
        "n_days": result.n_days,
        "bands": bands,
    }
