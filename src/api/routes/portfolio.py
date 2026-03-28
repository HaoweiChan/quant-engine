"""Portfolio-level backtest and stress-test endpoints for multi-strategy analysis."""
from __future__ import annotations

from typing import Literal

import numpy as np
import structlog
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from src.api.helpers import run_strategy_backtest
from src.core.portfolio_merger import PortfolioMerger, PortfolioMergerInput

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/portfolio", tags=["portfolio"])


class StrategyEntry(BaseModel):
    slug: str
    params: dict | None = None
    weight: float = 1.0


class PortfolioBacktestRequest(BaseModel):
    strategies: list[StrategyEntry]
    symbol: str = "TX"
    start: str = "2025-08-01"
    end: str = "2026-03-14"
    initial_capital: float = 2_000_000.0
    slippage_bps: float = 0.0
    commission_bps: float = 0.0


class PortfolioStressRequest(BaseModel):
    strategies: list[StrategyEntry]
    symbol: str = "TX"
    start: str = "2025-08-01"
    end: str = "2026-03-14"
    initial_capital: float = 2_000_000.0
    slippage_bps: float = 0.0
    commission_bps: float = 0.0
    n_paths: int = Field(500, ge=10, le=5000)
    n_days: int = Field(252, ge=20, le=1000)
    method: Literal["stationary", "circular", "garch"] = "stationary"
    ruin_threshold: float = Field(0.5, ge=0.01, le=0.99)
    seed: int | None = None


def _validate_strategies(strategies: list[StrategyEntry]) -> None:
    if len(strategies) < 2:
        raise HTTPException(400, "Portfolio requires at least 2 strategies")
    if len(strategies) > 3:
        raise HTTPException(400, "Maximum 3 strategies allowed")


def _run_individual_backtests(
    req: PortfolioBacktestRequest | PortfolioStressRequest,
) -> list[dict]:
    results: list[dict] = []
    for entry in req.strategies:
        try:
            bt = run_strategy_backtest(
                strategy_slug=entry.slug,
                symbol=req.symbol,
                start_str=req.start,
                end_str=req.end,
                initial_equity=req.initial_capital,
                strategy_params=entry.params,
                slippage_bps=req.slippage_bps,
                commission_bps=req.commission_bps,
            )
        except ValueError as exc:
            raise HTTPException(404, f"Strategy '{entry.slug}': {exc}")
        except Exception as exc:
            raise HTTPException(500, f"Backtest error for '{entry.slug}': {exc}")
        results.append(bt)
    return results


@router.post("/backtest")
async def run_portfolio_backtest(req: PortfolioBacktestRequest) -> dict:
    _validate_strategies(req.strategies)
    bt_results = _run_individual_backtests(req)

    # Build merger inputs
    inputs: list[PortfolioMergerInput] = []
    individual_summaries: list[dict] = []
    for entry, bt in zip(req.strategies, bt_results):
        dr = bt.get("daily_returns", [])
        if isinstance(dr, np.ndarray):
            dr = dr.tolist()
        inputs.append(PortfolioMergerInput(
            daily_returns=dr,
            strategy_slug=entry.slug,
            weight=entry.weight,
        ))
        individual_summaries.append({
            "slug": entry.slug,
            "weight": entry.weight,
            "metrics": bt.get("metrics", {}),
            "equity_curve": bt.get("equity_curve", []),
        })

    merger = PortfolioMerger(initial_capital=req.initial_capital)
    try:
        merged = merger.merge(inputs)
    except ValueError as exc:
        raise HTTPException(422, str(exc))

    logger.info(
        "portfolio_backtest_completed",
        n_strategies=len(req.strategies),
        n_days=merged.metrics.get("n_days", 0),
    )
    return {
        "individual": individual_summaries,
        "merged_equity_curve": merged.merged_equity_curve,
        "merged_daily_returns": merged.merged_daily_returns,
        "merged_metrics": merged.metrics,
        "correlation_matrix": merged.correlation_matrix,
        "strategy_slugs": [e.slug for e in req.strategies],
    }


@router.post("/stress-test")
async def run_portfolio_stress_test(req: PortfolioStressRequest) -> dict:
    _validate_strategies(req.strategies)
    bt_results = _run_individual_backtests(req)

    inputs: list[PortfolioMergerInput] = []
    for entry, bt in zip(req.strategies, bt_results):
        dr = bt.get("daily_returns", [])
        if isinstance(dr, np.ndarray):
            dr = dr.tolist()
        inputs.append(PortfolioMergerInput(
            daily_returns=dr,
            strategy_slug=entry.slug,
            weight=entry.weight,
        ))

    merger = PortfolioMerger(initial_capital=req.initial_capital)
    try:
        merged = merger.merge(inputs)
    except ValueError as exc:
        raise HTTPException(422, str(exc))

    returns = np.asarray(merged.merged_daily_returns, dtype=np.float64)
    if np.all(returns == 0) or np.nanstd(returns) < 1e-12:
        raise HTTPException(422, "Merged returns are all zero — strategies produced no meaningful trades")
    if req.method == "garch" and len(returns) < 50:
        raise HTTPException(422, "Insufficient data for GARCH fitting (need >= 50 daily returns)")

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

    path_arr = np.array(result.paths)
    percentile_keys = [5, 25, 50, 75, 95]
    bands: dict[str, list[float]] = {}
    for p in percentile_keys:
        bands[f"p{p}"] = np.percentile(path_arr, p, axis=0).tolist()

    logger.info(
        "portfolio_stress_test_completed",
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
