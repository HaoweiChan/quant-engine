"""Comprehensive backtest report: terminal-friendly text output for agent analysis.

Usage:
    from src.simulator.report import print_backtest_report
    print_backtest_report(result, timestamps, bars=raw_bars_dicts, ...)

Produces a full-page report covering:
- Returns vs buy-and-hold
- Risk metrics (Sharpe, Sortino, Calmar, max-DD, recovery factor)
- Trade statistics (win rate, profit factor, payoff, EV, kelly, streaks)
- Monthly returns table
- Per-trade log
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta
from statistics import mean, stdev
from typing import Any

from src.simulator.types import BacktestResult, Fill


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _pnl_sequence(trade_log: list[Fill], point_value: float) -> list[float]:
    """Return realized PnL per round-trip (long-only aware for now)."""
    pnls: list[float] = []
    entries: dict[str, tuple[float, float]] = {}  # symbol → (price, lots)
    for f in trade_log:
        if f.side == "buy":
            entries[f.symbol] = (f.fill_price, f.lots)
        elif f.side == "sell" and f.symbol in entries:
            ep, lots = entries.pop(f.symbol)
            pnls.append((f.fill_price - ep) * lots * point_value)
        elif f.side == "sell":
            # Short side
            entries[f.symbol] = (f.fill_price, f.lots)
        elif f.side == "buy" and f.symbol in entries:
            ep, lots = entries.pop(f.symbol)
            pnls.append((ep - f.fill_price) * lots * point_value)
    return pnls


def _trade_pairs(trade_log: list[Fill]) -> list[tuple[Fill, Fill]]:
    """Return (entry_fill, exit_fill) pairs from the trade log."""
    pairs: list[tuple[Fill, Fill]] = []
    open_entries: dict[str, Fill] = {}
    for f in trade_log:
        if f.side in ("buy",):
            open_entries[f.symbol] = f
        elif f.side == "sell" and f.symbol in open_entries:
            pairs.append((open_entries.pop(f.symbol), f))
    return pairs


def _consecutive_streaks(wins: list[bool]) -> tuple[int, int]:
    """Return (max_consec_wins, max_consec_losses)."""
    max_w = max_l = cur_w = cur_l = 0
    for w in wins:
        if w:
            cur_w += 1
            cur_l = 0
        else:
            cur_l += 1
            cur_w = 0
        max_w = max(max_w, cur_w)
        max_l = max(max_l, cur_l)
    return max_w, max_l


def _annualize(total_return: float, n_days: int) -> float:
    if n_days <= 0:
        return 0.0
    return (1 + total_return) ** (365.0 / n_days) - 1


def _sharpe(returns: list[float], periods_per_year: float) -> float:
    if len(returns) < 2:
        return 0.0
    mu = mean(returns)
    sd = stdev(returns) if len(returns) > 1 else 0.0
    return (mu / sd * math.sqrt(periods_per_year)) if sd > 0 else 0.0


def _sortino(returns: list[float], periods_per_year: float) -> float:
    if len(returns) < 2:
        return 0.0
    mu = mean(returns)
    down = [r for r in returns if r < 0]
    sd_down = stdev(down) if len(down) > 1 else 0.0
    return (mu / sd_down * math.sqrt(periods_per_year)) if sd_down > 0 else 0.0


def _omega(returns: list[float], threshold: float = 0.0) -> float:
    """Omega ratio: probability-weighted gains vs losses relative to threshold."""
    gains = sum(max(r - threshold, 0) for r in returns)
    losses = sum(max(threshold - r, 0) for r in returns)
    return gains / losses if losses > 0 else float("inf")


def _monthly_table(
    equity_curve: list[float], timestamps: list[datetime]
) -> dict[str, float]:
    """Monthly return, keyed by 'YYYY-MM'."""
    monthly: dict[str, list[float]] = {}
    for i, ts in enumerate(timestamps):
        key = ts.strftime("%Y-%m")
        monthly.setdefault(key, []).append(equity_curve[i + 1])  # equity after bar i
    result: dict[str, float] = {}
    prev = equity_curve[0]
    for key in sorted(monthly):
        last_eq = monthly[key][-1]
        result[key] = (last_eq - prev) / prev if prev > 0 else 0.0
        prev = last_eq
    return result


# ---------------------------------------------------------------------------
# Main report
# ---------------------------------------------------------------------------

def print_backtest_report(
    result: BacktestResult,
    timestamps: list[datetime],
    *,
    initial_equity: float = 2_000_000.0,
    point_value: float = 200.0,
    symbol: str = "TX",
    strategy_name: str = "Strategy",
    bars: list[dict[str, Any]] | None = None,
    bars_per_year: float = 252.0 * 390,  # 1-min: 252 trading days × 390 min/day
) -> None:
    """Print a comprehensive backtest report to stdout."""
    ec = result.equity_curve
    tlog = result.trade_log
    n_bars = len(timestamps)
    start_ts = timestamps[0] if timestamps else datetime(2024, 1, 1)
    end_ts = timestamps[-1] if timestamps else datetime(2024, 1, 1)
    n_days = max((end_ts - start_ts).days, 1)

    # --- Returns ---
    final_equity = ec[-1]
    net_pnl = final_equity - initial_equity
    total_ret = net_pnl / initial_equity
    cagr = _annualize(total_ret, n_days)

    # Buy-and-hold (using close prices from bars if provided)
    bah_ret: float | None = None
    if bars:
        first_price = float(bars[0].get("close", bars[0].get("price", 0)))
        last_price  = float(bars[-1].get("close", bars[-1].get("price", 0)))
        if first_price > 0:
            bah_ret = (last_price - first_price) / first_price
            bah_equity = initial_equity * (1 + bah_ret)

    # --- Risk ---
    bar_returns = [
        (ec[i + 1] - ec[i]) / ec[i] for i in range(len(ec) - 1) if ec[i] > 0
    ]
    sharpe = _sharpe(bar_returns, bars_per_year)
    sortino = _sortino(bar_returns, bars_per_year)
    omega = _omega(bar_returns)

    mdd_abs = result.metrics.get("max_drawdown_abs", 0.0)
    mdd_pct = result.metrics.get("max_drawdown_pct", 0.0)
    recovery = (net_pnl / mdd_abs) if mdd_abs > 0 else float("inf")
    calmar = (cagr / mdd_pct) if mdd_pct > 0 else float("inf")

    # --- Trade stats ---
    pnls = _pnl_sequence(tlog, point_value)
    pairs = _trade_pairs(tlog)
    n_trades = len(pnls)

    if n_trades > 0:
        wins_pnl  = [p for p in pnls if p > 0]
        losses_pnl = [p for p in pnls if p <= 0]
        win_rate  = len(wins_pnl) / n_trades
        avg_win   = mean(wins_pnl)   if wins_pnl   else 0.0
        avg_loss  = mean(losses_pnl) if losses_pnl else 0.0
        pf = abs(sum(wins_pnl) / sum(losses_pnl)) if losses_pnl else float("inf")
        payoff = abs(avg_win / avg_loss) if avg_loss else float("inf")
        ev = mean(pnls)
        # Kelly fraction
        p = win_rate
        b = payoff
        kelly = p - (1 - p) / b if b > 0 else 0.0
        best  = max(pnls)
        worst = min(pnls)
        win_flags = [p > 0 for p in pnls]
        max_cw, max_cl = _consecutive_streaks(win_flags)
        hold_mins = [
            (ex.timestamp - en.timestamp).total_seconds() / 60
            for en, ex in pairs
        ]
        avg_hold = mean(hold_mins) if hold_mins else 0.0
    else:
        win_rate = avg_win = avg_loss = pf = payoff = ev = kelly = 0.0
        best = worst = avg_hold = 0.0
        max_cw = max_cl = 0

    # --- Monthly returns ---
    monthly = _monthly_table(ec, timestamps)

    # --- Header ---
    W = 65
    bar = "=" * W
    sep = "-" * W
    print(bar)
    print(f"  {strategy_name}  |  {symbol} 1-min")
    print(f"  {start_ts.strftime('%Y-%m-%d %H:%M')} → {end_ts.strftime('%Y-%m-%d %H:%M')}  ({n_days}d, {n_bars:,} bars)")
    print(bar)

    # --- Returns block ---
    print(f"  {'RETURNS'}")
    print(sep)
    print(f"  Initial equity:       {initial_equity:>15,.0f} NTD")
    print(f"  Final equity:         {final_equity:>15,.0f} NTD")
    print(f"  Net PnL:              {net_pnl:>+15,.0f} NTD")
    print(f"  Total return:         {total_ret:>+14.2%}")
    print(f"  CAGR (annualized):    {cagr:>+14.2%}")
    if bah_ret is not None:
        alpha = total_ret - bah_ret
        print(f"  Buy-and-hold return:  {bah_ret:>+14.2%}  ({symbol}: {first_price:.0f} → {last_price:.0f})")
        print(f"  Alpha vs B&H:         {alpha:>+14.2%}")

    # --- Risk block ---
    print(f"\n  {'RISK METRICS'}")
    print(sep)
    print(f"  Max drawdown (abs):   {-mdd_abs:>+15,.0f} NTD")
    print(f"  Max drawdown (%):     {-mdd_pct:>+14.2%}")
    print(f"  Recovery factor:      {recovery:>15.2f}")
    print(f"  Sharpe ratio:         {sharpe:>15.4f}  (annualized, {bars_per_year:.0f} bars/yr)")
    print(f"  Sortino ratio:        {sortino:>15.4f}")
    print(f"  Calmar ratio:         {calmar:>15.4f}")
    print(f"  Omega ratio:          {omega:>15.4f}")

    # --- Trade stats ---
    print(f"\n  {'TRADE STATISTICS'}")
    print(sep)
    print(f"  Total trades:         {n_trades:>15}")
    print(f"  Win / Loss:           {len(wins_pnl) if n_trades else 0:>6} / {len(losses_pnl) if n_trades else 0:<6}  ({win_rate:.1%})")
    print(f"  Profit factor:        {pf:>15.3f}")
    print(f"  Payoff ratio:         {payoff:>15.3f}  (avg_win / avg_loss)")
    print(f"  Expected value:       {ev:>+15,.0f} NTD/trade")
    print(f"  Kelly fraction:       {kelly:>15.2%}")
    print(f"  Avg hold time:        {avg_hold:>14.1f} min")
    print(f"  Best trade:           {best:>+15,.0f} NTD")
    print(f"  Worst trade:          {worst:>+15,.0f} NTD")
    print(f"  Avg win:              {avg_win:>+15,.0f} NTD")
    print(f"  Avg loss:             {avg_loss:>+15,.0f} NTD")
    print(f"  Max consec. wins:     {max_cw:>15}")
    print(f"  Max consec. losses:   {max_cl:>15}")

    # --- Monthly returns ---
    if monthly:
        print(f"\n  {'MONTHLY RETURNS'}")
        print(sep)
        cols = sorted(monthly)
        for i in range(0, len(cols), 6):
            row_keys = cols[i:i + 6]
            header = "  " + "".join(f"{k:>12}" for k in row_keys)
            values = "  " + "".join(
                f"{monthly[k]:>+11.2%}" + " " for k in row_keys
            )
            print(header)
            print(values)

    # --- Trade log ---
    if pairs:
        print(f"\n  {'TRADE LOG'}")
        print(sep)
        hdr = f"  {'#':>3}  {'Entry':>20}  {'Exit':>20}  {'Entry Px':>9}  {'Exit Px':>8}  {'PnL':>10}  Reason"
        print(hdr)
        print("  " + sep)
        for idx, ((en, ex), pnl) in enumerate(zip(pairs, pnls), 1):
            flag = "W" if pnl > 0 else "L"
            pnl_str = f"{pnl:>+10,.0f}"
            print(
                f"  {idx:>3}  {str(en.timestamp)[:19]:>20}  "
                f"{str(ex.timestamp)[:19]:>20}  "
                f"{en.fill_price:>9.0f}  {ex.fill_price:>8.0f}  "
                f"{pnl_str}  [{flag}] {ex.reason}"
            )

    print(bar)
