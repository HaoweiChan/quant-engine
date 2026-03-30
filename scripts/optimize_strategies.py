"""Optimize ema_trend_pullback and atr_mean_reversion with seed architecture guidelines."""
import sys
import json
from datetime import datetime
from pathlib import Path
from statistics import mean as _mean

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.data.db import Database
from src.mcp_server.facade import resolve_factory
from src.strategies.registry import validate_and_clamp
from src.simulator.strategy_optimizer import StrategyOptimizer
from src.simulator.fill_model import MarketImpactFillModel
from src.core.types import ImpactParams


def load_data(symbol: str, start: str, end: str):
    db_path = Path(__file__).resolve().parent.parent / "data" / "taifex_data.db"
    db = Database(f"sqlite:///{db_path}")
    raw = db.get_ohlcv(symbol, datetime.fromisoformat(start), datetime.fromisoformat(end))
    if not raw:
        print(f"No data for {symbol} {start}-{end}")
        sys.exit(1)
    daily_ranges = [b.high - b.low for b in raw]
    daily_atr = _mean(daily_ranges) if daily_ranges else 0.0
    bars = [
        {
            "symbol": symbol,
            "price": b.close,
            "open": b.open,
            "high": b.high,
            "low": b.low,
            "close": b.close,
            "volume": float(b.volume),
            "daily_atr": daily_atr,
            "timestamp": b.timestamp,
        }
        for b in raw
    ]
    timestamps = [b.timestamp for b in raw]
    print(f"Loaded {len(bars)} bars, daily_atr={daily_atr:.1f}")
    return bars, timestamps


def run_baseline(strategy: str, bars, timestamps):
    """Run a baseline backtest with default params."""
    factory = resolve_factory(strategy)
    engine = factory()
    from src.simulator.backtester import BacktestRunner
    from src.adapters.taifex import TaifexAdapter
    fill_model = MarketImpactFillModel(
        params=ImpactParams(spread_bps=1.0, commission_bps=1.0)
    )
    adapter = TaifexAdapter()
    runner = BacktestRunner(
        config=lambda: factory(),
        adapter=adapter,
        fill_model=fill_model,
        initial_equity=2_000_000.0,
    )
    result = runner.run(bars, timestamps=timestamps)
    m = result.metrics
    print(f"\n=== {strategy} BASELINE ===")
    print(f"  Trades:    {m.get('trade_count', 0):.0f}")
    print(f"  Win Rate:  {m.get('win_rate', 0):.1%}")
    print(f"  Sharpe:    {m.get('sharpe', 0):.3f}")
    print(f"  Calmar:    {m.get('calmar', 0):.3f}")
    print(f"  PF:        {m.get('profit_factor', 0):.3f}")
    print(f"  MaxDD:     {m.get('max_drawdown_pct', 0):.3%}")
    print(f"  Composite: {m.get('composite_fitness', -9999):.3f}")
    print(f"  AvgHold:   {m.get('avg_holding_period', 0):.2f}h")
    total_pnl = result.equity_curve[-1] - result.equity_curve[0] if result.equity_curve else 0
    print(f"  PnL:       {total_pnl:,.0f}")
    return m


def run_sweep(strategy: str, sweep_params: dict, base_params: dict, bars, timestamps):
    """Run a parameter sweep using composite_fitness."""
    from src.adapters.taifex import TaifexAdapter
    fill_model = MarketImpactFillModel(
        params=ImpactParams(spread_bps=1.0, commission_bps=1.0)
    )
    adapter = TaifexAdapter()
    factory = resolve_factory(strategy)

    optimizer = StrategyOptimizer(
        adapter,
        fill_model=fill_model,
        mode="research",
        min_trade_count=10,
        min_expectancy=0.0,
    )

    param_grid = {}
    for k, v in sweep_params.items():
        param_grid[k] = v

    clamped, warnings = validate_and_clamp(strategy, base_params)
    if warnings:
        print(f"  Param warnings: {warnings}")

    result = optimizer.grid_search(
        engine_factory=lambda **p: factory(**{**clamped, **p}),
        param_grid=param_grid,
        bars=bars,
        timestamps=timestamps,
        objective="composite_fitness",
        is_fraction=0.8,
    )

    print(f"\n=== {strategy} SWEEP RESULTS ===")
    print(f"  Best params: {result.best_params}")
    m_is = result.best_is_result.metrics
    print(f"  IS Trades:    {m_is.get('trade_count', 0):.0f}")
    print(f"  IS Win Rate:  {m_is.get('win_rate', 0):.1%}")
    print(f"  IS Sharpe:    {m_is.get('sharpe', 0):.3f}")
    print(f"  IS Calmar:    {m_is.get('calmar', 0):.3f}")
    print(f"  IS PF:        {m_is.get('profit_factor', 0):.3f}")
    print(f"  IS Composite: {m_is.get('composite_fitness', -9999):.3f}")
    if result.best_oos_result:
        m_oos = result.best_oos_result.metrics
        print(f"  OOS Trades:    {m_oos.get('trade_count', 0):.0f}")
        print(f"  OOS Win Rate:  {m_oos.get('win_rate', 0):.1%}")
        print(f"  OOS Sharpe:    {m_oos.get('sharpe', 0):.3f}")
        print(f"  OOS Calmar:    {m_oos.get('calmar', 0):.3f}")
        print(f"  OOS PF:        {m_oos.get('profit_factor', 0):.3f}")
        print(f"  OOS Composite: {m_oos.get('composite_fitness', -9999):.3f}")
    print(f"  Gates: {result.gate_results}")
    print(f"  Promotable: {result.promotable}")

    trials = result.trials.to_dicts() if len(result.trials) > 0 else []
    if trials:
        print(f"\n  Top 5 trials:")
        for i, t in enumerate(trials[:5]):
            params_str = ", ".join(f"{k}={t[k]}" for k in sweep_params.keys())
            print(f"    {i+1}. {params_str} | CF={t.get('composite_fitness', -9999):.3f} "
                  f"Cal={t.get('calmar', 0):.3f} PF={t.get('profit_factor', 0):.3f} "
                  f"Trades={t.get('trade_count', 0):.0f}")
    return result


if __name__ == "__main__":
    print("=" * 60)
    print("STRATEGY OPTIMIZATION WITH SEED ARCHITECTURE GUIDELINES")
    print("=" * 60)

    bars, timestamps = load_data("TX", "2025-01-01", "2025-06-30")

    # --- PHASE 1: Baselines ---
    print("\n" + "=" * 40)
    print("PHASE 1: BASELINES")
    print("=" * 40)

    atr_mr_baseline = run_baseline("atr_mean_reversion", bars, timestamps)
    ema_tp_baseline = run_baseline("ema_trend_pullback", bars, timestamps)

    # --- PHASE 2: ATR Mean Reversion Entry Parameters ---
    print("\n" + "=" * 40)
    print("PHASE 2A: ATR MR - ENTRY PARAMS")
    print("=" * 40)

    atr_mr_sweep1 = run_sweep(
        "atr_mean_reversion",
        sweep_params={
            "kc_mult": [0.05, 0.08, 0.12, 0.18],
            "rsi_len": [3, 5, 7],
            "rsi_oversold": [20, 30, 40],
        },
        base_params={"vol_mult": 0.8, "trend_filter_atr": 3.0},
        bars=bars,
        timestamps=timestamps,
    )

    # Extract best entry params from sweep1
    best_entry_atr = atr_mr_sweep1.best_params if atr_mr_sweep1 else {}
    print(f"\nBest entry params: {best_entry_atr}")

    # --- PHASE 2B: ATR MR Stop/Exit Params ---
    print("\n" + "=" * 40)
    print("PHASE 2B: ATR MR - STOP/EXIT PARAMS")
    print("=" * 40)

    atr_mr_sweep2 = run_sweep(
        "atr_mean_reversion",
        sweep_params={
            "atr_sl_multi": [0.3, 0.5, 0.8, 1.0],
            "atr_tp_multi": [0.5, 0.8, 1.2, 1.5],
            "midline_exit": [0, 1],
        },
        base_params={
            "vol_mult": 0.8,
            "trend_filter_atr": 3.0,
            **best_entry_atr,
        },
        bars=bars,
        timestamps=timestamps,
    )

    # --- PHASE 3: EMA Trend Pullback Entry Parameters ---
    print("\n" + "=" * 40)
    print("PHASE 3A: EMA TP - ENTRY PARAMS")
    print("=" * 40)

    ema_tp_sweep1 = run_sweep(
        "ema_trend_pullback",
        sweep_params={
            "adx_min": [15.0, 20.0, 25.0],
            "min_pullback_pts": [3.0, 5.0, 8.0],
            "stoch_oversold": [15.0, 25.0, 35.0],
        },
        base_params={"bar_agg": 3, "allow_night": 1},
        bars=bars,
        timestamps=timestamps,
    )

    best_entry_ema = ema_tp_sweep1.best_params if ema_tp_sweep1 else {}
    print(f"\nBest entry params: {best_entry_ema}")

    # --- PHASE 3B: EMA TP Stop/Exit Params ---
    print("\n" + "=" * 40)
    print("PHASE 3B: EMA TP - STOP/EXIT PARAMS")
    print("=" * 40)

    ema_tp_sweep2 = run_sweep(
        "ema_trend_pullback",
        sweep_params={
            "atr_sl_mult": [1.0, 1.5, 2.0, 2.5],
            "atr_t1_mult": [1.5, 2.5, 3.5],
        },
        base_params={
            "bar_agg": 3,
            "allow_night": 1,
            **best_entry_ema,
        },
        bars=bars,
        timestamps=timestamps,
    )

    print("\n" + "=" * 60)
    print("OPTIMIZATION COMPLETE")
    print("=" * 60)
