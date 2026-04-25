"""Computation helpers for the API layer."""
from __future__ import annotations

import io
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import threading
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

_TAIPEI_TZ = timezone(timedelta(hours=8))
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from src.data.contracts import CONTRACTS, CONTRACTS_BY_SYMBOL, TaifexContract
from src.data.db import DEFAULT_DB_PATH

_DB_PATH = DEFAULT_DB_PATH

# Re-export for backward compatibility with API routes that import from here
FUTURES_CONTRACTS = CONTRACTS
FUTURES_BY_SYMBOL = CONTRACTS_BY_SYMBOL
FuturesContract = TaifexContract

TIMEFRAMES: list[dict[str, str]] = [
    {"label": "1 min", "value": "1"},
    {"label": "5 min", "value": "5"},
    {"label": "15 min", "value": "15"},
    {"label": "1 hour", "value": "60"},
    {"label": "Daily", "value": "1440"},
]

# ── Crawl state management ──────────────────────────────────────────────────
@dataclass
class CrawlState:
    running: bool = False
    symbol: str = ""
    log_lines: list[str] = field(default_factory=list)
    progress: str = ""
    error: str | None = None
    finished: bool = False
    bars_stored: int = 0


_crawl_state = CrawlState()
_crawl_lock = threading.Lock()


def get_crawl_state() -> dict:
    with _crawl_lock:
        return {
            "running": _crawl_state.running,
            "symbol": _crawl_state.symbol,
            "log": "\n".join(_crawl_state.log_lines[-80:]),
            "progress": _crawl_state.progress,
            "error": _crawl_state.error,
            "finished": _crawl_state.finished,
            "bars_stored": _crawl_state.bars_stored,
        }


def _crawl_log(msg: str) -> None:
    ts = datetime.now(_TAIPEI_TZ).strftime("%H:%M:%S")
    with _crawl_lock:
        _crawl_state.log_lines.append(f"[{ts}] {msg}")


def start_crawl(db_symbol: str, start_str: str, end_str: str) -> bool:
    """Start a background crawl thread. Returns False if already running."""
    with _crawl_lock:
        if _crawl_state.running:
            return False
        _crawl_state.running = True
        _crawl_state.symbol = db_symbol
        _crawl_state.log_lines.clear()
        _crawl_state.progress = "Starting..."
        _crawl_state.error = None
        _crawl_state.finished = False
        _crawl_state.bars_stored = 0

    t = threading.Thread(
        target=_crawl_worker,
        args=(db_symbol, start_str, end_str),
        daemon=True,
    )
    t.start()
    return True


def _crawl_worker(db_symbol: str, start_str: str, end_str: str) -> None:
    """Run crawl in a subprocess to isolate shioaji C++ crashes from the API server."""
    contract = FUTURES_BY_SYMBOL.get(db_symbol)
    if not contract:
        with _crawl_lock:
            _crawl_state.error = f"Unknown symbol: {db_symbol}"
            _crawl_state.running = False
            _crawl_state.finished = True
        return

    _crawl_log(f"Crawl started: {contract.display_name} ({contract.shioaji_path})")
    _crawl_log(f"Date range: {start_str} to {end_str}")

    try:
        _crawl_log("Connecting to Sinopac API (subprocess)...")
        with _crawl_lock:
            _crawl_state.progress = "Logging in to Sinopac..."

        # Run the shioaji-dependent crawl in a subprocess to isolate C++ crashes.
        proc = subprocess.run(
            [sys.executable, "-m", "src.data.crawl_cli",
             contract.shioaji_path, contract.db_symbol, start_str, end_str],
            capture_output=True, text=True, timeout=600,
            cwd=str(Path(__file__).resolve().parents[2]),
        )
        if proc.returncode != 0:
            stderr = proc.stderr.strip()
            raise RuntimeError(f"Crawl subprocess failed (rc={proc.returncode}): {stderr[-500:]}")

        for line in proc.stdout.strip().splitlines():
            _crawl_log(line)

        total = 0
        for line in proc.stdout.splitlines():
            if line.startswith("TOTAL="):
                total = int(line.split("=", 1)[1])
        _crawl_log(f"Crawl complete: {total:,} bars stored for {contract.db_symbol}")
        with _crawl_lock:
            _crawl_state.bars_stored = total
            _crawl_state.progress = f"Done — {total:,} bars"

    except Exception as exc:
        _crawl_log(f"ERROR: {exc}")
        with _crawl_lock:
            _crawl_state.error = str(exc)
            _crawl_state.progress = "Failed"
    finally:
        with _crawl_lock:
            _crawl_state.running = False
            _crawl_state.finished = True
        _crawl_log("--- crawl thread exited ---")


# ── Data coverage & export ──────────────────────────────────────────────────
_coverage_cache: list[dict] = []
_coverage_cache_ts: float = 0.0
_COVERAGE_TTL_SECS: float = 60.0


def get_db_coverage(force: bool = False) -> list[dict]:
    """Return per-symbol coverage stats from the database (cached for 60s)."""
    import time as _time

    global _coverage_cache, _coverage_cache_ts
    now = _time.monotonic()
    if not force and _coverage_cache and (now - _coverage_cache_ts) < _COVERAGE_TTL_SECS:
        return _coverage_cache

    if not _DB_PATH.exists():
        return []
    try:
        with sqlite3.connect(str(_DB_PATH)) as conn:
            # Use the (symbol, timestamp) index: scan only the index leaf pages
            rows = conn.execute(
                "SELECT symbol, COUNT(*), MIN(timestamp), MAX(timestamp) "
                "FROM ohlcv_bars GROUP BY symbol ORDER BY symbol"
            ).fetchall()
        _coverage_cache = [
            {"symbol": r[0], "bars": r[1], "from": r[2], "to": r[3]}
            for r in rows
        ]
        _coverage_cache_ts = now
        return _coverage_cache
    except Exception:
        return _coverage_cache  # return stale cache on error


def export_ohlcv_csv(symbol: str, start: datetime, end: datetime, tf_minutes: int) -> str:
    """Load, aggregate, and return CSV string."""
    df = load_ohlcv(symbol, start, end, tf_minutes)
    if df.empty:
        return ""
    buf = io.StringIO()
    df.to_csv(buf, index=False)
    return buf.getvalue()


GRID_PARAMS: dict[str, dict[str, float]] = {
    "Stop ATR Mult (λ)": {"min": 0.5, "max": 4.0, "default_min": 1.0, "default_max": 3.0},
    "Add Trigger ATR (Δ)": {"min": 1.0, "max": 20.0, "default_min": 2.0, "default_max": 8.0},
    "Max Pyramid Levels": {"min": 1.0, "max": 8.0, "default_min": 2.0, "default_max": 6.0},
    "Kelly Fraction": {"min": 0.05, "max": 1.0, "default_min": 0.1, "default_max": 0.5},
    "Entry Conf Threshold": {"min": 0.0, "max": 1.0, "default_min": 0.4, "default_max": 0.9},
    "Trail ATR Mult": {"min": 1.0, "max": 10.0, "default_min": 1.5, "default_max": 5.0},
    "Margin Limit": {"min": 0.1, "max": 1.0, "default_min": 0.2, "default_max": 0.8},
}

# ── Strategy Optimizer ──────────────────────────────────────────────────────
# ── Strategy discovery (delegates to src.strategies.registry) ────────────────
@dataclass
class StrategyInfo:
    name: str          # human-readable: "ATR Mean Reversion"
    module: str        # e.g. "src.strategies.short_term.mean_reversion.atr_mean_reversion"
    factory: str       # e.g. "create_atr_mean_reversion_engine"
    param_grid: dict[str, dict] | None = None
    holding_period: str | None = None
    signal_timeframe: str | None = None
    stop_architecture: str | None = None
    category: str | None = None
    tradeable_sessions: list[str] | None = None


def discover_strategies() -> dict[str, StrategyInfo]:
    """Discover strategies via the central registry."""
    from src.strategies.registry import get_all, get_param_grid
    result: dict[str, StrategyInfo] = {}
    for slug, reg_info in get_all().items():
        grid = get_param_grid(slug)
        meta = reg_info.meta or {}
        result[slug] = StrategyInfo(
            name=reg_info.name, module=reg_info.module,
            factory=reg_info.factory, param_grid=grid or None,
            holding_period=reg_info.holding_period.value if reg_info.holding_period else None,
            signal_timeframe=reg_info.signal_timeframe.value if reg_info.signal_timeframe else None,
            stop_architecture=reg_info.stop_architecture.value if reg_info.stop_architecture else None,
            category=reg_info.category.value if reg_info.category else None,
            tradeable_sessions=meta.get("tradeable_sessions"),
        )
    return result


def get_strategy_registry() -> dict[str, StrategyInfo]:
    """Return the current strategy registry, re-discovering if invalidated."""
    return discover_strategies()


# Backward compat — prefer get_strategy_registry() for live data
STRATEGY_REGISTRY: dict[str, StrategyInfo] = get_strategy_registry()


def get_param_grid_for_strategy(slug: str) -> dict[str, dict]:
    """Return the optimizer param grid for a strategy from the central registry."""
    from src.strategies.registry import get_param_grid
    try:
        return get_param_grid(slug)
    except KeyError:
        info = get_strategy_registry().get(slug)
        return info.param_grid or {} if info else {}

# Objectives available in the optimizer (maps display label → metric key)
OPT_OBJECTIVES: list[dict[str, str]] = [
    {"label": "Sortino Ratio", "value": "sortino"},
    {"label": "Sharpe Ratio", "value": "sharpe"},
    {"label": "Profit Factor", "value": "profit_factor"},
    {"label": "Calmar Ratio", "value": "calmar"},
    {"label": "Win Rate", "value": "win_rate"},
]


@dataclass
class OptimizerState:
    running: bool = False
    finished: bool = False
    error: str | None = None
    progress: str = ""
    result_data: dict | None = None
    _proc: subprocess.Popen | None = field(default=None, repr=False, compare=False)
    _output_path: str | None = field(default=None, repr=False, compare=False)


_opt_state = OptimizerState()
_opt_lock = threading.Lock()


def get_optimizer_state() -> dict:
    """Return a copy of the current optimizer state (also polls subprocess)."""
    with _opt_lock:
        _poll_subprocess()
        return {
            "running": _opt_state.running,
            "finished": _opt_state.finished,
            "error": _opt_state.error,
            "progress": _opt_state.progress,
            "result_data": _opt_state.result_data,
        }


def _poll_subprocess() -> None:
    """Called under _opt_lock. Check if the subprocess has finished."""
    proc = _opt_state._proc
    if proc is None or _opt_state.finished:
        return
    rc = proc.poll()
    if rc is None:
        return  # still running

    output_path = _opt_state._output_path
    if output_path and Path(output_path).exists():
        try:
            data = json.loads(Path(output_path).read_text())
            if data.get("status") == "ok":
                n_combos = len(data.get("trials", []))
                obj = data.get("objective", "sortino")
                best_val = data.get("is_metrics", {}).get(obj, 0)
                _opt_state.result_data = data
                _opt_state.progress = (
                    f"Done — {n_combos} trials, best {obj}: {best_val:.4f}"
                )
            else:
                _opt_state.error = data.get("error", "Unknown error in optimizer process")
                _opt_state.progress = "Failed"
        except Exception as exc:
            _opt_state.error = f"Failed to read result: {exc}"
            _opt_state.progress = "Failed"
    elif rc != 0:
        _opt_state.error = f"Optimizer process exited with code {rc}"
        _opt_state.progress = "Failed"
    else:
        _opt_state.error = "Optimizer process finished but no output file found"
        _opt_state.progress = "Failed"

    _opt_state.running = False
    _opt_state.finished = True
    _opt_state._proc = None


def start_optimizer_run(
    symbol: str,
    start_str: str,
    end_str: str,
    param_grid: dict[str, list],
    is_fraction: float,
    objective: str,
    n_jobs: int = 1,
    factory_module: str = "src.strategies.atr_mean_reversion",
    factory_name: str = "create_atr_mean_reversion_engine",
    slippage_bps: float = 0.0,
    commission_bps: float = 0.0,
    commission_fixed_per_contract: float = 0.0,
) -> bool:
    """Spawn the optimizer as a subprocess. Returns False if already running."""
    with _opt_lock:
        if _opt_state.running:
            return False

        config = {
            "symbol": symbol,
            "start": start_str,
            "end": end_str,
            "param_grid": param_grid,
            "is_fraction": is_fraction,
            "objective": objective,
            "n_jobs": n_jobs,
            "factory_module": factory_module,
            "factory_name": factory_name,
            "slippage_bps": slippage_bps,
            "commission_bps": commission_bps,
            "commission_fixed_per_contract": commission_fixed_per_contract,
        }
        tmpdir = tempfile.mkdtemp(prefix="qe_opt_")
        config_path = os.path.join(tmpdir, "config.json")
        output_path = os.path.join(tmpdir, "result.json")
        Path(config_path).write_text(json.dumps(config, default=str))

        n_combos = 1
        for v in param_grid.values():
            n_combos *= len(v)

        proc = subprocess.Popen(
            [sys.executable, "-m", "src.simulator.optimizer_cli",
             "--config", config_path, "--output", output_path],
            cwd=str(Path(_DB_PATH).parent),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        _opt_state.running = True
        _opt_state.finished = False
        _opt_state.error = None
        _opt_state.result_data = None
        _opt_state.progress = f"Running {n_combos} combos on {symbol} ({start_str} → {end_str})…"
        _opt_state._proc = proc
        _opt_state._output_path = output_path

    return True


def load_symbols() -> list[str]:
    if not _DB_PATH.exists():
        return []
    try:
        with sqlite3.connect(str(_DB_PATH)) as conn:
            return [r[0] for r in conn.execute(
                "SELECT DISTINCT symbol FROM ohlcv_bars ORDER BY symbol"
            ).fetchall()]
    except Exception:
        return []


def load_ohlcv(symbol: str, start: datetime, end: datetime, tf_minutes: int) -> pd.DataFrame:
    """Load OHLCV bars from SQLite, aggregating to the requested timeframe in SQL.

    For tf_minutes > 1, uses a CTE with MIN/MAX(rowid) to get correct open and
    close prices without loading all 1-min rows into Python.
    """
    if not _DB_PATH.exists():
        return pd.DataFrame()
    # Use space-separated format to match DB timestamps (not ISO T-separator).
    # If end is midnight (date-only input), extend to end-of-day so all
    # bars on that date are included.
    ts_start = start.strftime("%Y-%m-%d %H:%M:%S")
    if end.hour == 0 and end.minute == 0 and end.second == 0:
        ts_end = end.strftime("%Y-%m-%d") + " 23:59:59"
    else:
        ts_end = end.strftime("%Y-%m-%d %H:%M:%S")
    session_filter_sql = (
        "(time(timestamp) >= '15:00:00' "
        "OR time(timestamp) < '05:00:00' "
        "OR (time(timestamp) >= '08:45:00' AND time(timestamp) <= '13:45:59'))"
    )
    conn = sqlite3.connect(str(_DB_PATH))
    try:
        if tf_minutes <= 1:
            query = (
                "SELECT timestamp, open, high, low, close, volume "
                "FROM ohlcv_bars WHERE symbol = ? AND timestamp >= ? AND timestamp <= ? "
                f"AND {session_filter_sql} "
                "ORDER BY timestamp"
            )
            df = pd.read_sql_query(
                query, conn,
                params=(symbol, ts_start, ts_end),
                parse_dates=["timestamp"],
            )
        elif tf_minutes == 5:
            # Route to pre-aggregated 5m table for consistency with backtest engine
            # Timestamps in ohlcv_5m use space separator (not T), so compare with same format
            query = (
                "SELECT timestamp, open, high, low, close, volume "
                "FROM ohlcv_5m WHERE symbol = ? AND timestamp >= ? AND timestamp <= ? "
                "ORDER BY timestamp"
            )
            df = pd.read_sql_query(
                query, conn,
                params=(symbol, ts_start, ts_end),
                parse_dates=["timestamp"],
            )
        elif tf_minutes == 60:
            # Route to pre-aggregated 1h table for consistency with backtest engine
            # (uses session-relative right-aligned timestamps)
            # Timestamps in ohlcv_1h use space separator (not T), so compare with same format
            query = (
                "SELECT timestamp, open, high, low, close, volume "
                "FROM ohlcv_1h WHERE symbol = ? AND timestamp >= ? AND timestamp <= ? "
                "ORDER BY timestamp"
            )
            df = pd.read_sql_query(
                query, conn,
                params=(symbol, ts_start, ts_end),
                parse_dates=["timestamp"],
            )
        elif tf_minutes >= 1440:
            # Daily bars: group by TAIFEX trading day.
            # Night session (>=15:00) belongs to next calendar day's trading day.
            # Night session after midnight (<05:00) belongs to current calendar day.
            # Day session (08:45-13:45) belongs to current calendar day.
            query = f"""
            WITH trading_days AS (
                SELECT
                    rowid,
                    timestamp,
                    open, high, low, close, volume,
                    CASE
                        WHEN time(timestamp) >= '15:00:00'
                            THEN date(timestamp, '+1 day')
                        WHEN time(timestamp) < '05:00:00'
                            THEN date(timestamp)
                        ELSE date(timestamp)
                    END AS trade_date
                FROM ohlcv_bars
                WHERE symbol = :sym
                  AND timestamp >= :ts_start
                  AND timestamp <= :ts_end
                  AND {session_filter_sql}
            ),
            day_bounds AS (
                SELECT
                    trade_date,
                    MIN(rowid) AS first_rid,
                    MAX(rowid) AS last_rid,
                    MAX(high)  AS high,
                    MIN(low)   AS low,
                    SUM(volume) AS volume
                FROM trading_days
                GROUP BY trade_date
            )
            SELECT
                f.timestamp,
                f.open,
                db.high,
                db.low,
                l.close,
                db.volume
            FROM day_bounds db
            JOIN ohlcv_bars f ON f.rowid = db.first_rid
            JOIN ohlcv_bars l ON l.rowid = db.last_rid
            ORDER BY db.trade_date
            """
            df = pd.read_sql_query(
                query, conn,
                params={
                    "sym": symbol,
                    "ts_start": ts_start,
                    "ts_end": ts_end,
                },
                parse_dates=["timestamp"],
            )
        else:
            # Sub-daily aggregation: bucket = floor(unix_ts / bucket_secs)
            bucket_secs = tf_minutes * 60
            query = f"""
            WITH buckets AS (
                SELECT
                    CAST(strftime('%s', timestamp) / :bkt AS INTEGER) AS bkt,
                    MIN(rowid) AS first_rid,
                    MAX(rowid) AS last_rid,
                    MAX(high)  AS high,
                    MIN(low)   AS low,
                    SUM(volume) AS volume
                FROM ohlcv_bars
                WHERE symbol = :sym
                  AND timestamp >= :ts_start
                  AND timestamp <= :ts_end
                  AND {session_filter_sql}
                GROUP BY bkt
            )
            SELECT
                datetime(b.bkt * :bkt, 'unixepoch') AS timestamp,
                f.open,
                b.high,
                b.low,
                l.close,
                b.volume
            FROM buckets b
            JOIN ohlcv_bars f ON f.rowid = b.first_rid
            JOIN ohlcv_bars l ON l.rowid = b.last_rid
            ORDER BY timestamp
            """
            df = pd.read_sql_query(
                query, conn,
                params={
                    "bkt": bucket_secs,
                    "sym": symbol,
                    "ts_start": ts_start,
                    "ts_end": ts_end,
                },
                parse_dates=["timestamp"],
            )
    finally:
        conn.close()
    return df


def generate_equity_curve(n: int = 252, seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    returns = rng.normal(0.0003, 0.015, n)
    equity = 2_000_000.0 * np.cumprod(1 + returns)
    dates = pd.date_range(start="2024-01-02", periods=n, freq="B")
    return pd.DataFrame({"date": dates, "equity": equity})


def generate_buy_and_hold(n: int = 252, seed: int = 42) -> pd.DataFrame:
    """Simulated index buy-and-hold for benchmarking (lower drift, lower vol)."""
    rng = np.random.default_rng(seed + 1000)
    returns = rng.normal(0.00035, 0.012, n)
    equity = 2_000_000.0 * np.cumprod(1 + returns)
    dates = pd.date_range(start="2024-01-02", periods=n, freq="B")
    return pd.DataFrame({"date": dates, "equity": equity})


def generate_trades(n: int = 40, seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    dates = pd.date_range(start="2024-01-05", periods=n, freq="5B")
    sides = rng.choice(["buy", "sell"], n)
    prices = 19500 + rng.normal(0, 300, n).cumsum() + 500
    qtys = rng.choice([1, 2, 3, 4], n)
    reasons = rng.choice(["entry", "stop_loss", "trail_stop", "take_profit", "pyramid_add"], n)
    pnls = rng.normal(5000, 30000, n)
    return pd.DataFrame({
        "time": [str(d.date()) for d in dates[:n]],
        "side": sides,
        "price": np.round(prices, 0).astype(int),
        "qty": qtys,
        "reason": reasons,
        "pnl": np.round(pnls, 0).astype(int),
    })


def histogram_data(values: Any, bins: int = 30) -> tuple[list[float], list[int]]:
    counts, edges = np.histogram(values, bins=bins)
    mids = [(edges[i] + edges[i + 1]) / 2 for i in range(len(counts))]
    return mids, counts.tolist()


def run_strategy_backtest(
    strategy_slug: str,
    symbol: str,
    start_str: str,
    end_str: str,
    initial_equity: float = 2_000_000.0,
    strategy_params: dict | None = None,
    max_loss: float = 500_000.0,
    slippage_bps: float = 0.0,
    commission_bps: float = 0.0,
    commission_fixed_per_contract: float = 0.0,
    provenance: dict | None = None,
    intraday: bool = False,
) -> dict:
    """Run a backtest on real DB data via the MCP facade.

    Delegates to run_backtest_realdata_for_mcp so the dashboard and MCP
    tool produce identical results for the same inputs.

    Returns dict with keys: daily_returns (np.ndarray), equity_curve (list),
    bnh_returns (np.ndarray), bnh_equity (list), metrics (dict), bars_count (int).
    """
    from src.mcp_server.facade import run_backtest_realdata_for_mcp

    from src.strategies.registry import get_info as _get_info
    try:
        resolved_info = _get_info(strategy_slug)
        facade_name = resolved_info.slug
    except KeyError:
        raise ValueError(f"Unknown strategy: {strategy_slug}")

    merged_params = dict(strategy_params or {})
    merged_params["max_loss"] = max_loss
    if slippage_bps:
        merged_params["slippage_bps"] = slippage_bps
    if commission_bps:
        merged_params["commission_bps"] = commission_bps
    if commission_fixed_per_contract:
        merged_params["commission_fixed_per_contract"] = commission_fixed_per_contract

    result = run_backtest_realdata_for_mcp(
        symbol=symbol,
        start=start_str,
        end=end_str,
        strategy=facade_name,
        strategy_params=merged_params,
        initial_equity=initial_equity,
        intraday=intraday,
    )
    if "error" in result:
        raise ValueError(result["error"])
    # Ensure numpy arrays are converted to lists for JSON serialization.
    for key in ("daily_returns", "bnh_returns"):
        if key in result and hasattr(result[key], "tolist"):
            result[key] = result[key].tolist()
    if provenance:
        result["provenance"] = provenance
    return result


def run_grid_mc(
    x_vals: list[float],
    y_vals: list[float],
    n_sims: int,
    seed: int = 42,
) -> np.ndarray:
    """Monte Carlo for each (x, y) cell. Returns shape (len(y), len(x), 4) metrics."""
    results = np.zeros((len(y_vals), len(x_vals), 4))
    for yi, yv in enumerate(y_vals):
        for xi, xv in enumerate(x_vals):
            cell_rng = np.random.default_rng(seed + yi * 1000 + xi)
            drift = 0.0003 * (1 + (xv - 2) * 0.05 - (yv - 2) * 0.03)
            vol = 0.015 * (1 + (yv - 1) * 0.02)
            final_rets = []
            for _ in range(n_sims):
                r = cell_rng.normal(drift, vol, 252)
                final_rets.append(float(np.prod(1 + r) - 1) * 100)
            arr = np.array(final_rets)
            mean_ret = float(np.mean(arr))
            std_ret = float(np.std(arr))
            sharpe = mean_ret / std_ret if std_ret > 0 else 0.0
            win_rate = float(np.mean(arr > 0) * 100)
            results[yi, xi] = [mean_ret, sharpe, win_rate, std_ret]
    return results


# ── War Room data helpers ────────────────────────────────────────────────

_session_manager = None
_gateway_registry = None
_account_equity_store = None
_portfolio_equity_store = None
_market_data_subscriber = None
_live_bar_store = None
_live_pipeline = None
_telegram_dispatcher = None
_live_portfolio_store = None
_live_portfolio_manager = None


_subscriber_tick_count = 0
_subscriber_last_tick_ts = None
# Resolved-contract-code → db_symbol map. Populated at subscribe time so the
# tick callback can route by exact code (R1 vs R2) rather than by the
# group-prefix collapsing routine that used to lump R2 ticks into R1's table.
_code_to_symbol: dict[str, str] = {}


def get_subscriber_stats() -> dict:
    """Return market data subscriber health stats."""
    return {
        "tick_count": _subscriber_tick_count,
        "last_tick_ts": _subscriber_last_tick_ts.isoformat() if _subscriber_last_tick_ts else None,
        "status": "connected" if _market_data_subscriber and _market_data_subscriber != "initializing" else "disconnected",
    }


def _start_market_data_subscriber() -> None:
    """Start a standalone market data subscription with auto-reconnect.

    Feeds ticks into:
    1. WebSocket broadcaster for live UI updates
    2. Shared LiveMinuteBarStore for strategy evaluation pipeline
    """
    global _market_data_subscriber
    if _market_data_subscriber is not None:
        return

    import asyncio
    import logging
    import threading
    import time
    from datetime import datetime, timezone
    from zoneinfo import ZoneInfo

    logger = logging.getLogger(__name__)

    # Skip standalone subscriber when a sinopac gateway is already logged in
    # with the same person_id. Shioaji allows one session per person_id; a
    # second login returns 451 "Too Many Connections" and the subscriber
    # would reconnect-spam every 30s. The gateway's own tick callback already
    # feeds the shared bar store (see _init_war_room).
    try:
        if _gateway_registry is not None:
            for _aid in _gateway_registry.list_accounts():
                _gw = _gateway_registry.get_gateway(_aid)
                if _gw is not None and getattr(_gw, "broker_name", "") == "Sinopac" and getattr(_gw, "is_connected", False):
                    logger.info("market_data_subscriber: skipped (sinopac gateway already subscribed)")
                    _market_data_subscriber = "gateway_owned"
                    return
    except Exception:
        pass

    try:
        import shioaji as sj
    except ImportError:
        logger.info("market_data_subscriber: shioaji not installed, skipping")
        return

    try:
        from src.secrets.manager import get_secret_manager
        sm = get_secret_manager()
        creds = sm.get_group("sinopac")
        api_key = creds.get("api_key")
        secret_key = creds.get("secret_key")
        if not api_key or not secret_key:
            logger.info("market_data_subscriber: credentials not found, skipping")
            return
    except Exception as exc:
        logger.warning("market_data_subscriber: failed to load credentials: %s", exc)
        return

    _market_data_subscriber = "initializing"
    bar_store = _live_bar_store

    def _connect_and_subscribe(sj_mod, on_tick_cb) -> Any:
        """Login, register tick callback, then subscribe to R1+R2 tick feeds.

        Callback is registered BEFORE subscribing so no early ticks are lost.
        Rolling contracts (R1/R2) have a logical code like "TMFR1" in their
        .code attribute, but ticks carry the physical contract code (e.g.
        "TMFE6"). We resolve the physical code by finding the underlying
        contract in the same group with matching delivery.
        """
        from src.data.contracts import CONTRACTS

        api = sj_mod.Shioaji(simulation=False)
        api.login(api_key=api_key, secret_key=secret_key)
        logger.info("market_data_subscriber: connected to Sinopac")

        # Register tick callback BEFORE subscribing to avoid losing early ticks
        api.quote.set_on_tick_fop_v1_callback(on_tick_cb)

        time.sleep(2)

        # Rebuild on every reconnect — contract codes change after settlement.
        _code_to_symbol.clear()

        for contract_def in CONTRACTS:
            try:
                obj = api.Contracts
                for part in contract_def.shioaji_path.split("."):
                    obj = getattr(obj, part)
                logical_code = getattr(obj, "code", None)
                if not logical_code:
                    logger.warning(
                        "market_data_subscriber: resolve failed for %s (path=%s)",
                        contract_def.db_symbol, contract_def.shioaji_path,
                    )
                    continue

                # Rolling contracts (R1/R2) return a logical code that differs
                # from the physical tick code. Resolve the physical code by
                # matching delivery_date within the contract group.
                physical_code = logical_code
                delivery = getattr(obj, "delivery_date", None)
                if delivery and logical_code.endswith(("R1", "R2")):
                    group = getattr(api.Contracts.Futures, contract_def.shioaji_group, None)
                    if group:
                        for c in group:
                            c_code = getattr(c, "code", "")
                            if c_code.endswith(("R1", "R2")):
                                continue
                            if getattr(c, "delivery_date", None) == delivery:
                                physical_code = c_code
                                break

                api.quote.subscribe(
                    obj,
                    quote_type=sj_mod.constant.QuoteType.Tick,
                    version=sj_mod.constant.QuoteVersion.v1,
                )
                _code_to_symbol[physical_code] = contract_def.db_symbol
                logger.info(
                    "market_data_subscriber: subscribed %s logical=%s physical=%s",
                    contract_def.db_symbol, logical_code, physical_code,
                )
            except Exception as exc:
                logger.warning(
                    "market_data_subscriber: subscribe failed for %s: %s",
                    contract_def.db_symbol, exc,
                )
        return api

    def _run_subscriber() -> None:
        global _market_data_subscriber, _subscriber_tick_count, _subscriber_last_tick_ts
        tick_loop = None

        # Track last tick timestamp for session boundary detection
        _last_tick_ts_for_session: datetime | None = None

        def _on_tick(exchange, tick) -> None:
            nonlocal tick_loop, _last_tick_ts_for_session
            global _subscriber_tick_count, _subscriber_last_tick_ts
            code = getattr(tick, "code", "")
            symbol = _code_to_symbol.get(code)
            if symbol is None:
                return  # not a subscribed contract
            price = float(getattr(tick, "close", 0))
            if price <= 0:
                return
            volume = int(getattr(tick, "volume", 0))

            raw_ts = getattr(tick, "datetime", None)
            if isinstance(raw_ts, datetime):
                tick_ts = raw_ts if raw_ts.tzinfo else raw_ts.replace(tzinfo=ZoneInfo("Asia/Taipei"))
            else:
                tick_ts = datetime.now(timezone.utc).astimezone(ZoneInfo("Asia/Taipei"))

            # Determine spread leg from db_symbol: TX→R1, TX_R2→R2.
            is_r2 = symbol.endswith("_R2")
            spread_symbol = symbol[:-3] if is_r2 else symbol
            leg_code = f"{spread_symbol}R2" if is_r2 else f"{spread_symbol}R1"

            # Tee both R1 and R2 legs to the per-symbol spread buffer.
            try:
                from src.data.spread_monitor import get_live_buffer
                from src.data.session_utils import is_new_session
                from src.api.ws.spread_feed import push_spread_tick, push_session_reset
                from src.api.main import get_main_loop

                spread_buffer = get_live_buffer(spread_symbol)
                if _last_tick_ts_for_session is not None and is_new_session(_last_tick_ts_for_session, tick_ts):
                    spread_buffer.reset_session()
                    loop = tick_loop
                    if not loop or loop.is_closed():
                        loop = get_main_loop()
                    if loop and loop.is_running():
                        asyncio.run_coroutine_threadsafe(push_session_reset(spread_buffer.symbol), loop)
                _last_tick_ts_for_session = tick_ts

                ts_ms = int(tick_ts.timestamp() * 1000)
                spread_tick = spread_buffer.on_tick(leg_code, price, ts_ms)
                if spread_tick is not None:
                    loop = tick_loop
                    if not loop or loop.is_closed():
                        loop = get_main_loop()
                        tick_loop = loop
                    if loop and loop.is_running():
                        asyncio.run_coroutine_threadsafe(push_spread_tick(spread_tick), loop)
            except Exception:
                pass  # don't let spread processing break main tick flow

            _subscriber_tick_count += 1
            _subscriber_last_tick_ts = tick_ts

            # Persist to ohlcv_bars under the exact symbol (R1 → TX, R2 → TX_R2).
            if bar_store is not None:
                try:
                    bar_store.ingest_tick(symbol, price, volume, tick_ts)
                except Exception:
                    pass

            # Live broadcast only for R1 (single-mode chart shows the front month).
            if not is_r2:
                try:
                    from src.api.ws.live_feed import push_tick
                    from src.api.main import get_main_loop
                    loop = tick_loop
                    if not loop or loop.is_closed():
                        loop = get_main_loop()
                        tick_loop = loop
                    if loop and loop.is_running():
                        asyncio.run_coroutine_threadsafe(push_tick(symbol, price, volume, tick_ts), loop)
                except Exception:
                    pass

        while True:
            try:
                api = _connect_and_subscribe(sj, _on_tick)
                _market_data_subscriber = api
                connected_at = datetime.now(timezone.utc).astimezone(ZoneInfo("Asia/Taipei"))
                logger.info("market_data_subscriber: health monitor started, codes=%s", list(_code_to_symbol.keys()))
                # Health monitor: check for tick stalls every 120s during trading hours
                while True:
                    time.sleep(120)
                    now_taipei = datetime.now(timezone.utc).astimezone(ZoneInfo("Asia/Taipei"))
                    h, m = now_taipei.hour, now_taipei.minute
                    mins = h * 60 + m
                    in_session = mins >= 15 * 60 or mins < 5 * 60 or (8 * 60 + 45 <= mins <= 13 * 60 + 45)
                    if not in_session:
                        continue
                    if _subscriber_last_tick_ts:
                        stale_secs = (now_taipei - _subscriber_last_tick_ts).total_seconds()
                        if stale_secs > 300:
                            logger.warning("market_data_subscriber: no ticks for %.0fs, reconnecting", stale_secs)
                            try:
                                api.logout()
                            except Exception:
                                pass
                            break
                    else:
                        # Never received any ticks since connection — reconnect
                        # after 5 minutes to avoid silent dead connections.
                        age_secs = (now_taipei - connected_at).total_seconds()
                        if age_secs > 300:
                            logger.warning("market_data_subscriber: zero ticks after %.0fs, reconnecting", age_secs)
                            try:
                                api.logout()
                            except Exception:
                                pass
                            break
            except Exception as exc:
                logger.warning("market_data_subscriber: error, reconnecting in 30s: %s", exc)
                _market_data_subscriber = "reconnecting"
                time.sleep(30)

    threading.Thread(target=_run_subscriber, daemon=True, name="market-data-subscriber").start()


def _init_telegram_dispatcher():
    """Create a Telegram dispatcher if credentials are configured."""
    try:
        from src.secrets.manager import get_secret_manager
        sm = get_secret_manager()
        bot_token = sm.get("TELEGRAM_BOT_TOKEN")
        chat_id = sm.get("TELEGRAM_CHAT_ID")
        if not bot_token or not chat_id:
            import structlog
            structlog.get_logger(__name__).info("telegram_not_configured")
            return None
        from src.alerting.dispatcher import NotificationDispatcher
        import structlog
        dispatcher = NotificationDispatcher(bot_token=bot_token, chat_id=chat_id)
        structlog.get_logger(__name__).info("telegram_dispatcher_ready", chat_id=chat_id[:4] + "...")
        return dispatcher
    except Exception:
        import structlog
        structlog.get_logger(__name__).warning("telegram_init_failed", exc_info=True)
        return None


def get_telegram_dispatcher():
    """Get the global Telegram dispatcher (may be None if not configured)."""
    _init_war_room()
    return _telegram_dispatcher


def _init_war_room() -> None:
    """Lazy-init the SessionManager, GatewayRegistry, and LivePipeline singletons."""
    global _session_manager, _gateway_registry, _account_equity_store
    global _live_bar_store, _live_pipeline, _portfolio_equity_store
    global _live_portfolio_store, _live_portfolio_manager
    if _gateway_registry is not None:
        return
    from src.broker_gateway.account_db import AccountDB
    from src.broker_gateway.live_bar_store import LiveMinuteBarStore
    from src.broker_gateway.registry import GatewayRegistry
    from src.execution.live_pipeline import LivePipelineManager
    from src.trading_session.manager import SessionManager
    from src.trading_session.session_db import SessionDB
    from src.trading_session.store import AccountEquityStore, PortfolioEquityStore, SnapshotStore
    db = AccountDB()
    _gateway_registry = GatewayRegistry(db=db)
    _gateway_registry.load_all()
    store = SnapshotStore()
    session_db = SessionDB()
    _session_manager = SessionManager(registry=_gateway_registry, store=store, session_db=session_db)
    _session_manager.restore_from_db()
    # Initialize LivePortfolio store + manager alongside SessionManager. The
    # portfolio manager runs on the same DB file as sessions and does not
    # touch the broker, so this is cheap at startup.
    from src.trading_session.live_portfolio_manager import LivePortfolioManager
    from src.trading_session.portfolio_db import LivePortfolioStore
    _live_portfolio_store = LivePortfolioStore()
    _live_portfolio_manager = LivePortfolioManager(
        store=_live_portfolio_store,
        session_manager=_session_manager,
    )
    _account_equity_store = AccountEquityStore()
    _portfolio_equity_store = PortfolioEquityStore()
    # Reuse the sinopac gateway's existing bar store as the shared store when
    # available. The gateway creates its own store at connect() time and pushes
    # live ticks into it; if the LivePipeline held a *different* store, strategy
    # runners never see completed bars (ticks dead-end in the gateway's private
    # store). Sharing the instance keeps the one-session-per-person_id shioaji
    # constraint intact — no separate market-data subscriber needed.
    _live_bar_store = None
    try:
        for _gw in _gateway_registry.list_accounts():
            _cand = _gateway_registry.get_gateway(_gw)
            _cand_store = getattr(_cand, "_live_bar_store", None)
            if _cand_store is not None:
                _live_bar_store = _cand_store
                break
    except Exception:
        _live_bar_store = None
    if _live_bar_store is None:
        _live_bar_store = LiveMinuteBarStore()
    # Seed mock accounts with synthetic equity history (idempotent).
    _warroom_seed_enabled = os.environ.get("QUANT_WARROOM_SEED") == "1"
    try:
        all_configs = db.load_all_accounts()
        for config in all_configs:
            if _warroom_seed_enabled and config.id == "mock-dev":
                continue
            if config.broker == "mock" and not _account_equity_store.has_history(config.id):
                _account_equity_store.seed_sandbox_equity(config.id)
    except Exception:
        pass
    # Initialize Telegram notification dispatcher
    global _telegram_dispatcher
    _telegram_dispatcher = _init_telegram_dispatcher()
    # Start the live execution pipeline (bar → signal → fill)
    _live_pipeline = LivePipelineManager(
        session_manager=_session_manager,
        bar_store=_live_bar_store,
        equity_store=_account_equity_store,
        notifier=_telegram_dispatcher,
        portfolio_equity_store=_portfolio_equity_store,
        portfolio_store=_live_portfolio_store,
    )
    try:
        from src.api.main import get_main_loop
        loop = get_main_loop()
    except Exception:
        loop = None
    _live_pipeline.start(loop=loop)
    # Start standalone market data subscriber for WebSocket live feed
    _start_market_data_subscriber()


def get_war_room_data() -> dict:
    """Fetch all data needed by the war room dashboard pages."""
    _init_war_room()
    assert _session_manager is not None
    assert _gateway_registry is not None
    assert _account_equity_store is not None
    try:
        _session_manager.poll_all()
    except Exception:
        pass
    # Load all accounts from DB so they always appear even if gateway failed to instantiate
    accounts: dict = {}
    try:
        from src.broker_gateway.account_db import AccountDB
        all_configs = AccountDB().load_all_accounts()
    except Exception:
        all_configs = _gateway_registry.get_all_configs()
    for config in all_configs:
        gw = _gateway_registry.get_gateway(config.id)
        snap = None
        if gw:
            try:
                snap = gw.get_account_snapshot()
            except Exception:
                snap = None
        # Account-level equity curve = the broker's real money. Record the
        # snapshot whenever we have a live one — sandbox flag no longer
        # matters here because per-portfolio paper equity now lives in
        # ``portfolio_equity_history`` (see PortfolioEquityStore).
        # Mock account: write a synthesized point that follows the same
        # contract used by the war-room route — `mock_initial + sum(live
        # runner pnl)` — so the chart matches the chip without depending
        # on the GBM walk inside MockGateway.
        if config.broker == "mock":
            try:
                mock_initial = float(getattr(gw, "_initial", 2_000_000.0)) if gw else 2_000_000.0
                runner_snaps = (
                    _live_pipeline.get_runner_snapshots()
                    if _live_pipeline is not None else {}
                )
                live_pnl = 0.0
                for rs in runner_snaps.values():
                    if rs.get("account_id") != config.id:
                        continue
                    sid = rs.get("session_id")
                    sess = _session_manager.get_session(sid) if sid else None
                    pid = getattr(sess, "portfolio_id", None) if sess else None
                    if not pid:
                        continue
                    portfolio = (
                        _live_portfolio_manager.get_portfolio(pid)
                        if _live_portfolio_manager is not None else None
                    )
                    if portfolio and portfolio.mode == "live":
                        live_pnl += float(rs.get("realized_pnl", 0.0) or 0.0)
                        live_pnl += float(rs.get("unrealized_pnl", 0.0) or 0.0)
                _account_equity_store.record(
                    config.id, mock_initial + live_pnl, margin_used=0.0,
                )
            except Exception:
                pass
        elif snap and snap.connected and snap.equity > 0:
            try:
                _account_equity_store.record(config.id, snap.equity, snap.margin_used)
            except Exception:
                pass
        equity_curve = []
        try:
            equity_curve = _account_equity_store.get_equity_curve(config.id, days=30)
        except Exception:
            pass
        connect_error = getattr(gw, "_connect_error", None) if gw else "Gateway not loaded"
        accounts[config.id] = {
            "config": config,
            "snapshot": snap,
            "equity_curve": equity_curve,
            "connect_error": connect_error,
        }
    sessions = _session_manager.get_all_sessions()
    sessions_by_account: dict[str, list] = {}
    for s in sessions:
        sessions_by_account.setdefault(s.account_id, []).append(s)
    # Per-portfolio paper equity curves (only paper portfolios write here;
    # live portfolios share the account-level curve via the broker snapshot).
    portfolio_equity_curves: dict[str, list[tuple]] = {}
    if _portfolio_equity_store is not None and _live_portfolio_store is not None:
        try:
            for p in _live_portfolio_store.load_all():
                portfolio_equity_curves[p.portfolio_id] = (
                    _portfolio_equity_store.get_equity_curve(p.portfolio_id, days=30)
                )
        except Exception:
            pass
    return {
        "accounts": accounts,
        "all_sessions": sessions,
        "sessions_by_account": sessions_by_account,
        "portfolio_equity_curves": portfolio_equity_curves,
    }


def get_gateway_registry():
    _init_war_room()
    return _gateway_registry


def get_session_manager():
    _init_war_room()
    return _session_manager


def get_live_portfolio_manager():
    _init_war_room()
    return _live_portfolio_manager


def get_live_pipeline():
    _init_war_room()
    return _live_pipeline


def sync_live_pipeline() -> None:
    """Re-sync live pipeline runners after session state changes."""
    if _live_pipeline is not None:
        _live_pipeline.sync()
