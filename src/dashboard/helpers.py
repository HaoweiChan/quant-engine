"""Computation helpers for the dashboard (no Dash dependencies)."""
from __future__ import annotations

import io
import sqlite3
import threading
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

_DB_PATH = Path(__file__).resolve().parent.parent.parent / "taifex_data.db"

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
def get_db_coverage() -> list[dict]:
    """Return per-symbol coverage stats from the database."""
    if not _DB_PATH.exists():
        return []
    try:
        with sqlite3.connect(str(_DB_PATH)) as conn:
            rows = conn.execute(
                "SELECT symbol, COUNT(*), MIN(timestamp), MAX(timestamp) "
                "FROM ohlcv_bars GROUP BY symbol ORDER BY symbol"
            ).fetchall()
        return [
            {"symbol": r[0], "bars": r[1], "from": r[2], "to": r[3]}
            for r in rows
        ]
    except Exception:
        return []


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
    """Load 1-min OHLCV bars from SQLite and aggregate to the requested timeframe."""
    if not _DB_PATH.exists():
        return pd.DataFrame()
    conn = sqlite3.connect(str(_DB_PATH))
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
    conn.close()
    if df.empty or tf_minutes <= 1:
        return df
    df = df.set_index("timestamp")
    agg = df.resample(f"{tf_minutes}min").agg({
        "open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum",
    }).dropna(subset=["open"])
    return agg.reset_index()


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
