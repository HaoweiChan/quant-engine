"""Direct-backtest playback engine.

Runs real backtests via ``run_backtest_realdata_for_mcp`` (the same
facade the MCP tools use) and caches the raw equity curves, trade
signals, and timestamps in memory. The war-room endpoint serves
playback ``as_of`` queries from this cache, guaranteeing bit-exact
equivalence with MCP results.

The mock-DB seeder path is bypassed entirely when this engine is active.
"""
from __future__ import annotations

import bisect
import logging
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger(__name__)

_TAIPEI_TZ = timezone(timedelta(hours=8))


@dataclass
class StrategySpec:
    slug: str
    symbol: str
    weight: float
    intraday: bool = False


@dataclass
class _CachedStrategy:
    spec: StrategySpec
    equity_curve: list[float] = field(default_factory=list)
    equity_timestamps: list[int] = field(default_factory=list)
    trade_signals: list[dict] = field(default_factory=list)
    initial_equity: float = 0.0
    raw_result: dict = field(default_factory=dict)


class PlaybackEngine:
    """In-memory cache of raw MCP facade results for playback."""

    def __init__(
        self,
        strategies: list[StrategySpec],
        initial_equity: float,
        start: str,
        end: str,
    ):
        self.strategies = strategies
        self.initial_equity = initial_equity
        self.start = start
        self.end = end
        self._cache: dict[str, _CachedStrategy] = {}
        self._ready = False

    @property
    def ready(self) -> bool:
        return self._ready

    def run_backtests(self) -> dict[str, Any]:
        """Run all strategy backtests via the MCP facade. Returns a summary."""
        from src.mcp_server.facade import run_backtest_realdata_for_mcp

        report: dict[str, Any] = {}
        for spec in self.strategies:
            try:
                result = run_backtest_realdata_for_mcp(
                    symbol=spec.symbol,
                    start=self.start,
                    end=self.end,
                    strategy=spec.slug,
                    initial_equity=self.initial_equity,
                    intraday=spec.intraday,
                )
            except Exception as exc:
                logger.exception("playback_engine.backtest_error slug=%s", spec.slug)
                report[spec.slug] = {"error": str(exc)}
                continue

            if not isinstance(result, dict) or result.get("error"):
                err = result.get("error") if isinstance(result, dict) else "non-dict"
                report[spec.slug] = {"error": str(err)}
                continue

            eq_curve = result.get("equity_curve", [])
            eq_ts = result.get("equity_timestamps", [])
            signals = result.get("trade_signals", [])

            # Ensure lists (numpy arrays → list)
            if hasattr(eq_curve, "tolist"):
                eq_curve = eq_curve.tolist()
            if hasattr(eq_ts, "tolist"):
                eq_ts = eq_ts.tolist()

            self._cache[spec.slug] = _CachedStrategy(
                spec=spec,
                equity_curve=eq_curve,
                equity_timestamps=eq_ts,
                trade_signals=signals,
                initial_equity=self.initial_equity,
                raw_result=result,
            )
            report[spec.slug] = {
                "bars": len(eq_curve),
                "trades": len(signals),
            }

        self._ready = True
        return report

    def time_range(self) -> tuple[int, int] | None:
        """Min/max epoch seconds across all cached strategies."""
        all_ts: list[int] = []
        for c in self._cache.values():
            if c.equity_timestamps:
                all_ts.append(c.equity_timestamps[0])
                all_ts.append(c.equity_timestamps[-1])
        if not all_ts:
            return None
        return min(all_ts), max(all_ts)

    @staticmethod
    def _interp_at(
        series: list[tuple[int, float]], target: int, initial: float,
    ) -> float:
        """Linearly interpolate equity at *target* from sorted (epoch, eq)."""
        if not series:
            return initial
        if target <= series[0][0]:
            return series[0][1]
        if target >= series[-1][0]:
            return series[-1][1]
        i = bisect.bisect_right([t for t, _ in series], target) - 1
        if i < 0:
            return initial
        t0, v0 = series[i]
        if i + 1 < len(series):
            t1, v1 = series[i + 1]
            if t1 != t0:
                frac = (target - t0) / (t1 - t0)
                return v0 + frac * (v1 - v0)
        return v0

    def get_account_state(self, as_of_epoch: int) -> dict:
        """Portfolio-level state at *as_of_epoch*.

        Returns a dict compatible with the mock-dev account block in the
        war-room response: equity, equity_curve, positions, recent_fills.
        """
        all_fills: list[dict] = []
        all_fill_dicts: list[dict] = []
        total_equity = 0.0

        # Collect per-strategy weighted series and initial equity
        per_strat: dict[str, list[tuple[int, float]]] = {}
        per_strat_init: dict[str, float] = {}
        for slug, cached in self._cache.items():
            w = cached.spec.weight
            eq = cached.equity_curve
            ts = cached.equity_timestamps
            if not eq or not ts:
                continue
            n = min(len(eq), len(ts))
            idx = min(bisect.bisect_right(ts, as_of_epoch) - 1, n - 1)
            if idx < 0:
                continue
            per_strat_init[slug] = w * eq[0]
            per_strat[slug] = [(ts[i], w * eq[i]) for i in range(idx + 1)]
            total_equity += w * eq[idx]

            for sig in cached.trade_signals:
                sig_epoch = _signal_epoch(sig)
                if sig_epoch is not None and sig_epoch <= as_of_epoch:
                    fill = _format_fill(sig, slug, cached.spec.symbol)
                    all_fills.append(fill)
                    all_fill_dicts.append({
                        "strategy_slug": slug,
                        "symbol": fill["symbol"],
                        "side": fill["side"],
                        "quantity": fill["quantity"],
                        "price": fill["price"],
                        "timestamp": fill["timestamp"],
                    })

        # Build equity curve on a unified hourly grid with forward-fill
        # interpolation so every point sums ALL strategies' equity.
        all_epochs = [ep for series in per_strat.values() for ep, _ in series]
        if all_epochs:
            grid_start = min(all_epochs)
            grid_end = max(all_epochs)
            step = 3600
            grid: list[int] = []
            t = grid_start
            while t <= grid_end + step:
                grid.append(t)
                t += step
            if grid and grid[-1] < grid_end:
                grid.append(grid_end)
            eq_curve_out = []
            for ep in grid:
                total = sum(
                    self._interp_at(per_strat[s], ep, per_strat_init.get(s, 0.0))
                    for s in per_strat
                )
                eq_curve_out.append(
                    {"timestamp": _epoch_to_taipei_iso(ep), "equity": total}
                )
        else:
            eq_curve_out = []

        # Reconstruct positions from fills via FIFO
        positions = _reconstruct_positions(all_fill_dicts)

        # Sort fills newest first
        all_fills.sort(key=lambda f: f["timestamp"], reverse=True)

        return {
            "equity": total_equity,
            "equity_curve": eq_curve_out,
            "positions": positions,
            "recent_fills": all_fills[:2000],
        }

    def get_strategy_state(self, slug: str, as_of_epoch: int) -> dict | None:
        """Per-strategy snapshot at *as_of_epoch*."""
        cached = self._cache.get(slug)
        if not cached or not cached.equity_curve:
            return None

        w = cached.spec.weight
        eq = cached.equity_curve
        ts = cached.equity_timestamps
        initial_slot = self.initial_equity * w

        idx = bisect.bisect_right(ts, as_of_epoch) - 1
        if idx < 0:
            return None
        idx = min(idx, len(eq) - 1)
        equity = w * eq[idx]
        realized = equity - initial_slot

        # Peak and drawdown
        peak = initial_slot
        for i in range(idx + 1):
            val = w * eq[i]
            if val > peak:
                peak = val
        dd_pct = (peak - equity) / peak * 100.0 if peak > 0 else 0.0

        # Trade count
        trade_count = 0
        for sig in cached.trade_signals:
            sig_epoch = _signal_epoch(sig)
            if sig_epoch is not None and sig_epoch <= as_of_epoch:
                trade_count += 1

        return {
            "equity": equity,
            "unrealized_pnl": 0.0,
            "realized_pnl": realized,
            "drawdown_pct": dd_pct,
            "peak_equity": peak,
            "trade_count": trade_count,
        }


def _signal_epoch(sig: dict) -> int | None:
    ts = sig.get("timestamp")
    if ts is None:
        return None
    if isinstance(ts, (int, float)):
        return int(ts)
    try:
        dt = datetime.fromisoformat(str(ts))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=_TAIPEI_TZ)
        return int(dt.timestamp())
    except (ValueError, TypeError):
        return None


def _epoch_to_taipei_iso(epoch: int) -> str:
    return datetime.fromtimestamp(epoch, tz=_TAIPEI_TZ).isoformat()


def _format_fill(sig: dict, slug: str, default_symbol: str) -> dict:
    side_raw = str(sig.get("side", "buy")).lower()
    return {
        "timestamp": str(sig.get("timestamp", "")),
        "symbol": sig.get("symbol", default_symbol),
        "side": "buy" if side_raw.startswith("b") else "sell",
        "price": float(sig.get("price", 0)),
        "quantity": int(sig.get("lots", 1)),
        "fee": 50.0,
        "strategy_slug": slug,
        "is_session_close": False,
        "signal_reason": str(sig.get("reason", "ENTRY")),
        "triggered": True,
        "spread_role": "single",
    }


def _reconstruct_positions(fills: list[dict]) -> list[dict]:
    """FIFO position reconstruction from flat fill list."""
    groups: dict[tuple, list] = {}
    for f in sorted(fills, key=lambda r: r["timestamp"]):
        key = (f["strategy_slug"], f["symbol"])
        groups.setdefault(key, []).append(f)

    positions = []
    for (slug, symbol), group_fills in groups.items():
        lots: deque[tuple[int, float]] = deque()
        net_qty = 0

        for fill in group_fills:
            side = fill["side"].upper()
            qty = int(fill["quantity"])
            price = float(fill["price"])
            delta = qty if side == "BUY" else -qty
            new_net = net_qty + delta

            if net_qty == 0:
                lots.append((abs(delta), price))
            elif (net_qty > 0 and delta > 0) or (net_qty < 0 and delta < 0):
                lots.append((abs(delta), price))
            else:
                remaining = abs(delta)
                while remaining > 0 and lots:
                    lot_qty, _ = lots[0]
                    if lot_qty <= remaining:
                        remaining -= lot_qty
                        lots.popleft()
                    else:
                        lots[0] = (lot_qty - remaining, lots[0][1])
                        remaining = 0
                if new_net != 0 and not lots:
                    lots.append((abs(new_net), price))

            net_qty = new_net

        if net_qty == 0 or not lots:
            continue

        total_qty = sum(q for q, _ in lots)
        avg_entry = sum(q * p for q, p in lots) / total_qty if total_qty else 0.0
        current_price = float(group_fills[-1]["price"])

        positions.append({
            "symbol": symbol,
            "side": "BUY" if net_qty > 0 else "SELL",
            "quantity": abs(net_qty),
            "avg_entry_price": avg_entry,
            "current_price": current_price,
            "unrealized_pnl": 0.0,
            "strategy_slug": slug,
        })

    return positions
