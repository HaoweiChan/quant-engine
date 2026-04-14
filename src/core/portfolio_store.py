"""SQLite-backed store for portfolio optimization results.

Persists optimization runs so allocation decisions are traceable
and results can be compared across time periods.
"""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

_TAIPEI_TZ = timezone(timedelta(hours=8))
_DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "portfolio_opt.db"

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS portfolio_runs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    run_at          TEXT NOT NULL,
    symbol          TEXT NOT NULL,
    start_date      TEXT NOT NULL,
    end_date        TEXT NOT NULL,
    initial_capital REAL NOT NULL,
    min_weight      REAL NOT NULL,
    n_strategies    INTEGER NOT NULL,
    strategy_slugs  TEXT NOT NULL,
    n_days          INTEGER NOT NULL,
    correlation_json TEXT NOT NULL,
    notes           TEXT
);

CREATE TABLE IF NOT EXISTS portfolio_allocations (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id          INTEGER NOT NULL REFERENCES portfolio_runs(id),
    objective       TEXT NOT NULL,
    weights_json    TEXT NOT NULL,
    sharpe          REAL,
    total_return    REAL,
    annual_return   REAL,
    max_drawdown_pct REAL,
    sortino         REAL,
    calmar          REAL,
    annual_vol      REAL,
    is_selected     INTEGER NOT NULL DEFAULT 0,
    selected_at     TEXT
);

CREATE TABLE IF NOT EXISTS portfolio_stress_tests (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id          INTEGER NOT NULL REFERENCES portfolio_runs(id),
    allocation_id   INTEGER REFERENCES portfolio_allocations(id),
    tested_at       TEXT NOT NULL,
    method          TEXT NOT NULL,
    n_paths         INTEGER NOT NULL,
    n_days_forward  INTEGER NOT NULL,
    var_95          REAL,
    var_99          REAL,
    cvar_95         REAL,
    cvar_99         REAL,
    median_final    REAL,
    prob_ruin       REAL,
    p5_final        REAL,
    p25_final       REAL,
    p50_final       REAL,
    p75_final       REAL,
    p95_final       REAL
);

CREATE INDEX IF NOT EXISTS idx_port_runs_symbol ON portfolio_runs(symbol);
CREATE INDEX IF NOT EXISTS idx_port_alloc_run ON portfolio_allocations(run_id);
CREATE INDEX IF NOT EXISTS idx_port_alloc_selected ON portfolio_allocations(is_selected);
CREATE INDEX IF NOT EXISTS idx_port_stress_run ON portfolio_stress_tests(run_id);
"""


class PortfolioStore:
    """Persist and query portfolio optimization results."""

    def __init__(self, db_path: Path | None = None) -> None:
        env_path = os.environ.get("PORTFOLIO_OPT_DB")
        if db_path is not None:
            self._db_path = db_path
        elif env_path:
            self._db_path = Path(env_path)
        else:
            self._db_path = _DEFAULT_DB_PATH
        self._conn = sqlite3.connect(str(self._db_path))
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA_SQL)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def save_optimization(
        self,
        result: dict[str, Any],
        symbol: str,
        start: str,
        end: str,
        initial_capital: float,
        min_weight: float,
        notes: str | None = None,
    ) -> int:
        """Save a full optimization result. Returns the run_id."""
        now = datetime.now(_TAIPEI_TZ).isoformat()
        slugs = result["strategy_slugs"]
        cur = self._conn.execute(
            """INSERT INTO portfolio_runs
               (run_at, symbol, start_date, end_date, initial_capital, min_weight,
                n_strategies, strategy_slugs, n_days, correlation_json, notes)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                now, symbol, start, end, initial_capital, min_weight,
                len(slugs), json.dumps(slugs), result["n_days"],
                json.dumps(result["correlation_matrix"]), notes,
            ),
        )
        run_id = cur.lastrowid
        for obj_key in ["max_sharpe", "max_return", "min_drawdown", "risk_parity", "equal_weight"]:
            alloc = result[obj_key]
            self._conn.execute(
                """INSERT INTO portfolio_allocations
                   (run_id, objective, weights_json, sharpe, total_return,
                    annual_return, max_drawdown_pct, sortino, calmar, annual_vol)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    run_id, alloc["objective"], json.dumps(alloc["weights"]),
                    alloc["sharpe"], alloc["total_return"], alloc["annual_return"],
                    alloc["max_drawdown_pct"], alloc["sortino"], alloc["calmar"],
                    alloc["annual_vol"],
                ),
            )
        self._conn.commit()
        logger.info("portfolio_optimization_saved", run_id=run_id, n_strategies=len(slugs))
        return run_id

    def save_stress_test(
        self,
        run_id: int,
        allocation_objective: str,
        stress_result: dict[str, Any],
    ) -> int:
        """Save a stress test result linked to a run and allocation."""
        now = datetime.now(_TAIPEI_TZ).isoformat()
        # Find the allocation_id for this objective
        row = self._conn.execute(
            "SELECT id FROM portfolio_allocations WHERE run_id=? AND objective=?",
            (run_id, allocation_objective),
        ).fetchone()
        alloc_id = row["id"] if row else None
        cur = self._conn.execute(
            """INSERT INTO portfolio_stress_tests
               (run_id, allocation_id, tested_at, method, n_paths, n_days_forward,
                var_95, var_99, cvar_95, cvar_99, median_final, prob_ruin,
                p5_final, p25_final, p50_final, p75_final, p95_final)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                run_id, alloc_id, now,
                stress_result.get("method", "stationary"),
                stress_result.get("n_paths", 0),
                stress_result.get("n_days_forward", 0),
                stress_result.get("var_95"),
                stress_result.get("var_99"),
                stress_result.get("cvar_95"),
                stress_result.get("cvar_99"),
                stress_result.get("median_final"),
                stress_result.get("prob_ruin"),
                stress_result.get("p5_final"),
                stress_result.get("p25_final"),
                stress_result.get("p50_final"),
                stress_result.get("p75_final"),
                stress_result.get("p95_final"),
            ),
        )
        self._conn.commit()
        return cur.lastrowid

    def select_allocation(self, run_id: int, objective: str) -> bool:
        """Mark an allocation as the selected/active one for a run.

        Deactivates any previously selected allocation for the same run.
        """
        now = datetime.now(_TAIPEI_TZ).isoformat()
        self._conn.execute(
            "UPDATE portfolio_allocations SET is_selected=0 WHERE run_id=?",
            (run_id,),
        )
        cur = self._conn.execute(
            "UPDATE portfolio_allocations SET is_selected=1, selected_at=? WHERE run_id=? AND objective=?",
            (now, run_id, objective),
        )
        self._conn.commit()
        return cur.rowcount > 0

    def get_latest_run(self, symbol: str = "TX") -> dict[str, Any] | None:
        """Get the most recent optimization run for a symbol."""
        row = self._conn.execute(
            "SELECT * FROM portfolio_runs WHERE symbol=? ORDER BY id DESC LIMIT 1",
            (symbol,),
        ).fetchone()
        if not row:
            return None
        return self._run_to_dict(row)

    def get_run(self, run_id: int) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM portfolio_runs WHERE id=?", (run_id,),
        ).fetchone()
        if not row:
            return None
        return self._run_to_dict(row)

    def get_selected_allocation(self, run_id: int) -> dict[str, Any] | None:
        """Get the selected allocation for a run."""
        row = self._conn.execute(
            "SELECT * FROM portfolio_allocations WHERE run_id=? AND is_selected=1",
            (run_id,),
        ).fetchone()
        if not row:
            return None
        d = dict(row)
        d["weights"] = json.loads(d.pop("weights_json"))
        return d

    def list_runs(self, symbol: str | None = None, limit: int = 10) -> list[dict[str, Any]]:
        if symbol:
            rows = self._conn.execute(
                "SELECT * FROM portfolio_runs WHERE symbol=? ORDER BY id DESC LIMIT ?",
                (symbol, limit),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM portfolio_runs ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [self._run_to_dict(r) for r in rows]

    def _run_to_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        run = dict(row)
        run["strategy_slugs"] = json.loads(run["strategy_slugs"])
        run["correlation_matrix"] = json.loads(run["correlation_json"])
        del run["correlation_json"]
        # Attach allocations
        allocs = self._conn.execute(
            "SELECT * FROM portfolio_allocations WHERE run_id=?", (run["id"],),
        ).fetchall()
        run["allocations"] = {a["objective"]: dict(a) for a in allocs}
        for a in run["allocations"].values():
            a["weights"] = json.loads(a["weights_json"])
            del a["weights_json"]
        # Attach stress tests
        stresses = self._conn.execute(
            "SELECT * FROM portfolio_stress_tests WHERE run_id=?", (run["id"],),
        ).fetchall()
        run["stress_tests"] = [dict(s) for s in stresses]
        return run
