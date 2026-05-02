"""Portfolio-level backtest, stress-test, and optimization endpoints."""
from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from typing import Literal

import numpy as np
import structlog
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from src.api.helpers import run_strategy_backtest
from src.core.portfolio_merger import PortfolioMerger, PortfolioMergerInput

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/portfolio", tags=["portfolio"])

_TAIPEI_TZ = timezone(timedelta(hours=8))


def _daily_timestamps_from_bar_epochs(
    bar_epochs: list[int], target_len: int,
) -> list[int]:
    """Down-sample bar-level epochs to one entry per unique calendar day.

    Mirrors the per-day grouping used to compute true_daily_returns in the
    MCP facade (`src/mcp_server/facade.py` line ~1257), which keys by the
    first 10 chars of the timestamp string — i.e. calendar date in Taipei
    local time. Truncates/pads to ``target_len`` so the returned series
    matches `PortfolioMerger.merged_equity_curve` exactly. Falls back to
    the input unchanged for trivially short inputs.
    """
    if len(bar_epochs) < 2 or target_len <= 0:
        return list(bar_epochs)[:target_len] if target_len > 0 else []
    daily: dict[str, int] = {}
    for epoch in bar_epochs:
        dt = datetime.fromtimestamp(int(epoch), tz=_TAIPEI_TZ)
        day = dt.strftime("%Y-%m-%d")
        daily[day] = int(epoch)
    series = list(daily.values())
    if len(series) >= target_len:
        return series[:target_len]
    # Pad with the last known epoch + 1 day per missing slot so the chart
    # still receives strictly-increasing timestamps.
    last = series[-1] if series else int(bar_epochs[0])
    while len(series) < target_len:
        last += 86_400
        series.append(last)
    return series


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
    commission_fixed_per_contract: float = 0.0


class PortfolioStressRequest(BaseModel):
    strategies: list[StrategyEntry]
    symbol: str = "TX"
    start: str = "2025-08-01"
    end: str = "2026-03-14"
    initial_capital: float = 2_000_000.0
    slippage_bps: float = 0.0
    commission_bps: float = 0.0
    commission_fixed_per_contract: float = 0.0
    n_paths: int = Field(500, ge=10, le=5000)
    n_days: int = Field(252, ge=20, le=1000)
    method: Literal["stationary", "circular", "garch"] = "stationary"
    ruin_threshold: float = Field(0.5, ge=0.01, le=0.99)
    seed: int | None = None


class PortfolioOptimizeRequest(BaseModel):
    strategies: list[StrategyEntry]
    symbol: str = "TX"
    start: str = "2025-08-01"
    end: str = "2026-03-14"
    initial_capital: float = 2_000_000.0
    min_weight: float = Field(0.10, ge=0.0, le=0.5, description="Minimum allocation per strategy")
    slippage_bps: float = 0.0
    commission_bps: float = 0.0
    commission_fixed_per_contract: float = 0.0


def _validate_strategies(strategies: list[StrategyEntry]) -> None:
    if len(strategies) < 2:
        raise HTTPException(400, "Portfolio requires at least 2 strategies")


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
                commission_fixed_per_contract=req.commission_fixed_per_contract,
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
        metrics = dict(bt.get("metrics", {}))
        dr_arr = np.asarray(dr, dtype=np.float64)
        n_days = len(dr_arr)
        if n_days > 0:
            total_ret = float(np.prod(1 + dr_arr) - 1)
            annual_factor = 252 / n_days if n_days > 0 else 1
            annual_vol = float(np.std(dr_arr) * np.sqrt(252))
            annual_ret = float((1 + total_ret) ** annual_factor - 1)
            metrics.setdefault("total_return", total_ret)
            metrics.setdefault("annual_return", annual_ret)
            metrics.setdefault("annual_vol", annual_vol)
            metrics.setdefault("n_days", n_days)
        # Normalise trade_signals to plain dicts for JSON serialisation
        raw_signals = bt.get("trade_signals", [])
        signals = [
            dict(s) if not isinstance(s, dict) else s
            for s in (raw_signals if raw_signals else [])
        ]
        eq_ts = bt.get("equity_timestamps", [])
        if hasattr(eq_ts, "tolist"):
            eq_ts = eq_ts.tolist()
        individual_summaries.append({
            "slug": entry.slug,
            "weight": entry.weight,
            "metrics": metrics,
            "equity_curve": bt.get("equity_curve", []),
            "trade_signals": signals,
            "equity_timestamps": eq_ts,
            "timeframe_minutes": bt.get("timeframe_minutes", 1),
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
    # Derive top-level timestamps/tf from the first strategy (shared bar grid).
    # PortfolioMerger.merged_equity_curve is at DAILY granularity (one entry per
    # trading day plus an initial-equity prefix). The bt result's
    # equity_timestamps array, in contrast, is bar-level (often 1-min). Indexing
    # `timestamps[0..N_days]` against bar-level epochs collapses the x-axis to
    # the first N_days minutes of data — visible as an "hours-only" axis on a
    # half-year backtest. Down-sample to one epoch per unique date and prepend
    # the (first - 1s) sentinel to align with the initial-equity prefix in the
    # merged curve.
    first_bt = bt_results[0] if bt_results else {}
    bar_eq_ts = first_bt.get("equity_timestamps", [])
    if hasattr(bar_eq_ts, "tolist"):
        bar_eq_ts = bar_eq_ts.tolist()
    daily_ts = _daily_timestamps_from_bar_epochs(
        bar_eq_ts, target_len=len(merged.merged_equity_curve),
    )
    return {
        "individual": individual_summaries,
        "merged_equity_curve": merged.merged_equity_curve,
        "merged_daily_returns": merged.merged_daily_returns,
        "merged_metrics": merged.metrics,
        "correlation_matrix": merged.correlation_matrix,
        "strategy_slugs": [e.slug for e in req.strategies],
        "equity_timestamps": daily_ts,
        "timeframe_minutes": first_bt.get("timeframe_minutes", 1),
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


@router.post("/optimize")
async def run_portfolio_optimize(req: PortfolioOptimizeRequest) -> dict:
    """Find optimal weight allocations across strategies.

    Runs backtests for each strategy, then optimizes weights for
    max Sharpe, max return, min drawdown, and risk parity.
    Returns Pareto front for multi-objective visualization.
    """
    _validate_strategies(req.strategies)
    from src.core.portfolio_optimizer import PortfolioOptimizer
    daily_returns: dict[str, np.ndarray] = {}
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
                commission_fixed_per_contract=req.commission_fixed_per_contract,
            )
        except ValueError as exc:
            raise HTTPException(404, f"Strategy '{entry.slug}': {exc}")
        except Exception as exc:
            raise HTTPException(500, f"Backtest error for '{entry.slug}': {exc}")
        dr = bt.get("daily_returns", [])
        if isinstance(dr, np.ndarray):
            dr = dr.tolist()
        daily_returns[entry.slug] = np.array(dr, dtype=np.float64)
    try:
        optimizer = PortfolioOptimizer(
            daily_returns=daily_returns,
            initial_capital=req.initial_capital,
            min_weight=req.min_weight,
        )
        result = optimizer.optimize()
    except Exception as exc:
        raise HTTPException(500, f"Optimization error: {exc}")
    output = {
        "strategy_slugs": result.strategy_slugs,
        "max_sharpe": asdict(result.max_sharpe),
        "max_return": asdict(result.max_return),
        "min_drawdown": asdict(result.min_drawdown),
        "risk_parity": asdict(result.risk_parity),
        "equal_weight": asdict(result.equal_weight),
        "pareto_front": [asdict(p) for p in result.pareto_front],
        "correlation_matrix": result.correlation_matrix,
        "individual_metrics": result.individual_metrics,
        "n_days": result.n_days,
    }
    # Auto-persist
    try:
        from src.core.portfolio_store import PortfolioStore
        store = PortfolioStore()
        run_id = store.save_optimization(
            result=output, symbol=req.symbol, start=req.start, end=req.end,
            initial_capital=req.initial_capital, min_weight=req.min_weight,
            slippage_bps=req.slippage_bps,
            commission_bps=req.commission_bps,
            commission_fixed_per_contract=req.commission_fixed_per_contract,
        )
        store.close()
        output["run_id"] = run_id
    except Exception as exc:
        logger.warning("portfolio_persistence_failed", error=str(exc))
    logger.info(
        "portfolio_optimization_completed",
        n_strategies=len(req.strategies),
        max_sharpe=result.max_sharpe.sharpe,
    )
    return output


@router.get("/saved")
async def list_saved_portfolios(symbol: str | None = None, limit: int = 10) -> dict:
    """List saved portfolio optimization runs with their allocations.

    Returns flattened allocation entries for easy dropdown population.
    Each entry includes run metadata and allocation details.
    """
    from src.core.portfolio_store import PortfolioStore

    try:
        store = PortfolioStore()
        runs = store.list_runs(symbol=symbol, limit=limit)
        store.close()
    except Exception as exc:
        logger.warning("portfolio_list_failed", error=str(exc))
        return {"portfolios": [], "error": str(exc)}

    # Flatten into allocation-centric entries for frontend dropdown
    portfolios: list[dict] = []
    for run in runs:
        for obj_key, alloc in run.get("allocations", {}).items():
            portfolios.append({
                "id": alloc["id"],
                "run_id": run["id"],
                "objective": alloc["objective"],
                "weights": alloc["weights"],
                "sharpe": alloc.get("sharpe"),
                "total_return": alloc.get("total_return"),
                "annual_return": alloc.get("annual_return"),
                "max_drawdown_pct": alloc.get("max_drawdown_pct"),
                "is_selected": bool(alloc.get("is_selected")),
                "symbol": run["symbol"],
                "start_date": run["start_date"],
                "end_date": run["end_date"],
                "strategy_slugs": run["strategy_slugs"],
                "n_strategies": run["n_strategies"],
                "run_at": run["run_at"],
                "slippage_bps": run.get("slippage_bps", 0.0),
                "commission_bps": run.get("commission_bps", 0.0),
                "commission_fixed_per_contract": run.get("commission_fixed_per_contract", 0.0),
            })

    logger.info("portfolio_list_returned", count=len(portfolios))
    return {"portfolios": portfolios}
