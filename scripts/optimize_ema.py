"""Quick targeted lot tests."""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.mcp_server.facade import run_backtest_realdata_for_mcp

STRAT = "src.strategies.intraday.trend_following.ema_trend_pullback:create_ema_trend_pullback_engine"
FULL_START, FULL_END = "2024-03-25", "2026-03-14"


def run_one(start, end, params):
    t0 = time.time()
    r = run_backtest_realdata_for_mcp(
        symbol="TX", start=start, end=end,
        strategy=STRAT, strategy_params=params,
    )
    dt = time.time() - t0
    if "error" in r:
        print(f"    ERROR: {r['error'][:120]}", flush=True)
        return None, dt
    m = r["metrics"]
    bnh_pnl = 0
    ratio = 0
    if "bnh_equity" in r and r["bnh_equity"]:
        bnh_pnl = r["bnh_equity"][-1] - r["bnh_equity"][0]
        ratio = r["total_pnl"] / bnh_pnl if bnh_pnl != 0 else 0
    return {
        "sharpe": m["sharpe"], "trades": int(m["trade_count"]),
        "pnl": r["total_pnl"], "wr": m["win_rate"],
        "dd": m["max_drawdown_pct"], "bnh_pnl": bnh_pnl,
        "ratio": ratio, "pf": m["profit_factor"],
    }, dt


BASE = {
    "bar_agg": 5, "allow_night": 0, "ema_align": 1,
    "ema_fast": 13, "ema_slow": 34, "ema_trend": 144,
    "adx_min": 30, "min_pullback_pts": 15,
    "stoch_oversold": 15, "stoch_overbought": 85,
    "ema_trail_buffer_pts": 5.0,
}

if __name__ == "__main__":
    for lots, ml in [(6, 1200000), (7, 1500000), (8, 1800000), (10, 2500000)]:
        params = dict(BASE)
        params["lots"] = lots
        params["max_loss"] = ml
        print(f"lots={lots} max_loss={ml}: ", end="", flush=True)
        res, dt = run_one(FULL_START, FULL_END, params)
        if res:
            print(f"sharpe={res['sharpe']:+.3f} pnl={res['pnl']:+.0f} ratio={res['ratio']:.2f}x "
                  f"dd={res['dd']*100:.1f}% trades={res['trades']} ({dt:.0f}s)", flush=True)
        else:
            print(f"FAILED ({dt:.0f}s)", flush=True)
