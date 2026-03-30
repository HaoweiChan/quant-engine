"""Optimize atr_mean_reversion and ema_trend_pullback v3.

Fixes from v2:
- Sort uses (composite_fitness, profit_factor, pnl) for proper tiebreaking
- Optimize directly on H1 2025 data (no Q1-then-validate scheme)
- EMA Pullback: focused around the promising param ranges from v2
- ATR MR: try wider KC (0.3-0.5) + relaxed RSI + different stop ratios
"""
import os
import sys
import logging
import itertools

logging.disable(logging.CRITICAL)
os.environ["STRUCTLOG_LEVEL"] = "CRITICAL"

from pathlib import Path
from datetime import datetime
from statistics import mean as _mean

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import structlog
structlog.configure(
    wrapper_class=structlog.stdlib.BoundLogger,
    logger_factory=structlog.PrintLoggerFactory(file=open(os.devnull, 'w'))
)

from src.data.db import Database
from src.mcp_server.facade import resolve_factory
from src.simulator.fill_model import MarketImpactFillModel
from src.simulator.backtester import BacktestRunner
from src.adapters.taifex import TaifexAdapter
from src.core.types import ImpactParams

OUT_PATH = Path(__file__).resolve().parent.parent / "opt_results.txt"
OUT = open(str(OUT_PATH), "w")


def p(s=""):
    print(s, file=OUT, flush=True)


def load_data(symbol, start, end):
    db_path = Path(__file__).resolve().parent.parent / "data" / "taifex_data.db"
    db = Database(f"sqlite:///{db_path}")
    raw = db.get_ohlcv(symbol, datetime.fromisoformat(start), datetime.fromisoformat(end))
    daily_ranges = [b.high - b.low for b in raw]
    daily_atr = _mean(daily_ranges) if daily_ranges else 0.0
    bars = [
        {"symbol": symbol, "price": b.close, "open": b.open, "high": b.high,
         "low": b.low, "close": b.close, "volume": float(b.volume),
         "daily_atr": daily_atr, "timestamp": b.timestamp}
        for b in raw
    ]
    return bars, [b.timestamp for b in raw], daily_atr


def run_bt(strategy, params, bars, timestamps):
    factory = resolve_factory(strategy)
    fill_model = MarketImpactFillModel(params=ImpactParams(spread_bps=1.0, commission_bps=1.0))
    runner = BacktestRunner(
        config=lambda: factory(**params),
        adapter=TaifexAdapter(), fill_model=fill_model, initial_equity=2_000_000.0,
    )
    result = runner.run(bars, timestamps=timestamps)
    m = result.metrics
    pnl = result.equity_curve[-1] - result.equity_curve[0] if result.equity_curve else 0
    return m, pnl


def fmt(m, pnl):
    return (f"Trades={m.get('trade_count',0):.0f} WR={m.get('win_rate',0):.1%} "
            f"Sh={m.get('sharpe',0):.2f} Cal={m.get('calmar',0):.2f} "
            f"PF={m.get('profit_factor',0):.2f} CF={m.get('composite_fitness',-9999):.2f} "
            f"DD={m.get('max_drawdown_pct',0):.1%} PnL={pnl:,.0f}")


def sort_key(result):
    """Sort by (composite_fitness, profit_factor, pnl) for proper tiebreaking."""
    cf, params, m, pnl = result
    pf = m.get('profit_factor', 0)
    return (cf, pf, pnl)


def sweep(strategy, sweep_params, base_params, bars, timestamps):
    keys = list(sweep_params.keys())
    combos = list(itertools.product(*[sweep_params[k] for k in keys]))
    p(f"  Running {len(combos)} combinations...")
    results = []
    for i, combo in enumerate(combos):
        params = {**base_params, **dict(zip(keys, combo))}
        try:
            m, pnl = run_bt(strategy, params, bars, timestamps)
            cf = m.get('composite_fitness', -9999)
            results.append((cf, params, m, pnl))
        except Exception as e:
            p(f"  ERROR: {e}")
            results.append((-9999, params, {}, 0))
        if (i + 1) % 4 == 0:
            p(f"  ...{i+1}/{len(combos)} done")
    results.sort(key=sort_key, reverse=True)
    return results


def show_top(results, n=8, label_keys=None):
    p(f"Top {min(n, len(results))}:")
    for i, (cf, params, m, pnl) in enumerate(results[:n]):
        if label_keys:
            lbl = " ".join(f"{k}={params.get(k)}" for k in label_keys)
        else:
            lbl = str({k: v for k, v in params.items()})
        p(f"  {i+1}. {lbl} | {fmt(m, pnl)}")


if __name__ == "__main__":
    bars, ts, atr = load_data("TX", "2025-01-01", "2025-06-30")
    p(f"H1 2025 Data: {len(bars)} bars, daily_atr={atr:.1f}")

    # =====================================================
    # EMA TREND PULLBACK v3 (most promising — optimize first)
    # =====================================================
    p("\n" + "="*60)
    p("=== EMA TREND PULLBACK v3 (on full H1 2025) ===")
    p("="*60)

    # Baseline with best-so-far params from v2
    m, pnl = run_bt("ema_trend_pullback", {
        "bar_agg": 3, "allow_night": 1, "vol_mult": 0.8, "vwap_filter": 1,
        "adx_min": 25.0, "rsi_oversold": 45, "min_pullback_pts": 3.0,
        "atr_sl_mult": 2.0, "atr_t1_mult": 4.0,
        "max_hold_bars": 120, "ema_trail_buffer_pts": 2.0,
    }, bars, ts)
    p(f"V2 BEST params on H1: {fmt(m, pnl)}")

    # Phase 1: Entry sweep — focused ranges around proven values
    p("\nPhase 1: entry sweep (adx_min, rsi_oversold, ema_fast, ema_slow, vwap_filter)")
    r1 = sweep("ema_trend_pullback", {
        "adx_min": [20.0, 25.0, 30.0],
        "rsi_oversold": [35, 40, 45, 50],
        "ema_fast": [5, 8, 13],
        "vwap_filter": [0, 1],
    }, {
        "bar_agg": 3, "allow_night": 1, "vol_mult": 0.8,
        "min_pullback_pts": 3.0, "atr_sl_mult": 2.0, "atr_t1_mult": 4.0,
        "max_hold_bars": 120, "ema_trail_buffer_pts": 2.0,
    }, bars, ts)
    show_top(r1, 10, ["adx_min", "rsi_oversold", "ema_fast", "vwap_filter"])
    best1 = r1[0][1]

    # Phase 2: Stop/exit sweep
    p(f"\nPhase 2: stop sweep (best entry: adx={best1.get('adx_min')}, rsi_os={best1.get('rsi_oversold')}, ema_f={best1.get('ema_fast')}, vwap={best1.get('vwap_filter')})")
    r2 = sweep("ema_trend_pullback", {
        "atr_sl_mult": [1.5, 2.0, 2.5, 3.0],
        "atr_t1_mult": [3.0, 4.0, 5.0],
    }, {**best1}, bars, ts)
    show_top(r2, 8, ["atr_sl_mult", "atr_t1_mult"])
    best2 = r2[0][1]

    # Phase 3: Timing + bar_agg + trail
    p(f"\nPhase 3: timing (bar_agg, max_hold, trail)")
    r3 = sweep("ema_trend_pullback", {
        "bar_agg": [1, 3, 5],
        "max_hold_bars": [90, 120, 180],
        "ema_trail_buffer_pts": [2.0, 5.0],
    }, {**best2}, bars, ts)
    show_top(r3, 10, ["bar_agg", "max_hold_bars", "ema_trail_buffer_pts"])
    best_ema = r3[0][1]

    p(f"\n>>> BEST EMA PULLBACK: {fmt(r3[0][2], r3[0][3])}")
    p(f"    Params: {best_ema}")

    # =====================================================
    # ATR MEAN REVERSION v3 (wider KC, wider TP, try midline exit)
    # =====================================================
    p("\n" + "="*60)
    p("=== ATR MEAN REVERSION v3 (on full H1 2025) ===")
    p("="*60)

    # Baseline with improved defaults
    m, pnl = run_bt("atr_mean_reversion", {}, bars, ts)
    p(f"DEFAULTS (kc=0.25, sl=0.6, tp=1.5, adx=35, vwap=1, hold=120): {fmt(m, pnl)}")

    # Phase 1: Wide KC + ADX + VWAP + midline exit
    p("\nPhase 1: structure sweep (kc_mult, adx_threshold, vwap, midline_exit)")
    r4 = sweep("atr_mean_reversion", {
        "kc_mult": [0.25, 0.30, 0.35, 0.40],
        "adx_threshold": [25, 30, 35, 40],
        "vwap_filter": [0, 1],
        "midline_exit": [0, 1],
    }, {"rsi_len": 3, "vol_mult": 0.8, "max_hold_bars": 120}, bars, ts)
    show_top(r4, 10, ["kc_mult", "adx_threshold", "vwap_filter", "midline_exit"])
    best4 = r4[0][1]

    # Phase 2: Stop sweep with proper tiebreaking
    p(f"\nPhase 2: stop sweep (best: kc={best4.get('kc_mult')}, adx={best4.get('adx_threshold')}, vwap={best4.get('vwap_filter')}, mid={best4.get('midline_exit')})")
    r5 = sweep("atr_mean_reversion", {
        "atr_sl_multi": [0.6, 0.8, 1.0, 1.5],
        "atr_tp_multi": [1.5, 2.0, 2.5, 3.0],
    }, {**best4}, bars, ts)
    show_top(r5, 10, ["atr_sl_multi", "atr_tp_multi"])
    best5 = r5[0][1]

    # Phase 3: Timing + RSI
    p(f"\nPhase 3: RSI + timing")
    r6 = sweep("atr_mean_reversion", {
        "rsi_oversold": [20, 25, 30, 35, 40],
        "max_hold_bars": [60, 90, 120],
    }, {**best5}, bars, ts)
    show_top(r6, 10, ["rsi_oversold", "max_hold_bars"])
    best_mr = r6[0][1]

    p(f"\n>>> BEST ATR MR: {fmt(r6[0][2], r6[0][3])}")
    p(f"    Params: {best_mr}")

    p("\n=== DONE ===")
    OUT.close()
