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
from datetime import date, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

_DB_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "taifex_data.db"

# ── TAIFEX Futures Continuous Contract Registry ─────────────────────────────
# Maps (display_name) -> (db_symbol, shioaji_contract_path)
@dataclass
class FuturesContract:
    display: str
    db_symbol: str
    shioaji_path: str
    description: str


FUTURES_CONTRACTS: list[FuturesContract] = [
    FuturesContract("TX (TAIEX)", "TX", "Futures.TXF.TXFR1", "台指期 · 大台"),
    FuturesContract("MTX (Mini-TAIEX)", "MTX", "Futures.MXF.MXFR1", "小台指期 · 小台"),
    FuturesContract("TMF (10Y Bond)", "TMF", "Futures.T5F.T5FR1", "十年期公債期貨"),
    FuturesContract("TE (Electronics)", "TE", "Futures.TEF.TEFR1", "電子期貨"),
    FuturesContract("TF (Finance)", "TF", "Futures.TFF.TFFR1", "金融期貨"),
    FuturesContract("XIF (Non-Fin/Elec)", "XIF", "Futures.XIF.XIFR1", "非金電期貨"),
    FuturesContract("GTF (OTC 200)", "GTF", "Futures.GTF.GTFR1", "櫃買期貨"),
    FuturesContract("G2F (OTC Biotech)", "G2F", "Futures.G2F.G2FR1", "櫃買富櫃200期貨"),
    FuturesContract("RHF (USD/TWD FX)", "RHF", "Futures.RHF.RHFR1", "美元兌台幣匯率期貨"),
    FuturesContract("GDF (Gold)", "GDF", "Futures.GDF.GDFR1", "黃金期貨"),
    FuturesContract("BTF (Brent Oil)", "BTF", "Futures.BTF.BTFR1", "布蘭特原油期貨"),
    FuturesContract("SPF (S&P 500)", "SPF", "Futures.SPF.SPFR1", "美國標普500期貨"),
    FuturesContract("UNF (DJIA)", "UNF", "Futures.UNF.UNFR1", "美國道瓊期貨"),
    FuturesContract("UDF (Nasdaq 100)", "UDF", "Futures.UDF.UDFR1", "那斯達克100期貨"),
    FuturesContract("F1F (Phila Semi)", "F1F", "Futures.F1F.F1FR1", "費城半導體期貨"),
]

FUTURES_BY_SYMBOL: dict[str, FuturesContract] = {c.db_symbol: c for c in FUTURES_CONTRACTS}

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
    ts = datetime.now().strftime("%H:%M:%S")
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
    contract = FUTURES_BY_SYMBOL.get(db_symbol)
    if not contract:
        with _crawl_lock:
            _crawl_state.error = f"Unknown symbol: {db_symbol}"
            _crawl_state.running = False
            _crawl_state.finished = True
        return

    _crawl_log(f"Crawl started: {contract.display} ({contract.shioaji_path})")
    _crawl_log(f"Date range: {start_str} to {end_str}")

    try:
        from src.data.crawl import crawl_historical
        from src.data.db import Database

        _crawl_log("Connecting to Sinopac API...")
        with _crawl_lock:
            _crawl_state.progress = "Logging in to Sinopac..."

        from src.pipeline.config import create_sinopac_connector
        connector = create_sinopac_connector()
        _crawl_log("Login successful ✓")

        db = Database(f"sqlite:///{_DB_PATH}")
        start_date = date.fromisoformat(start_str)
        end_date = date.fromisoformat(end_str)

        with _crawl_lock:
            _crawl_state.progress = f"Fetching {contract.db_symbol} 1-min bars..."
        _crawl_log(f"Fetching 1-min kbars for {contract.shioaji_path} → DB symbol: {contract.db_symbol}")

        total = crawl_historical(
            symbol=contract.shioaji_path,
            start=start_date,
            end=end_date,
            db=db,
            connector=connector,
            db_symbol=contract.db_symbol,
        )
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
    module: str        # e.g. "src.strategies.atr_mean_reversion"
    factory: str       # e.g. "create_atr_mean_reversion_engine"
    param_grid: dict[str, dict] | None = None


def discover_strategies() -> dict[str, StrategyInfo]:
    """Discover strategies via the central registry."""
    from src.strategies.registry import get_all, get_param_grid
    result: dict[str, StrategyInfo] = {}
    for slug, reg_info in get_all().items():
        grid = get_param_grid(slug)
        result[slug] = StrategyInfo(
            name=reg_info.name, module=reg_info.module,
            factory=reg_info.factory, param_grid=grid or None,
        )
    return result


STRATEGY_REGISTRY: dict[str, StrategyInfo] = discover_strategies()


def get_param_grid_for_strategy(slug: str) -> dict[str, dict]:
    """Return the optimizer param grid for a strategy from the central registry."""
    from src.strategies.registry import get_param_grid
    try:
        return get_param_grid(slug)
    except KeyError:
        info = STRATEGY_REGISTRY.get(slug)
        return info.param_grid or {} if info else {}

# Objectives available in the optimizer (maps display label → metric key)
OPT_OBJECTIVES: list[dict[str, str]] = [
    {"label": "Sharpe Ratio", "value": "sharpe"},
    {"label": "Profit Factor", "value": "profit_factor"},
    {"label": "Calmar Ratio", "value": "calmar"},
    {"label": "Win Rate", "value": "win_rate"},
    {"label": "Sortino Ratio", "value": "sortino"},
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
                obj = data.get("objective", "sharpe")
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
    conn = sqlite3.connect(str(_DB_PATH))
    try:
        if tf_minutes <= 1:
            query = (
                "SELECT timestamp, open, high, low, close, volume "
                "FROM ohlcv_bars WHERE symbol = ? AND timestamp >= ? AND timestamp <= ? "
                "ORDER BY timestamp"
            )
            df = pd.read_sql_query(
                query, conn,
                params=(symbol, start.isoformat(), end.isoformat()),
                parse_dates=["timestamp"],
            )
        else:
            # Aggregate in SQL: bucket = floor(unix_ts / bucket_secs)
            bucket_secs = tf_minutes * 60
            query = """
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
                    "ts_start": start.isoformat(),
                    "ts_end": end.isoformat(),
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
    max_loss: float = 100_000.0,
) -> dict:
    """Run a backtest on real DB data via the MCP facade.

    Delegates to run_backtest_realdata_for_mcp so the dashboard and MCP
    tool produce identical results for the same inputs.

    Returns dict with keys: daily_returns (np.ndarray), equity_curve (list),
    bnh_returns (np.ndarray), bnh_equity (list), metrics (dict), bars_count (int).
    """
    from src.mcp_server.facade import run_backtest_realdata_for_mcp

    info = STRATEGY_REGISTRY.get(strategy_slug)
    if not info:
        raise ValueError(f"Unknown strategy: {strategy_slug}")
    facade_name = strategy_slug

    merged_params = dict(strategy_params or {})
    merged_params["max_loss"] = max_loss

    result = run_backtest_realdata_for_mcp(
        symbol=symbol,
        start=start_str,
        end=end_str,
        strategy=facade_name,
        strategy_params=merged_params,
        initial_equity=initial_equity,
    )
    if "error" in result:
        raise ValueError(result["error"])
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


def _init_war_room() -> None:
    """Lazy-init the SessionManager and GatewayRegistry singletons."""
    global _session_manager, _gateway_registry, _account_equity_store
    if _gateway_registry is not None:
        return
    from src.broker_gateway.account_db import AccountDB
    from src.broker_gateway.registry import GatewayRegistry
    from src.trading_session.manager import SessionManager
    from src.trading_session.store import AccountEquityStore, SnapshotStore
    db = AccountDB()
    _gateway_registry = GatewayRegistry(db=db)
    _gateway_registry.load_all()
    store = SnapshotStore()
    _session_manager = SessionManager(registry=_gateway_registry, store=store)
    _session_manager.restore_from_config()
    _account_equity_store = AccountEquityStore()


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
        # Record equity for the curve whenever we have a live snapshot
        if snap and snap.connected and snap.equity > 0:
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
    return {
        "accounts": accounts,
        "all_sessions": sessions,
        "sessions_by_account": sessions_by_account,
    }


def get_gateway_registry():
    _init_war_room()
    return _gateway_registry


def get_session_manager():
    _init_war_room()
    return _session_manager
