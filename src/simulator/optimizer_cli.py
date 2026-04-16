"""CLI entrypoint for the strategy optimizer.

Usage (invoked by the dashboard as a subprocess):
    python -m src.simulator.optimizer_cli \\
        --config /path/to/config.json \\
        --output /path/to/result.json

Config JSON schema:
{
    "symbol":       "TX",
    "start":        "2025-08-01",
    "end":          "2026-03-14",
    "param_grid":   {"bb_len": [15, 20, 25], "rsi_oversold": [25, 30], ...},
    "is_fraction":  0.8,
    "objective":    "sortino",
    "n_jobs":       1
}

Result JSON schema:
{
    "status":       "ok" | "error",
    "error":        null | "<message>",
    "trials":       [ {param_cols..., metric_cols...}, ... ],
    "best_params":  {...},
    "warnings":     [...],
    "is_metrics":   {...},
    "oos_metrics":  {...} | null,
    "is_equity":    [...],
    "oos_equity":   [...],
    "is_bars":      int,
    "oos_bars":     int,
    "param_keys":   [...],
    "objective":    "sortino",
    "symbol":       "TX",
    "start":        "...",
    "end":          "...",
    "is_fraction":  0.8
}
"""
from __future__ import annotations

import sys
import json
import argparse
from pathlib import Path
from typing import TYPE_CHECKING
from statistics import mean as _mean

if TYPE_CHECKING:
    from src.simulator.types import OptimizerResult


def main() -> None:
    parser = argparse.ArgumentParser(description="Run strategy optimizer and write results to JSON")
    parser.add_argument("--config", required=True, help="Path to JSON config file")
    parser.add_argument("--output", required=True, help="Path to write JSON result file")
    args = parser.parse_args()

    config_path = Path(args.config)
    output_path = Path(args.output)

    try:
        cfg = json.loads(config_path.read_text())
        result_data, optimizer_result = _run_optimizer(cfg)
        # Persist full result to param registry
        try:
            from src.strategies.param_registry import ParamRegistry
            registry = ParamRegistry()
            run_id = registry.save_run(
                result=optimizer_result,
                strategy=cfg.get("factory_name", "").replace("create_", "").replace("_engine", ""),
                symbol=cfg["symbol"],
                objective=cfg.get("objective", "sortino"),
                train_start=cfg.get("start"),
                train_end=cfg.get("end"),
                is_fraction=float(cfg.get("is_fraction", 0.8)),
                search_type="grid",
                source="dashboard",
            )
            registry.close()
            result_data["run_id"] = run_id
        except Exception:
            pass  # registry save is best-effort; don't fail the CLI
        output_path.write_text(json.dumps({**result_data, "status": "ok"}))
    except Exception as exc:
        output_path.write_text(json.dumps({"status": "error", "error": str(exc)}))
        sys.exit(1)


def _run_optimizer(cfg: dict) -> tuple[dict, "OptimizerResult"]:
    import importlib
    from datetime import datetime

    from src.adapters.taifex import TaifexAdapter
    from src.core.types import ImpactParams
    from src.data.db import Database
    from src.simulator.fill_model import MarketImpactFillModel
    from src.simulator.strategy_optimizer import StrategyOptimizer

    factory_module = cfg.get("factory_module", "src.strategies.atr_mean_reversion")
    factory_name = cfg.get("factory_name", "create_atr_mean_reversion_engine")
    mod = importlib.import_module(factory_module)
    engine_factory = getattr(mod, factory_name)

    symbol: str = cfg["symbol"]
    start_dt = datetime.fromisoformat(cfg["start"])
    end_dt = datetime.fromisoformat(cfg["end"])
    param_grid: dict = cfg["param_grid"]
    is_fraction: float = float(cfg.get("is_fraction", 0.8))
    objective: str = cfg.get("objective", "sortino")
    n_jobs: int = int(cfg.get("n_jobs", 1))
    slippage_bps: float = float(cfg.get("slippage_bps", 0.0))
    commission_bps: float = float(cfg.get("commission_bps", 0.0))
    commission_fixed_per_contract: float = float(cfg.get("commission_fixed_per_contract", 0.0))
    mode: str = cfg.get("mode", "research")
    min_trade_count: int = int(cfg.get("min_trade_count", 30))
    min_expectancy: float = float(cfg.get("min_expectancy", 0.0))
    min_oos_objective: float = float(cfg.get("min_oos_objective", 0.0))

    db = Database()
    raw = db.get_ohlcv(symbol, start_dt, end_dt)

    if not raw:
        raise ValueError(f"No data for {symbol} in {cfg['start']}–{cfg['end']}")

    # Compute true daily ATR from daily high-low ranges, NOT per-bar ranges.
    _daily_hl: dict[str, tuple[float, float]] = {}
    for b in raw:
        d = b.timestamp.date() if hasattr(b.timestamp, "date") else str(b.timestamp)[:10]
        if d not in _daily_hl:
            _daily_hl[d] = (b.high, b.low)
        else:
            prev = _daily_hl[d]
            _daily_hl[d] = (max(prev[0], b.high), min(prev[1], b.low))
    daily_ranges = [hi - lo for hi, lo in _daily_hl.values() if hi > lo]
    daily_atr = _mean(daily_ranges) if daily_ranges else _mean(b.high - b.low for b in raw)
    bars = [
        {"symbol": symbol, "price": b.close, "open": b.open, "high": b.high,
         "low": b.low, "close": b.close, "daily_atr": daily_atr, "timestamp": b.timestamp}
        for b in raw
    ]
    timestamps = [b.timestamp for b in raw]

    impact_params = ImpactParams(
        spread_bps=slippage_bps,
        commission_bps=commission_bps,
        commission_fixed_per_contract=commission_fixed_per_contract,
    )

    opt = StrategyOptimizer(
        adapter=TaifexAdapter(),
        fill_model=MarketImpactFillModel(params=impact_params),
        n_jobs=n_jobs,
        mode=mode,
        min_trade_count=min_trade_count,
        min_expectancy=min_expectancy,
        min_oos_objective=min_oos_objective,
    )
    result = opt._grid_search(
        engine_factory,
        param_grid,
        bars,
        timestamps,
        objective=objective,
        is_fraction=is_fraction,
    )

    param_keys = list(param_grid.keys())
    is_end = int(len(bars) * is_fraction)

    is_eq = result.best_is_result.equity_curve
    oos_eq = result.best_oos_result.equity_curve if result.best_oos_result else []
    # Downsample equity curves to ≤500 points for JSON size
    step_is = max(1, len(is_eq) // 500)
    step_oos = max(1, len(oos_eq) // 500) if oos_eq else 1

    return {
        "trials": result.trials.to_dicts(),
        "best_params": result.best_params,
        "warnings": result.warnings,
        "mode": result.mode,
        "promotable": result.promotable,
        "gate_results": result.gate_results,
        "gate_details": result.gate_details,
        "objective_direction": result.objective_direction,
        "disqualified_trials": result.disqualified_trials,
        "is_metrics": result.best_is_result.metrics,
        "oos_metrics": result.best_oos_result.metrics if result.best_oos_result else None,
        "is_equity": is_eq[::step_is],
        "oos_equity": oos_eq[::step_oos],
        "is_bars": is_end,
        "oos_bars": len(bars) - is_end,
        "param_keys": param_keys,
        "objective": objective,
        "symbol": symbol,
        "start": cfg["start"],
        "end": cfg["end"],
        "is_fraction": is_fraction,
    }, result


if __name__ == "__main__":
    main()
