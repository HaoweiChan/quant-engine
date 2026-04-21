"""War Room data endpoint."""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

_TAIPEI_TZ = timezone(timedelta(hours=8))

from collections import deque

from fastapi import APIRouter, Query
from pydantic import BaseModel

from src.api.helpers import get_live_pipeline, get_war_room_data
from src.api.routes.playback_engine import PlaybackEngine, StrategySpec
from src.trading_session.store import FillStore

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["trading"])


# Cache disabled. The previous 30-second TTL cache served stale equity into
# fresh playback sessions and survived seeder refactors that change the
# meaning of persisted snapshots, both producing values that disagreed with
# the MCP reference. SQLite reads on the mock tables are sub-millisecond, so
# the dashboard's 5s poll cadence does not need a cache. The
# `invalidate_warroom_cache` hook is retained as a no-op so the admin reseed
# endpoint and other callers continue to compile.
_MOCK_ACCOUNT_ID = "mock-dev"


def invalidate_warroom_cache() -> None:
    """No-op placeholder kept for API compatibility (cache was removed)."""
    return None


# ---------------------------------------------------------------------------
# Direct-backtest playback engine (bypasses mock DB)
# ---------------------------------------------------------------------------
_playback_engine: PlaybackEngine | None = None


class _PlaybackStrategyBody(BaseModel):
    slug: str
    symbol: str
    weight: float
    intraday: bool = False


class _PlaybackInitBody(BaseModel):
    strategies: list[_PlaybackStrategyBody]
    start: str
    end: str
    initial_equity: float = 2_000_000.0


@router.post("/war-room/playback/init")
async def init_playback(body: _PlaybackInitBody) -> dict:
    """Run backtests via the MCP facade and cache results for playback.

    Uses the exact same ``run_backtest_realdata_for_mcp`` function the
    MCP tools call, so equity values are guaranteed identical.
    """
    global _playback_engine
    specs = [
        StrategySpec(
            slug=s.slug,
            symbol=s.symbol,
            weight=s.weight,
            intraday=s.intraday,
        )
        for s in body.strategies
    ]
    engine = PlaybackEngine(
        strategies=specs,
        initial_equity=body.initial_equity,
        start=body.start,
        end=body.end,
    )
    report = engine.run_backtests()
    _playback_engine = engine
    tr = engine.time_range()
    logger.info(
        "playback.init strategies=%d range=%s report=%s",
        len(specs),
        tr,
        report,
    )
    return {
        "status": "ok",
        "report": report,
        "time_range": {
            "min_epoch": tr[0] if tr else None,
            "max_epoch": tr[1] if tr else None,
            "min_ts": _epoch_to_iso(tr[0]) if tr else None,
            "max_ts": _epoch_to_iso(tr[1]) if tr else None,
        },
    }


@router.delete("/war-room/playback")
async def stop_playback() -> dict:
    """Clear the in-memory playback cache."""
    global _playback_engine
    _playback_engine = None
    logger.info("playback.stopped")
    return {"status": "ok"}


@router.get("/war-room/playback/status")
async def playback_status() -> dict:
    """Check whether the direct-backtest playback engine is active."""
    if _playback_engine is None or not _playback_engine.ready:
        return {"active": False}
    tr = _playback_engine.time_range()
    return {
        "active": True,
        "strategies": [s.slug for s in _playback_engine.strategies],
        "time_range": {
            "min_ts": _epoch_to_iso(tr[0]) if tr else None,
            "max_ts": _epoch_to_iso(tr[1]) if tr else None,
        },
    }


def _epoch_to_iso(epoch: int | None) -> str | None:
    if epoch is None:
        return None
    return datetime.fromtimestamp(epoch, tz=_TAIPEI_TZ).isoformat()


def _mock_db_path() -> Path:
    return Path(__file__).resolve().parent.parent.parent.parent / "data" / "trading.db"


def _strategy_label(slug: str) -> str:
    return slug.split("/")[-1] if "/" in slug else slug


# Cache of slug → spread_legs metadata so each war-room request avoids
# re-importing the strategy module to look up STRATEGY_META.
_SPREAD_LEGS_CACHE: dict[str, list[str] | None] = {}


def _spread_legs_for_slug(slug: str) -> list[str] | None:
    """Return the 2-element spread_legs list for a spread strategy slug, or
    None for single-leg strategies. Result is memoised in-process.
    """
    if slug in _SPREAD_LEGS_CACHE:
        return _SPREAD_LEGS_CACHE[slug]
    legs: list[str] | None = None
    try:
        from src.strategies.registry import get_info

        info = get_info(slug)
        meta_legs = (info.meta or {}).get("spread_legs") if info else None
        if isinstance(meta_legs, (list, tuple)) and len(meta_legs) == 2:
            legs = [str(meta_legs[0]), str(meta_legs[1])]
    except Exception:
        legs = None
    _SPREAD_LEGS_CACHE[slug] = legs
    return legs


def _spread_role_for_fill(slug: str, symbol: str) -> str:
    """Tag a fill as 'r1', 'r2', or 'single' for per-panel signal filtering.

    Spread strategies in the seeder use account-relative legs (e.g. MTX/MTX_R2)
    rather than the strategy's META default (TX/TX_R2). To match both, we
    accept the fill's symbol when it equals either the META leg or shares the
    suffix convention (`{leg}_R2` for the second leg, anything else for the
    first). Returns 'single' when the strategy has no spread metadata.
    """
    legs = _spread_legs_for_slug(slug)
    if not legs:
        return "single"
    # Direct META match first.
    if symbol == legs[0]:
        return "r1"
    if symbol == legs[1]:
        return "r2"
    # Account-override fallback: leg2 is conventionally "{symbol}_R2".
    if symbol.endswith("_R2"):
        return "r2"
    return "r1"


def _get_mock_db_connection() -> sqlite3.Connection:
    """Open and return a SQLite connection to the mock trading DB."""
    db_path = _mock_db_path()
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def _reconstruct_positions_from_fills(fill_rows: list, as_of: str) -> list[dict]:
    """Reconstruct open positions at `as_of` via FIFO matching of fills.

    Fill rows must be provided in chronological order (oldest first).
    Each row must have: strategy_slug, symbol, side, quantity, price, timestamp.
    """
    from datetime import datetime as _dt

    # Group fills by (strategy_slug, symbol), sorted chronologically.
    groups: dict[tuple, list] = {}
    for row in sorted(fill_rows, key=lambda r: r["timestamp"]):
        key = (row["strategy_slug"], row["symbol"])
        groups.setdefault(key, []).append(row)

    positions = []
    for (slug, symbol), fills in groups.items():
        # Maintain a deque of open lots: each entry is (qty, price).
        lots: deque[tuple[int, float]] = deque()
        net_qty = 0  # positive = long, negative = short

        for fill in fills:
            side = fill["side"].upper()
            qty = int(fill["quantity"])
            price = float(fill["price"])

            # Determine signed delta.
            delta = qty if side == "BUY" else -qty
            new_net = net_qty + delta

            if net_qty == 0:
                # Opening a fresh position.
                lots.append((qty if delta > 0 else -delta, price))
            elif (net_qty > 0 and delta > 0) or (net_qty < 0 and delta < 0):
                # Adding to existing position.
                lots.append((abs(delta), price))
            else:
                # Reducing or flipping.
                remaining_close = abs(delta)
                while remaining_close > 0 and lots:
                    lot_qty, lot_price = lots[0]
                    if lot_qty <= remaining_close:
                        remaining_close -= lot_qty
                        lots.popleft()
                    else:
                        lots[0] = (lot_qty - remaining_close, lot_price)
                        remaining_close = 0
                # If we flipped through zero, open the new side.
                if new_net != 0 and not lots:
                    lots.append((abs(new_net), price))

            net_qty = new_net

        if net_qty == 0 or not lots:
            continue

        # Compute VWAP of remaining lots.
        total_qty = sum(q for q, _ in lots)
        avg_entry = sum(q * p for q, p in lots) / total_qty if total_qty else 0.0
        # Use the price of the most recent fill as current_price proxy.
        current_price = float(fills[-1]["price"])

        positions.append(
            {
                "symbol": symbol,
                "side": "BUY" if net_qty > 0 else "SELL",
                "quantity": abs(net_qty),
                "avg_entry_price": avg_entry,
                "current_price": current_price,
                "unrealized_pnl": 0.0,  # Cannot compute without live price
                "strategy_slug": slug,
            }
        )

    return positions


def _load_mock_current(account_id: str) -> dict | None:
    """Cache-friendly path: return the full mock war-room state with hourly resampling."""
    return _load_mock_warroom_state(account_id)


def _normalize_as_of_to_taipei(as_of: str) -> str:
    """Convert an as_of timestamp (possibly UTC) to Taipei local ISO format.

    DB timestamps are stored as Taipei local ISO (e.g. '2026-04-01T19:00:59+08:00').
    The frontend sends UTC ISO strings (e.g. '2026-04-01T11:00:59.000Z').
    SQLite does string comparison, so we must match the DB format.
    """
    from datetime import datetime as _dt
    raw = as_of.strip()
    try:
        dt = _dt.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return raw
    taipei_dt = dt.astimezone(_TAIPEI_TZ)
    return taipei_dt.isoformat()


def _load_mock_as_of(account_id: str, as_of: str) -> dict:
    """Return mock war-room state filtered to `as_of` timestamp.

    Bypasses the cache (both read and write).  Returns raw snapshot points
    without hourly grid resampling.  Positions are reconstructed from fills
    via FIFO matching.  Never reads the mock_positions table.
    """
    from datetime import datetime as _dt

    as_of = _normalize_as_of_to_taipei(as_of)
    db_path = _mock_db_path()
    if not db_path.exists():
        return {
            "equity_curve": [],
            "positions": [],
            "recent_fills": [],
            "trade_counts_by_session": {},
            "equity": 0.0,
            "per_strategy_latest": {},
        }

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        session_like = f"mock::{account_id}::%"

        snapshot_rows = conn.execute(
            """
            SELECT session_id, strategy_slug, timestamp, equity, unrealized_pnl,
                   realized_pnl, drawdown_pct, peak_equity, trade_count
            FROM mock_session_snapshots
            WHERE timestamp <= ? AND session_id LIKE ?
            ORDER BY timestamp ASC
            """,
            (as_of, session_like),
        ).fetchall()

        # All fills up to as_of (needed for position reconstruction and recent_fills).
        all_fill_rows = conn.execute(
            """
            SELECT timestamp, account_id, session_id, strategy_slug, symbol,
                   side, price, quantity, fee, pnl_realized, is_session_close,
                   signal_reason, triggered
            FROM mock_fills
            WHERE account_id = ? AND timestamp <= ?
            ORDER BY timestamp ASC
            """,
            (account_id, as_of),
        ).fetchall()

        trade_counts_by_session = {
            row[0]: int(row[1])
            for row in conn.execute(
                """
                SELECT session_id, COUNT(1) FROM mock_fills
                WHERE account_id = ? AND timestamp <= ?
                GROUP BY session_id
                """,
                (account_id, as_of),
            ).fetchall()
        }
    finally:
        conn.close()

    if not snapshot_rows:
        return {
            "equity_curve": [],
            "positions": [],
            "recent_fills": [],
            "trade_counts_by_session": {},
            "equity": 0.0,
            "per_strategy_latest": {},
        }

    # Build equity curve with forward-fill: carry each strategy's last known
    # equity so sums are always across ALL strategies, not just those with
    # a snapshot at that exact timestamp.
    per_strategy_latest: dict[str, dict] = {}
    strategy_latest_equity: dict[str, float] = {}
    all_timestamps: set[str] = set()
    for row in snapshot_rows:
        ts = row["timestamp"]
        slug = row["strategy_slug"]
        all_timestamps.add(ts)
        strategy_latest_equity[slug] = float(row["equity"])
        per_strategy_latest[slug] = {
            "equity": float(row["equity"]),
            "unrealized_pnl": float(row["unrealized_pnl"]),
            "realized_pnl": float(row["realized_pnl"]),
            "drawdown_pct": float(row["drawdown_pct"]),
            "peak_equity": float(row["peak_equity"]),
            "trade_count": int(row["trade_count"]),
            "timestamp": row["timestamp"],
            "session_id": row["session_id"],
        }
    # Forward-fill equity per strategy across all timestamps
    ts_equity: dict[str, float] = {}
    strat_eq: dict[str, float] = {}
    rows_by_ts: dict[str, dict[str, float]] = {}
    for row in snapshot_rows:
        ts = row["timestamp"]
        rows_by_ts.setdefault(ts, {})[row["strategy_slug"]] = float(row["equity"])
    for ts in sorted(all_timestamps):
        for slug, eq in rows_by_ts.get(ts, {}).items():
            strat_eq[slug] = eq
        ts_equity[ts] = sum(strat_eq.values())
    equity_curve = sorted(ts_equity.items())

    # Recent fills: take the most-recent slice per strategy, then combine.
    # Using a global "last 200" cap starved bursty strategies (e.g.
    # spread_reversion, which stops trading mid-year) of representation in
    # the blotter and chart markers once other strategies crowded the tail.
    # 500 per strategy × 4 strategies ≈ a bounded payload that still shows
    # every strategy's signal history.
    fills_by_slug: dict[str, list] = {}
    for row in all_fill_rows:
        fills_by_slug.setdefault(row["strategy_slug"], []).append(row)
    per_strategy_cap = 500
    picked: list = []
    for slug_fills in fills_by_slug.values():
        picked.extend(slug_fills[-per_strategy_cap:])
    picked.sort(key=lambda r: r["timestamp"], reverse=True)
    recent_fills = [
        {
            "timestamp": r["timestamp"],
            "symbol": r["symbol"],
            "side": r["side"],
            "price": float(r["price"]),
            "quantity": int(r["quantity"]),
            "fee": float(r["fee"]),
            "strategy_slug": r["strategy_slug"],
            "is_session_close": bool(r["is_session_close"]),
            "signal_reason": r["signal_reason"] or "",
            "triggered": bool(r["triggered"]),
            # Per-panel filter key for spread chart rendering. "r1" / "r2" for
            # the two legs of a spread strategy, "single" for non-spread.
            "spread_role": _spread_role_for_fill(r["strategy_slug"], r["symbol"]),
        }
        for r in picked
    ]

    positions = _reconstruct_positions_from_fills(list(all_fill_rows), as_of)
    latest_equity = equity_curve[-1][1] if equity_curve else 0.0

    return {
        "equity": latest_equity,
        "equity_curve": equity_curve,
        "positions": positions,
        "recent_fills": recent_fills,
        "trade_counts_by_session": trade_counts_by_session,
        "per_strategy_latest": per_strategy_latest,
    }


def _load_mock_warroom_state(account_id: str) -> dict | None:
    """Return a dict of {positions, fills, equity_curve, per_strategy_snapshots}
    aggregated across all seeded strategies for the account, or None if empty.
    """
    db_path = _mock_db_path()
    if not db_path.exists():
        return None
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        # Are the mock tables present?
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'mock_%'"
            ).fetchall()
        }
        if not {"mock_session_snapshots", "mock_fills", "mock_positions"}.issubset(tables):
            return None

        snapshot_rows = conn.execute(
            """
            SELECT session_id, strategy_slug, timestamp, equity, unrealized_pnl,
                   realized_pnl, drawdown_pct, peak_equity, trade_count
            FROM mock_session_snapshots
            WHERE session_id LIKE ?
            ORDER BY timestamp ASC
            """,
            (f"mock::{account_id}::%",),
        ).fetchall()
        if not snapshot_rows:
            return None

        fill_rows = conn.execute(
            """
            SELECT timestamp, account_id, session_id, strategy_slug, symbol,
                   side, price, quantity, fee, pnl_realized, is_session_close,
                   signal_reason, triggered, rn
            FROM (
                SELECT *, ROW_NUMBER() OVER (
                    PARTITION BY strategy_slug ORDER BY timestamp DESC
                ) AS rn
                FROM mock_fills
                WHERE account_id = ?
            )
            WHERE rn <= 500
            ORDER BY timestamp DESC
            """,
            (account_id,),
        ).fetchall()

        position_rows = conn.execute(
            """
            SELECT account_id, session_id, strategy_slug, symbol, side, quantity,
                   avg_entry_price, current_price, unrealized_pnl, opened_at
            FROM mock_positions
            WHERE account_id = ?
            """,
            (account_id,),
        ).fetchall()

        trade_counts_by_session = {
            row[0]: int(row[1])
            for row in conn.execute(
                """
                SELECT session_id, COUNT(1) FROM mock_fills
                WHERE account_id = ?
                GROUP BY session_id
                """,
                (account_id,),
            ).fetchall()
        }
    finally:
        conn.close()

    # Aggregate per-strategy equity curves → account-level curve via linear
    # interpolation onto a common hourly grid, then summing across strategies.
    per_strategy: dict[str, list[tuple[str, float]]] = {}
    per_strategy_initial: dict[str, float] = {}
    latest_per_strategy: dict[str, dict] = {}
    for row in snapshot_rows:
        slug = row["strategy_slug"]
        per_strategy.setdefault(slug, []).append((row["timestamp"], float(row["equity"])))
        latest_per_strategy[slug] = {
            "equity": float(row["equity"]),
            "unrealized_pnl": float(row["unrealized_pnl"]),
            "realized_pnl": float(row["realized_pnl"]),
            "drawdown_pct": float(row["drawdown_pct"]),
            "peak_equity": float(row["peak_equity"]),
            "trade_count": int(row["trade_count"]),
            "timestamp": row["timestamp"],
            "session_id": row["session_id"],
        }

    # Use first snapshot per strategy as its initial equity seed.
    for slug, series in per_strategy.items():
        if series:
            per_strategy_initial[slug] = series[0][1]

    # Resample all strategy curves onto a common hourly grid, then sum.
    # This avoids step-function jumps caused by forward-filling strategies
    # with sparse or misaligned timestamps onto the union timeline.
    from datetime import datetime as _dt

    def _iso_to_epoch(ts: str) -> float:
        try:
            d = _dt.fromisoformat(ts)
            return d.timestamp()
        except Exception:
            return 0.0

    def _epoch_to_iso_local(epoch: float) -> str:
        return _dt.fromtimestamp(epoch, tz=_TAIPEI_TZ).isoformat()

    def _interp_at(series_epochs: list[tuple[float, float]], target: float, initial: float) -> float:
        """Linearly interpolate equity at `target` epoch from sorted (epoch, equity) series."""
        if not series_epochs:
            return initial
        if target <= series_epochs[0][0]:
            return series_epochs[0][1]
        if target >= series_epochs[-1][0]:
            return series_epochs[-1][1]
        # Binary search for bracketing points
        lo, hi = 0, len(series_epochs) - 1
        while lo + 1 < hi:
            mid = (lo + hi) // 2
            if series_epochs[mid][0] <= target:
                lo = mid
            else:
                hi = mid
        t0, v0 = series_epochs[lo]
        t1, v1 = series_epochs[hi]
        if t1 == t0:
            return v0
        frac = (target - t0) / (t1 - t0)
        return v0 + frac * (v1 - v0)

    # Convert each strategy's ISO timestamps to epoch floats for interpolation.
    per_strategy_epochs: dict[str, list[tuple[float, float]]] = {
        slug: sorted((_iso_to_epoch(ts), eq) for ts, eq in series)
        for slug, series in per_strategy.items()
    }

    # Determine grid boundaries from the union of all strategy time ranges.
    all_epochs = [ep for series in per_strategy_epochs.values() for ep, _ in series]
    if not all_epochs:
        equity_curve: list[tuple[str, float]] = []
    else:
        grid_start = min(all_epochs)
        grid_end = max(all_epochs)
        # Use hourly grid (3600s) — coarse enough to smooth jitter, fine enough for chart detail.
        step = 3600
        grid_epochs: list[float] = []
        t = grid_start
        while t <= grid_end + step:
            grid_epochs.append(t)
            t += step
        # Ensure the true end point is included.
        if grid_epochs[-1] < grid_end:
            grid_epochs.append(grid_end)

        equity_curve = []
        for ep in grid_epochs:
            total = sum(
                _interp_at(per_strategy_epochs[slug], ep, per_strategy_initial.get(slug, 0.0))
                for slug in per_strategy_epochs
            )
            equity_curve.append((_epoch_to_iso_local(ep), total))

    positions = [
        {
            "symbol": r["symbol"],
            "side": r["side"],
            "quantity": int(r["quantity"]),
            "avg_entry_price": float(r["avg_entry_price"]),
            "current_price": float(r["current_price"]),
            "unrealized_pnl": float(r["unrealized_pnl"]),
            "strategy_slug": r["strategy_slug"],
        }
        for r in position_rows
    ]
    recent_fills = [
        {
            "timestamp": r["timestamp"],
            "symbol": r["symbol"],
            "side": r["side"],
            "price": float(r["price"]),
            "quantity": int(r["quantity"]),
            "fee": float(r["fee"]),
            "strategy_slug": r["strategy_slug"],
            "is_session_close": bool(r["is_session_close"]),
            "signal_reason": r["signal_reason"] or "",
            "triggered": bool(r["triggered"]),
            "spread_role": _spread_role_for_fill(r["strategy_slug"], r["symbol"]),
        }
        for r in fill_rows
    ]

    latest_equity = equity_curve[-1][1] if equity_curve else 0.0
    return {
        "equity": latest_equity,
        "equity_curve": equity_curve,
        "positions": positions,
        "recent_fills": recent_fills,
        "trade_counts_by_session": trade_counts_by_session,
        "per_strategy_latest": latest_per_strategy,
    }


def _resolve_deployment_info(session) -> dict:
    """Resolve deployed candidate → params + backtest metrics + stale flag."""
    info: dict = {
        "deployed_candidate_id": session.deployed_candidate_id,
        "deployed_params": None,
        "backtest_metrics": None,
        "is_stale": False,
        "active_candidate_id": None,
    }
    if not session.deployed_candidate_id:
        return info
    try:
        from src.strategies.param_registry import ParamRegistry

        reg = ParamRegistry()
        # Get deployed candidate params
        row = reg._conn.execute(
            "SELECT params, run_id, strategy FROM param_candidates WHERE id = ?",
            (session.deployed_candidate_id,),
        ).fetchone()
        if row:
            info["deployed_params"] = json.loads(row["params"])
            # Get backtest metrics from the associated trial
            trial = reg._conn.execute(
                """SELECT sharpe, sortino, total_pnl, win_rate, max_drawdown_pct, profit_factor, trade_count
                   FROM param_trials WHERE run_id = ? ORDER BY sortino DESC LIMIT 1""",
                (row["run_id"],),
            ).fetchone()
            if trial:
                info["backtest_metrics"] = {
                    "sharpe": trial["sharpe"],
                    "sortino": trial["sortino"],
                    "total_pnl": trial["total_pnl"],
                    "win_rate": trial["win_rate"],
                    "max_drawdown_pct": trial["max_drawdown_pct"],
                    "profit_factor": trial["profit_factor"],
                    "trade_count": trial["trade_count"],
                }
            # Check stale: is deployed candidate still the active one?
            active = reg._conn.execute(
                "SELECT id FROM param_candidates WHERE strategy = ? AND is_active = 1",
                (row["strategy"],),
            ).fetchone()
            if active:
                info["active_candidate_id"] = active["id"]
            # Check code hash mismatch: does current file hash differ from deployed run's hash?
            try:
                from src.strategies.code_hash import compute_strategy_hash

                stored_run = reg._conn.execute(
                    "SELECT strategy_hash FROM param_runs WHERE id = ?",
                    (row["run_id"],),
                ).fetchone()
                if stored_run and stored_run["strategy_hash"]:
                    current_hash, _ = compute_strategy_hash(row["strategy"])
                    info["is_stale"] = current_hash != stored_run["strategy_hash"]
            except Exception:
                # If hash computation fails, don't mark as stale
                pass
        reg.close()
    except Exception:
        pass
    return info


def _build_settlement_block(sessions: list[dict]) -> dict:
    """Build settlement countdown + per-session roll urgency."""
    try:
        from src.data.settlement_calendar import (
            days_to_settlement,
            next_settlement,
            roll_urgency,
            settlement_month_code,
            next_month_code,
        )
        today = datetime.now(_TAIPEI_TZ).date()
        dts = days_to_settlement(today)
        ns = next_settlement(today)
        current_month = settlement_month_code(today)
        next_month = next_month_code(today)
        per_session: dict[str, dict] = {}
        for s in sessions:
            slug = s.get("strategy_slug", "")
            hp = _infer_holding_period(slug)
            urgency, days_left = roll_urgency(hp, today)
            per_session[s["session_id"]] = {
                "holding_period": hp,
                "urgency": urgency,
                "days_to_settlement": days_left,
            }
        return {
            "days_to_settlement": dts,
            "settlement_date": ns.isoformat(),
            "current_month": current_month,
            "next_month": next_month,
            "per_session": per_session,
        }
    except Exception:
        return {}


def _infer_holding_period(strategy_slug: str) -> str:
    """Best-effort holding period from slug path or STRATEGY_META."""
    if not strategy_slug:
        return "short_term"
    parts = strategy_slug.split("/")
    if len(parts) >= 1:
        prefix = parts[0]
        if prefix in ("short_term", "medium_term", "swing"):
            return prefix
    try:
        from src.strategies.registry import get_strategy_info
        info = get_strategy_info(strategy_slug)
        if info and info.holding_period:
            return info.holding_period.value
    except Exception:
        pass
    return "short_term"


@router.get("/war-room/mock-range")
async def mock_range() -> dict:
    """Return the min/max timestamps for mock account playback range."""
    conn = _get_mock_db_connection()
    try:
        row = conn.execute(
            """
            SELECT MIN(timestamp) as min_ts, MAX(timestamp) as max_ts
            FROM mock_session_snapshots
            WHERE session_id LIKE 'mock::mock-dev::%'
            """
        ).fetchone()
        if row and row["min_ts"]:
            return {"min_ts": row["min_ts"], "max_ts": row["max_ts"]}
        return {"min_ts": None, "max_ts": None}
    finally:
        conn.close()


@router.get("/war-room")
async def war_room(as_of: str | None = Query(None)) -> dict:
    # Direct-backtest playback: when the PlaybackEngine is active and an
    # as_of timestamp is provided, serve from the cached raw MCP results
    # instead of the mock DB. This guarantees bit-exact equity with MCP.
    use_engine = as_of is not None and _playback_engine is not None and _playback_engine.ready
    engine_state: dict | None = None
    engine_strat_states: dict[str, dict] = {}
    if use_engine:
        try:
            as_of_epoch = int(datetime.fromisoformat(
                as_of.replace("Z", "+00:00"),
            ).timestamp())
            engine_state = _playback_engine.get_account_state(as_of_epoch)
            for spec in _playback_engine.strategies:
                ss = _playback_engine.get_strategy_state(spec.slug, as_of_epoch)
                if ss is not None:
                    engine_strat_states[spec.slug] = ss
        except Exception:
            logger.warning("playback_engine.get_state_failed", exc_info=True)
            use_engine = False

    # Fallback: mock DB path (used when engine is not active or for
    # non-playback requests).
    if as_of is not None and not use_engine:
        mock_state: dict | None = None
        try:
            mock_state = _load_mock_as_of(_MOCK_ACCOUNT_ID, as_of)
        except Exception:
            mock_state = None
    elif not use_engine:
        mock_state = None
        try:
            mock_state = _load_mock_current(_MOCK_ACCOUNT_ID)
        except Exception:
            mock_state = None
    else:
        mock_state = None

    fetched_at = datetime.now(_TAIPEI_TZ).isoformat()
    try:
        data = get_war_room_data()
    except Exception as exc:
        return {
            "error": str(exc),
            "accounts": {},
            "all_sessions": [],
            "sessions_by_account": {},
            "fetched_at": fetched_at,
        }

    # Load live runner snapshots (paper-mode positions/PnL not visible to broker)
    runner_snaps: dict[str, dict] = {}
    try:
        pipeline = get_live_pipeline()
        if pipeline:
            runner_snaps = pipeline.get_runner_snapshots()
    except Exception:
        pass

    # session_id → mode lookup for the "live affects account, paper doesn't"
    # contract. The mock account branch below uses this to compute
    # `equity_val = mock_initial + sum(live_runner_pnl)`. Looked up via the
    # session manager + live portfolio manager so we don't have to thread
    # portfolio_id through the runner snapshots themselves.
    def _is_live_portfolio_session(sid: str | None) -> bool:
        if not sid:
            return False
        try:
            from src.api.helpers import (
                get_live_portfolio_manager,
                get_session_manager,
            )
            sm = get_session_manager()
            pm = get_live_portfolio_manager()
        except Exception:
            return False
        if sm is None or pm is None:
            return False
        sess = sm.get_session(sid)
        pid = getattr(sess, "portfolio_id", None) if sess is not None else None
        if not pid:
            return False
        portfolio = pm.get_portfolio(pid)
        return bool(portfolio and portfolio.mode == "live")

    accounts = {}
    for acct_id, info in data.get("accounts", {}).items():
        snap = info.get("snapshot")
        config = info.get("config")
        equity_curve = info.get("equity_curve", [])
        is_sandbox = bool(config.sandbox_mode) if config else False
        is_mock = bool(config and config.broker == "mock")
        # Account chip = the real broker money. Paper portfolios have their
        # own equity curve via /api/war-room.portfolio_equity_curves and the
        # PortfolioCard renders that — never sum runner equities into the
        # account total here, that was the source of the 100k/300k mixing.
        if is_mock:
            # Mock account uses fake money but should still demonstrate the
            # "live affects account, paper doesn't" contract end-to-end:
            #   mock_equity = mock_initial + sum(live runner P&L)
            # Paper runner P&L is excluded — those are sandbox bubbles that
            # only move per-portfolio curves.
            try:
                from src.api.helpers import get_gateway_registry
                _registry = get_gateway_registry()
                _gw = _registry.get_gateway(acct_id) if _registry else None
            except Exception:
                _gw = None
            mock_initial = float(getattr(_gw, "_initial", 2_000_000.0)) if _gw else 2_000_000.0
            live_pnl = sum(
                float(rs.get("realized_pnl", 0.0) or 0.0)
                + float(rs.get("unrealized_pnl", 0.0) or 0.0)
                for rs in runner_snaps.values()
                if rs.get("account_id") == acct_id
                and _is_live_portfolio_session(rs.get("session_id"))
            )
            equity_val = mock_initial + live_pnl
            margin_used_val = sum(
                float(rs.get("margin_used", 0.0) or 0.0)
                for rs in runner_snaps.values()
                if rs.get("account_id") == acct_id
                and _is_live_portfolio_session(rs.get("session_id"))
            )
            margin_avail_val = max(equity_val - margin_used_val, 0.0)
        elif snap and snap.connected:
            equity_val = snap.equity
            margin_used_val = snap.margin_used
            margin_avail_val = snap.margin_available
        else:
            # Broker disconnected: fall back to the most recent persisted
            # broker snapshot (account_equity_history) so the chip keeps
            # showing the last known real equity instead of going blank
            # during transient disconnects. Margin info is gone with the
            # snapshot, so those stay at zero.
            equity_val = equity_curve[-1][1] if equity_curve else None
            margin_used_val = 0
            margin_avail_val = 0
        positions_block = [
            {
                "symbol": p.symbol,
                "side": p.side,
                "quantity": p.quantity,
                "avg_entry_price": p.avg_entry_price,
                "current_price": p.current_price,
                "unrealized_pnl": p.unrealized_pnl,
                "strategy_slug": getattr(p, "strategy_slug", None),
            }
            for p in (snap.positions if snap and snap.connected else [])
        ]
        # Enrich with paper-mode runner positions (broker can't see these)
        if not positions_block and acct_id != _MOCK_ACCOUNT_ID and runner_snaps:
            for rs in runner_snaps.values():
                if rs["account_id"] == acct_id:
                    positions_block.extend(rs["positions"])
        # For live accounts, read from persistent FillStore instead of broker API
        # which loses fills on reconnect
        if acct_id != _MOCK_ACCOUNT_ID:
            try:
                fill_store = FillStore()
                db_fills = fill_store.get_recent_fills(acct_id, limit=200)
                recent_fills_block = [
                    {
                        "timestamp": f["timestamp"],
                        "symbol": f["symbol"],
                        "side": f["side"],
                        "price": float(f["price"]),
                        "quantity": int(f["quantity"]),
                        "fee": float(f["fee"]),
                        "strategy_slug": f["strategy_slug"],
                        "signal_reason": f.get("signal_reason", ""),
                        "is_session_close": bool(f.get("is_session_close", 0)),
                        "slippage_bps": f.get("slippage_bps"),
                    }
                    for f in db_fills
                ]
            except Exception:
                recent_fills_block = []
        else:
            recent_fills_block = [
                {
                    "timestamp": f.timestamp.isoformat() if hasattr(f.timestamp, "isoformat") else str(f.timestamp),
                    "symbol": f.symbol,
                    "side": f.side,
                    "price": f.price,
                    "quantity": f.quantity,
                    "fee": f.fee,
                    "strategy_slug": None,
                }
                for f in (snap.recent_fills if snap and snap.connected else [])
            ]
        equity_curve_block = [
            {"timestamp": t.isoformat(), "equity": e} for t, e in equity_curve
        ]

        # Direct-backtest engine takes priority over mock DB for mock-dev.
        if acct_id == _MOCK_ACCOUNT_ID and use_engine and engine_state is not None:
            equity_val = float(engine_state["equity"]) or equity_val
            positions_block = engine_state["positions"]
            recent_fills_block = engine_state["recent_fills"]
            equity_curve_block = engine_state["equity_curve"]
        elif acct_id == _MOCK_ACCOUNT_ID and mock_state is not None:
            equity_val = float(mock_state["equity"]) or equity_val
            positions_block = mock_state["positions"]
            recent_fills_block = mock_state["recent_fills"]
            equity_curve_block = [
                {"timestamp": ts, "equity": eq}
                for ts, eq in mock_state["equity_curve"]
            ]

        accounts[acct_id] = {
            "display_name": config.display_name if config else acct_id,
            "broker": config.broker if config else "",
            "sandbox_mode": is_sandbox,
            "connected": bool(snap and snap.connected),
            "connect_error": info.get("connect_error"),
            "equity": equity_val,
            "margin_used": margin_used_val,
            "margin_available": margin_avail_val,
            "positions": positions_block,
            "recent_fills": recent_fills_block,
            "equity_curve": equity_curve_block,
        }
    # Get session equity curves from SnapshotStore
    session_equity_curves: dict[str, list] = {}
    try:
        from src.trading_session.store import SnapshotStore
        snap_store = SnapshotStore()
        for s in data.get("all_sessions", []):
            curve = snap_store.get_equity_curve(s.session_id, days=30)
            session_equity_curves[s.session_id] = [
                {"timestamp": t.isoformat(), "equity": e} for t, e in curve
            ]
    except Exception:
        pass

    sessions = []
    for s in data.get("all_sessions", []):
        snap = s.current_snapshot
        # Fallback: load latest snapshot from DB when current_snapshot is None (e.g., sandbox accounts)
        if snap is None:
            try:
                latest = snap_store.get_latest_snapshot(s.session_id)
                if latest:
                    from src.trading_session.session import SessionSnapshot
                    from src.broker_gateway.types import LivePosition
                    # Filter account-level positions to this session's symbol
                    acct_info = data.get("accounts", {}).get(s.account_id, {})
                    acct_snap = acct_info.get("snapshot")
                    fallback_positions = []
                    if acct_snap and acct_snap.positions:
                        fallback_positions = [
                            LivePosition(
                                symbol=p.symbol,
                                side=p.side,
                                quantity=p.quantity,
                                avg_entry_price=p.avg_entry_price,
                                current_price=getattr(p, "current_price", 0),
                                unrealized_pnl=p.unrealized_pnl,
                            )
                            for p in acct_snap.positions
                            if p.symbol == s.symbol
                        ]
                    snap = SessionSnapshot(
                        timestamp=datetime.fromisoformat(latest["timestamp"]),
                        equity=latest["equity"],
                        unrealized_pnl=latest.get("unrealized_pnl", 0),
                        realized_pnl=latest.get("realized_pnl", 0),
                        drawdown_pct=latest.get("drawdown_pct", 0),
                        peak_equity=latest.get("peak_equity", latest["equity"]),
                        trade_count=latest.get("trade_count", 0),
                        positions=fallback_positions,
                    )
            except Exception:
                pass
        deploy_info = _resolve_deployment_info(s)
        mock_trade_count = None
        mock_strategy_snap = None
        # Direct-backtest engine: per-strategy state
        if (
            use_engine
            and s.account_id == _MOCK_ACCOUNT_ID
            and s.strategy_slug
        ):
            eng_snap = engine_strat_states.get(s.strategy_slug)
            if eng_snap is None and s.strategy_slug:
                short = s.strategy_slug.split("/")[-1]
                for full_slug, ss in engine_strat_states.items():
                    if full_slug.split("/")[-1] == short:
                        eng_snap = ss
                        break
            if eng_snap is not None:
                mock_strategy_snap = eng_snap
                mock_trade_count = eng_snap.get("trade_count")
        elif (
            mock_state is not None
            and s.account_id == _MOCK_ACCOUNT_ID
            and s.strategy_slug
        ):
            mock_session_id = f"mock::{_MOCK_ACCOUNT_ID}::{s.strategy_slug.replace('/', '__')}"
            mock_trade_count = mock_state["trade_counts_by_session"].get(mock_session_id)
            psl = mock_state.get("per_strategy_latest", {})
            mock_strategy_snap = psl.get(s.strategy_slug)
            if mock_strategy_snap is None:
                short = s.strategy_slug.split("/")[-1]
                for full_slug in psl:
                    if full_slug.split("/")[-1] == short:
                        mock_strategy_snap = psl[full_slug]
                        if mock_trade_count is None:
                            alt_sid = f"mock::{_MOCK_ACCOUNT_ID}::{full_slug.replace('/', '__')}"
                            mock_trade_count = mock_state["trade_counts_by_session"].get(alt_sid)
                        break
        # During playback (as_of), prefer mock per-strategy snapshot over live snapshot.
        # If in playback mode with a mock account but no mock data yet, return zeros
        # instead of live data (which would be identical across strategies).
        snapshot_block: dict | None = None
        is_playback_mock = as_of and s.account_id == _MOCK_ACCOUNT_ID
        if mock_strategy_snap is not None:
            positions_source = (
                (engine_state.get("positions") if engine_state else None)
                or (mock_state.get("positions") if mock_state else None)
                or []
            )
            snapshot_block = {
                "equity": mock_strategy_snap["equity"],
                "unrealized_pnl": mock_strategy_snap["unrealized_pnl"],
                "realized_pnl": mock_strategy_snap["realized_pnl"],
                "drawdown_pct": mock_strategy_snap["drawdown_pct"],
                "trade_count": mock_trade_count if mock_trade_count is not None else mock_strategy_snap["trade_count"],
                "positions": [
                    p for p in positions_source
                    if p.get("strategy_slug") == s.strategy_slug
                ],
            }
        elif is_playback_mock:
            snapshot_block = {
                "equity": 0,
                "unrealized_pnl": 0,
                "realized_pnl": 0,
                "drawdown_pct": 0,
                "trade_count": mock_trade_count or 0,
                "positions": [],
            }
        elif snap:
            snapshot_block = {
                "equity": snap.equity,
                "unrealized_pnl": snap.unrealized_pnl,
                "realized_pnl": snap.realized_pnl,
                "drawdown_pct": snap.drawdown_pct,
                "trade_count": mock_trade_count if mock_trade_count is not None else snap.trade_count,
                "positions": [
                    {
                        "symbol": p.symbol,
                        "side": p.side,
                        "quantity": p.quantity,
                        "avg_entry_price": p.avg_entry_price,
                        "unrealized_pnl": p.unrealized_pnl,
                    }
                    for p in snap.positions
                ],
            }
        elif mock_trade_count is not None:
            snapshot_block = {
                "equity": 0,
                "unrealized_pnl": 0,
                "realized_pnl": 0,
                "drawdown_pct": 0,
                "trade_count": mock_trade_count,
                "positions": [],
            }
        # Enrich session snapshot with live runner data (paper-mode)
        rs = runner_snaps.get(s.session_id)
        if rs and s.account_id != _MOCK_ACCOUNT_ID:
            if snapshot_block is None:
                snapshot_block = {}
            snapshot_block["equity"] = rs["equity"]
            snapshot_block["realized_pnl"] = rs["realized_pnl"]
            snapshot_block["unrealized_pnl"] = rs["unrealized_pnl"]
            snapshot_block["positions"] = rs["positions"]
            if rs["trade_count"] > snapshot_block.get("trade_count", 0):
                snapshot_block["trade_count"] = rs["trade_count"]
        sessions.append(
            {
                "session_id": s.session_id,
                "account_id": s.account_id,
                "strategy_slug": s.strategy_slug,
                "symbol": s.symbol,
                "status": s.status,
                "equity_share": getattr(s, "equity_share", 1.0),
                "portfolio_id": getattr(s, "portfolio_id", None),
                **deploy_info,
                "snapshot": snapshot_block,
                "equity_curve": session_equity_curves.get(s.session_id, []),
            }
        )
    settlement_block = _build_settlement_block(sessions)
    portfolio_equity_curves_block: dict[str, list] = {}
    for pid, curve in (data.get("portfolio_equity_curves") or {}).items():
        portfolio_equity_curves_block[pid] = [
            {"timestamp": t.isoformat() if hasattr(t, "isoformat") else str(t), "equity": e}
            for t, e in curve
        ]
    response = {
        "accounts": accounts,
        "all_sessions": sessions,
        "sessions_by_account": data.get("sessions_by_account", {}),
        "portfolio_equity_curves": portfolio_equity_curves_block,
        "settlement": settlement_block,
        "fetched_at": fetched_at,
    }
    return response
