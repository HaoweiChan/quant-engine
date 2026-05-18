"""Playback verification — replay live runner code against historical bars.

Usage:
    .venv/bin/python scripts/verify_playback.py [target_date YYYY-MM-DD]

For each active live session, this script:
  1. Instantiates LiveStrategyRunner with the SAME SizingConfig the live
     pipeline uses (LivePipelineManager.DEFAULT_SIZING). [goal-1]
  2. Replays 1m bars from a configurable window so the runner accumulates
     state (positions, indicator history, daily_atr cache). [goal-2]
  3. Feeds each bar bar-for-bar through runner.on_bar_complete(), captures
     ExecutionResults. [goal-3]
  4. Optionally seeds prior positions from live_fills history to reduce
     cold-start divergence. [goal-2 extended]

Compares the playback's fills on the target date against the live_fills
table.

KNOWN LIMITS — exact alignment to live is bounded by:
  - Live runner restarts mid-day are not reproduced (state resets).
  - Live data-feed gaps (e.g. 2026-05-18 day session) are not visible in
    market.db, which fills the gap retroactively via gap_repair.
  - Live's _daily_atr_cache may accumulate stale values across restarts;
    the playback computes it fresh from market.db.
"""
from __future__ import annotations
import os
import sys
import sqlite3
import asyncio
import logging
from datetime import datetime, timedelta

os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ".")

# Silence noisy production logs so the summary table is readable.
logging.basicConfig(level=logging.CRITICAL)
import structlog
structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(logging.CRITICAL))

from src.broker_gateway.live_bar_store import MinuteBar
from src.execution.live_pipeline import LivePipelineManager
from src.execution.live_strategy_runner import LiveStrategyRunner


SIZING = LivePipelineManager.DEFAULT_SIZING


def discover_sessions() -> list[tuple[str, str, str, float, str]]:
    """Return (account_id, strategy, symbol, equity, live_session_id) for
    every active live session. Equity is the most-recent account_equity
    row; falls back to virtual_equity then 1M."""
    conn = sqlite3.connect("data/trading.db")
    out: list[tuple[str, str, str, float, str]] = []
    for row in conn.execute(
        "SELECT session_id, account_id, strategy_slug, symbol, equity_share, virtual_equity "
        "FROM sessions WHERE status = 'active' ORDER BY account_id, strategy_slug"
    ):
        sid, account_id, slug, symbol, share, vequity = row
        eq = vequity or (share or 1.0) * 1_000_000
        # Try to pull a more accurate per-account equity if available.
        try:
            cur = conn.execute(
                "SELECT equity FROM account_equity_history "
                "WHERE account_id=? ORDER BY timestamp DESC LIMIT 1",
                (account_id,),
            )
            row2 = cur.fetchone()
            if row2 and row2[0]:
                eq = float(row2[0]) * (share or 1.0)
        except Exception:
            pass
        out.append((account_id, slug, symbol, float(eq), sid))
    return out


def fetch_1m_bars(symbol: str, start: str, end: str) -> list[MinuteBar]:
    conn = sqlite3.connect("data/market.db")
    cur = conn.execute(
        "SELECT timestamp, open, high, low, close, volume FROM ohlcv_bars "
        "WHERE symbol = ? AND timestamp BETWEEN ? AND ? ORDER BY timestamp",
        (symbol, start, end),
    )
    out: list[MinuteBar] = []
    for ts, o, h, lo, c, v in cur.fetchall():
        try:
            t = datetime.fromisoformat(ts)
        except ValueError:
            t = datetime.strptime(ts[:19], "%Y-%m-%d %H:%M:%S")
        out.append(MinuteBar(timestamp=t, open=float(o), high=float(h),
                             low=float(lo), close=float(c), volume=float(v)))
    return out


def live_fills_on(account_id: str, strategy: str, symbol: str, date: str) -> list[tuple]:
    conn = sqlite3.connect("data/trading.db")
    cur = conn.execute(
        "SELECT timestamp, side, price, quantity, signal_reason FROM live_fills "
        "WHERE strategy_slug=? AND symbol=? AND account_id=? AND timestamp LIKE ? "
        "ORDER BY timestamp",
        (strategy, symbol, account_id, f"{date}%"),
    )
    return cur.fetchall()


async def replay(account_id: str, strategy: str, symbol: str, equity: float,
                 live_session_id: str, start: str, end: str, target_date: str
                 ) -> tuple[list[tuple], int]:
    runner = LiveStrategyRunner(
        session_id=live_session_id,          # use LIVE session_id so DB-backed
        account_id=account_id,               # state (entry guards) is shared
        strategy_slug=strategy,
        symbol=symbol,
        equity_budget=equity,
        sizing_config=SIZING,
        execution_mode="paper",
    )
    bars = fetch_1m_bars(symbol, start, end)
    target_fills: list[tuple] = []
    for bar in bars:
        try:
            results = await runner.on_bar_complete(symbol, bar)
        except Exception:
            continue
        if not results:
            continue
        for r in results:
            if getattr(r, "fill_price", None) is None:
                continue
            if bar.timestamp.date().isoformat() == target_date:
                target_fills.append((bar.timestamp, r))
    return target_fills, len(bars)


async def main(target_date: str, start: str, end: str) -> None:
    sessions = discover_sessions()
    print("=" * 110)
    print(f"PLAYBACK vs LIVE on {target_date}   window={start[:10]}..{end[:10]}")
    print(f"runner=LiveStrategyRunner  sizing={SIZING.__class__.__name__}(risk={SIZING.risk_per_trade}, "
          f"margin_cap={SIZING.margin_cap}, max_lots={SIZING.max_lots})")
    print("=" * 110)
    print(f"{'session':45} {'sym':4} {'equity':>12} {'bars':>7} {'bt':>5} {'live':>5}  verdict")
    print("-" * 110)
    rows: list[tuple] = []
    for account_id, strategy, symbol, equity, sid in sessions:
        short = f"{account_id}/{strategy.split('/')[-1]}"
        try:
            bt_fills, n_bars = await replay(account_id, strategy, symbol, equity, sid,
                                            start, end, target_date)
        except Exception as e:
            print(f"{short:45} {symbol:4} {equity:>12.0f} FAIL: {type(e).__name__}: {e}")
            continue
        live = live_fills_on(account_id, strategy, symbol, target_date)
        if len(bt_fills) == len(live):
            v = "MATCH"
        elif abs(len(bt_fills) - len(live)) <= 1:
            v = "OFF-BY-1"
        elif abs(len(bt_fills) - len(live)) <= 3:
            v = "CLOSE"
        else:
            v = f"DIVERGE ({len(bt_fills) - len(live):+d})"
        print(f"{short:45} {symbol:4} {equity:>12.0f} {n_bars:>7} {len(bt_fills):>5} {len(live):>5}  {v}")
        rows.append((short, symbol, bt_fills, live, v))

    print()
    for short, symbol, bt_fills, live, v in rows:
        if not bt_fills and not live:
            continue
        print(f"--- {short} {symbol} (BT={len(bt_fills)}, LIVE={len(live)}, {v}) ---")
        for ts, r in bt_fills[:10]:
            side = getattr(r.order, "side", "?"); reason = getattr(r.order, "reason", "?")
            print(f"   BT   {ts}  {side:4} qty={r.fill_qty:>5} @ {r.fill_price:>9.3f} {reason}")
        for ts_s, side, price, qty, reason in live[:10]:
            print(f"   LIVE {ts_s}  {side:4} qty={qty:>5} @ {price:>9.3f} {reason}")


def fetch_bars_from_journal(session_id: str, target_date: str) -> list[MinuteBar]:
    """Reconstruct the exact bar stream the live runner saw on target_date by
    grepping the journal for runner_bar_seen records. Returns bars in arrival
    order. Requires the runner-instrumentation log line in
    src/execution/live_strategy_runner.py:on_bar_complete."""
    import json as _json
    import subprocess
    cmd = [
        "journalctl", "--user", "-u", "quant-engine-api",
        f"--since={target_date} 00:00:00",
        f"--until={target_date} 23:59:59",
        "--no-pager", "--output=cat",
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    except Exception:
        return []
    bars: list[MinuteBar] = []
    for line in proc.stdout.splitlines():
        if "runner_bar_seen" not in line or session_id not in line:
            continue
        try:
            j = line[line.index("{"): line.rindex("}") + 1]
            d = _json.loads(j)
        except Exception:
            continue
        if d.get("event") != "runner_bar_seen" or d.get("session_id") != session_id:
            continue
        try:
            t = datetime.fromisoformat(d["bar_ts"])
        except Exception:
            continue
        bars.append(MinuteBar(timestamp=t, open=float(d["open"]),
                              high=float(d["high"]), low=float(d["low"]),
                              close=float(d["close"]), volume=float(d.get("volume", 0))))
    return bars


def fetch_state_from_journal(session_id: str, target_date: str, win_start: datetime) -> list[dict] | None:
    """Find the most recent runner_state_seen record at or before win_start
    for this session on target_date. Returns the positions list (with exact
    stop_level) or None if no state log was emitted (pre-instrumentation)."""
    import json as _json
    import subprocess
    cmd = [
        "journalctl", "--user", "-u", "quant-engine-api",
        f"--since={target_date} 00:00:00",
        f"--until={win_start.strftime('%Y-%m-%d %H:%M:%S')}",
        "--no-pager", "--output=cat",
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    except Exception:
        return None
    latest: list[dict] | None = None
    for line in proc.stdout.splitlines():
        if "runner_state_seen" not in line or session_id not in line:
            continue
        try:
            j = line[line.index("{"): line.rindex("}") + 1]
            d = _json.loads(j)
        except Exception:
            continue
        if d.get("event") != "runner_state_seen" or d.get("session_id") != session_id:
            continue
        latest = d.get("positions") or None
    return latest


def compute_position_at(session_id: str, win_start: datetime) -> tuple[float, float] | None:
    """Reconstruct LIVE's net position at win_start from live_fills history.
    Returns (signed_qty, vwap_entry_price) or None if flat."""
    conn = sqlite3.connect("data/trading.db")
    cur = conn.execute(
        "SELECT side, price, quantity FROM live_fills "
        "WHERE session_id = ? AND timestamp < ? ORDER BY timestamp",
        (session_id, win_start.strftime("%Y-%m-%d %H:%M:%S")),
    )
    net = 0.0
    long_cost = 0.0  # cumulative cost of currently-open long lots
    short_cost = 0.0
    for side, price, qty in cur.fetchall():
        s = 1.0 if side == "buy" else -1.0
        new_net = net + s * qty
        # Crossing zero closes the prior side and opens the new side
        if net == 0:
            if s > 0:
                long_cost = price * qty
            else:
                short_cost = price * qty
        elif (net > 0 and s > 0) or (net < 0 and s < 0):
            # Adding to existing side
            if s > 0:
                long_cost += price * qty
            else:
                short_cost += price * qty
        else:
            # Reducing
            if new_net == 0:
                long_cost = 0.0; short_cost = 0.0
            elif (net > 0 and new_net > 0) or (net < 0 and new_net < 0):
                # Proportional reduce
                if net > 0:
                    long_cost *= new_net / net
                else:
                    short_cost *= new_net / abs(net) if net != 0 else 1
            else:
                # Crossed zero AND flipped sides
                if new_net > 0:
                    long_cost = price * new_net
                    short_cost = 0.0
                else:
                    short_cost = price * abs(new_net)
                    long_cost = 0.0
        net = new_net
    if abs(net) < 1e-9:
        return None
    vwap = (long_cost if net > 0 else short_cost) / abs(net)
    return (net, vwap)


def seed_position(runner: LiveStrategyRunner, qty: float, vwap: float, snapshot_price: float) -> None:
    """Inject a Position into the runner's engine to match LIVE state at win_start.
    Uses a generous stop so the seeded position survives normal noise — actual
    stop will be recomputed by the strategy's update_stop on the next bar."""
    from src.core.types import Position
    direction = "long" if qty > 0 else "short"
    abs_qty = abs(qty)
    # Stop at 5% from VWAP — generous to avoid premature stop-out on the
    # first journal bar. The strategy's update_stop will tighten on
    # subsequent bars via the trail-ratchet logic.
    stop = vwap * 0.95 if direction == "long" else vwap * 1.05
    pos = Position(
        entry_price=vwap,
        lots=abs_qty,
        contract_type="large",
        stop_level=stop,
        pyramid_level=0,
        entry_timestamp=datetime.now(),
        direction=direction,
        position_id=f"seed-{runner.session_id[:8]}",
    )
    runner._engine._positions = [pos]


async def main_from_journal(target_date: str) -> None:
    """Exact-match mode: replay only the bars the LIVE runner actually saw
    (via the journal runner_bar_seen records). Given the same bar stream and
    the same runner code, the playback's fills must equal LIVE's fills.

    Comparison is restricted to LIVE fills that fall WITHIN the journal's
    recorded bar-timestamp range, so we don't penalise the playback for
    pre-instrumentation fills it has no bars for."""
    sessions = discover_sessions()
    print("=" * 116)
    print(f"PLAYBACK FROM-JOURNAL  date={target_date}   "
          f"(bars from runner_bar_seen records; comparison clamped to journal time range)")
    print("=" * 116)
    print(f"{'session':45} {'sym':4} {'bars':>5} {'window':>17} {'bt':>4} {'live_in_win':>11}  verdict")
    print("-" * 116)
    for account_id, strategy, symbol, equity, sid in sessions:
        short = f"{account_id}/{strategy.split('/')[-1]}"
        bars = fetch_bars_from_journal(sid, target_date)
        if not bars:
            print(f"{short:45} {symbol:4} {0:>5} (no journal records — needs runner instrumentation deployed)")
            continue
        win_start = bars[0].timestamp
        win_end = bars[-1].timestamp
        runner = LiveStrategyRunner(
            session_id=sid, account_id=account_id, strategy_slug=strategy,
            symbol=symbol, equity_budget=equity, sizing_config=SIZING,
            execution_mode="paper",
        )
        # Pre-warmup: hydrate indicator state from market.db bars before
        # the journal window so RSI/EMA/ATR/Donchian channels have history.
        warmup_start = (win_start - timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S")
        warmup_end = (win_start - timedelta(minutes=1)).strftime("%Y-%m-%d %H:%M:%S")
        warmup_bars = fetch_1m_bars(symbol, warmup_start, warmup_end)
        for bar in warmup_bars:
            try:
                await runner.on_bar_complete(symbol, bar)
            except Exception:
                continue
        # Flatten anything the warmup produced (it would otherwise contaminate
        # the journal-window comparison with BT-only positions).
        runner._engine._positions = []
        # Position seeding: prefer the runner_state_seen journal record
        # (exact stop_level + pyramid level). Fall back to fills-based
        # reconstruction (approximate stop_level) when no state record
        # exists for this session yet.
        from src.core.types import Position
        state_positions = fetch_state_from_journal(sid, target_date, win_start)
        if state_positions:
            seeded = []
            for p in state_positions:
                seeded.append(Position(
                    entry_price=float(p["entry_price"]),
                    lots=float(p["lots"]),
                    contract_type="large",
                    stop_level=float(p["stop_level"]),
                    pyramid_level=int(p.get("pyramid_level", 0)),
                    entry_timestamp=win_start,
                    direction=p["direction"],
                    position_id=f"seed-{sid[:8]}",
                ))
            runner._engine._positions = seeded
        else:
            pos_info = compute_position_at(sid, win_start)
            if pos_info is not None:
                net_qty, vwap = pos_info
                seed_position(runner, net_qty, vwap, bars[0].open)
        bt_fills: list[tuple] = []
        for bar in bars:
            try:
                results = await runner.on_bar_complete(symbol, bar)
            except Exception:
                continue
            for r in results or []:
                if getattr(r, "fill_price", None) is None:
                    continue
                bt_fills.append((bar.timestamp, r))
        # Clamp live fills to the journal time window so we compare like-with-like
        all_live = live_fills_on(account_id, strategy, symbol, target_date)
        live_in_win = []
        for ts_s, side, price, qty, reason in all_live:
            try:
                tt = datetime.fromisoformat(ts_s.replace(" ", "T"))
            except ValueError:
                tt = datetime.strptime(ts_s[:19], "%Y-%m-%d %H:%M:%S")
            if win_start <= tt <= win_end:
                live_in_win.append((ts_s, side, price, qty, reason))
        diff = len(bt_fills) - len(live_in_win)
        v = "MATCH" if diff == 0 else ("OFF-BY-1" if abs(diff) <= 1 else f"DIVERGE ({diff:+d})")
        win_str = f"{win_start.strftime('%H:%M')}-{win_end.strftime('%H:%M')}"
        print(f"{short:45} {symbol:4} {len(bars):>5} {win_str:>17} {len(bt_fills):>4} {len(live_in_win):>11}  {v}")


if __name__ == "__main__":
    if "--from-journal" in sys.argv:
        args = [a for a in sys.argv[1:] if a != "--from-journal"]
        target = args[0] if args else datetime.now().strftime("%Y-%m-%d")
        asyncio.run(main_from_journal(target))
    else:
        target = sys.argv[1] if len(sys.argv) > 1 else "2026-05-15"
        start = sys.argv[2] if len(sys.argv) > 2 else "2026-04-01 00:00:00"
        end = sys.argv[3] if len(sys.argv) > 3 else f"{target} 23:59:59"
        asyncio.run(main(target, start, end))
