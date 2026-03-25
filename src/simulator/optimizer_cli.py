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
    "objective":    "sharpe",
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
    "objective":    "sharpe",
    "symbol":       "TX",
    "start":        "...",
    "end":          "...",
    "is_fraction":  0.8
}
"""
from __future__ import annotations

import argparse
import json
import sys
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
                objective=cfg.get("objective", "sharpe"),
                train_start=cfg.get("start"),
                train_end=cfg.get("end"),
                is_fraction=float(cfg.get("is_fraction", 0.8)),
                search_type="grid",
                source="dashboard",
            )
            # Auto-activate best candidate
            best_cand = registry._conn.execute(
                "SELECT id FROM param_candidates WHERE run_id = ? AND label LIKE 'best_%' LIMIT 1",
                (run_id,),
            ).fetchone()
            if best_cand:
                registry.activate(best_cand["id"])
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
    objective: str = cfg.get("objective", "sharpe")
    n_jobs: int = int(cfg.get("n_jobs", 1))

    db_path = Path(__file__).resolve().parent.parent.parent / "data" / "taifex_data.db"
    db = Database(f"sqlite:///{db_path}")
    raw = db.get_ohlcv(symbol, start_dt, end_dt)

    if not raw:
        raise ValueError(f"No data for {symbol} in {cfg['start']}–{cfg['end']}")

    daily_atr = _mean(b.high - b.low for b in raw)
    bars = [
        {"symbol": symbol, "price": b.close, "open": b.open, "high": b.high,
         "low": b.low, "close": b.close, "daily_atr": daily_atr, "timestamp": b.timestamp}
        for b in raw
    ]
    timestamps = [b.timestamp for b in raw]

    opt = StrategyOptimizer(
        adapter=TaifexAdapter(),
        fill_model=MarketImpactFillModel(),
        n_jobs=n_jobs,
    )
    result = opt.grid_search(
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
