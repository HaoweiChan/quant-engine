"""SQLite-backed store for portfolio optimization results.

Persists optimization runs so allocation decisions are traceable
and results can be compared across time periods.
"""
from __future__ import annotations

import hashlib
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

CREATE TABLE IF NOT EXISTS portfolio_walk_forward_runs (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id                  INTEGER REFERENCES portfolio_runs(id),
    ran_at                  TEXT NOT NULL,
    symbol                  TEXT NOT NULL,
    start_date              TEXT NOT NULL,
    end_date                TEXT NOT NULL,
    n_folds                 INTEGER NOT NULL,
    oos_fraction            REAL NOT NULL,
    objective               TEXT NOT NULL,
    strategy_slugs          TEXT NOT NULL,
    n_folds_computed        INTEGER NOT NULL,
    aggregate_oos_sharpe    REAL NOT NULL,
    aggregate_oos_mdd       REAL NOT NULL,
    worst_fold_oos_mdd      REAL NOT NULL,
    weight_drift_cv         REAL NOT NULL,
    correlation_stability   REAL NOT NULL,
    thresholds_applied_json TEXT,
    per_fold_json           TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_port_runs_symbol ON portfolio_runs(symbol);
CREATE INDEX IF NOT EXISTS idx_port_alloc_run ON portfolio_allocations(run_id);
CREATE INDEX IF NOT EXISTS idx_port_alloc_selected ON portfolio_allocations(is_selected);
CREATE INDEX IF NOT EXISTS idx_port_stress_run ON portfolio_stress_tests(run_id);
CREATE INDEX IF NOT EXISTS idx_port_wf_run ON portfolio_walk_forward_runs(run_id);
CREATE INDEX IF NOT EXISTS idx_port_wf_symbol ON portfolio_walk_forward_runs(symbol);
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
        self._migrate_content_hash()
        self._migrate_cost_columns()
        self._conn.commit()

    def _migrate_content_hash(self) -> None:
        """Add content_hash column if missing, backfill existing rows, purge dupes."""
        cols = {
            r[1]
            for r in self._conn.execute("PRAGMA table_info(portfolio_allocations)")
        }
        if "content_hash" in cols:
            return
        self._conn.execute(
            "ALTER TABLE portfolio_allocations ADD COLUMN content_hash TEXT"
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_port_alloc_hash "
            "ON portfolio_allocations(content_hash)"
        )
        rows = self._conn.execute(
            "SELECT pa.id, pa.objective, pa.weights_json, pr.symbol, "
            "pr.start_date, pr.end_date "
            "FROM portfolio_allocations pa "
            "JOIN portfolio_runs pr ON pr.id = pa.run_id"
        ).fetchall()
        for r in rows:
            h = self._allocation_hash(
                r["objective"], r["symbol"],
                r["start_date"], r["end_date"], r["weights_json"],
            )
            self._conn.execute(
                "UPDATE portfolio_allocations SET content_hash=? WHERE id=?",
                (h, r["id"]),
            )
        self._purge_duplicates()
        self._conn.commit()
        logger.info("portfolio_content_hash_migrated", rows=len(rows))

    def _migrate_cost_columns(self) -> None:
        """Add slippage/commission columns to portfolio_runs if missing."""
        cols = {
            r[1]
            for r in self._conn.execute("PRAGMA table_info(portfolio_runs)")
        }
        added = []
        for col in ("slippage_bps", "commission_bps", "commission_fixed_per_contract"):
            if col not in cols:
                self._conn.execute(
                    f"ALTER TABLE portfolio_runs ADD COLUMN {col} REAL NOT NULL DEFAULT 0.0"
                )
                added.append(col)
        if added:
            self._conn.commit()
            logger.info("portfolio_cost_columns_migrated", added=added)

    @staticmethod
    def _allocation_hash(
        objective: str, symbol: str, start: str, end: str, weights_json: str,
    ) -> str:
        """Stable hash for deduplication based on meaningful fields."""
        canonical = json.dumps(
            json.loads(weights_json), sort_keys=True, separators=(",", ":"),
        )
        payload = f"{objective}|{symbol}|{start}|{end}|{canonical}"
        return hashlib.sha256(payload.encode()).hexdigest()[:16]

    def _purge_duplicates(self) -> None:
        """Remove duplicate allocations, keeping the earliest (lowest id)."""
        dupes = self._conn.execute(
            "SELECT content_hash, MIN(id) AS keep_id, COUNT(*) AS cnt "
            "FROM portfolio_allocations "
            "WHERE content_hash IS NOT NULL "
            "GROUP BY content_hash HAVING cnt > 1"
        ).fetchall()
        removed = 0
        for d in dupes:
            cur = self._conn.execute(
                "DELETE FROM portfolio_allocations "
                "WHERE content_hash=? AND id != ?",
                (d["content_hash"], d["keep_id"]),
            )
            removed += cur.rowcount
        if removed:
            logger.info("portfolio_duplicates_purged", removed=removed)
        orphans = self._conn.execute(
            "DELETE FROM portfolio_runs WHERE id NOT IN "
            "(SELECT DISTINCT run_id FROM portfolio_allocations)"
        )
        if orphans.rowcount:
            logger.info("portfolio_orphan_runs_purged", removed=orphans.rowcount)

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
        slippage_bps: float = 0.0,
        commission_bps: float = 0.0,
        commission_fixed_per_contract: float = 0.0,
    ) -> int:
        """Save a full optimization result. Returns the run_id.

        Skips individual allocations that already exist (same hash).
        """
        now = datetime.now(_TAIPEI_TZ).isoformat()
        slugs = result["strategy_slugs"]
        cur = self._conn.execute(
            """INSERT INTO portfolio_runs
               (run_at, symbol, start_date, end_date, initial_capital, min_weight,
                n_strategies, strategy_slugs, n_days, correlation_json, notes,
                slippage_bps, commission_bps, commission_fixed_per_contract)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                now, symbol, start, end, initial_capital, min_weight,
                len(slugs), json.dumps(slugs), result["n_days"],
                json.dumps(result["correlation_matrix"]), notes,
                slippage_bps, commission_bps, commission_fixed_per_contract,
            ),
        )
        run_id = cur.lastrowid
        saved = 0
        skipped = 0
        for obj_key in ["max_sharpe", "max_return", "min_drawdown", "risk_parity", "equal_weight"]:
            alloc = result[obj_key]
            wj = json.dumps(alloc["weights"])
            h = self._allocation_hash(alloc["objective"], symbol, start, end, wj)
            existing = self._conn.execute(
                "SELECT id FROM portfolio_allocations WHERE content_hash=?", (h,),
            ).fetchone()
            if existing:
                skipped += 1
                continue
            self._conn.execute(
                """INSERT INTO portfolio_allocations
                   (run_id, objective, weights_json, sharpe, total_return,
                    annual_return, max_drawdown_pct, sortino, calmar, annual_vol,
                    content_hash)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    run_id, alloc["objective"], wj,
                    alloc["sharpe"], alloc["total_return"], alloc["annual_return"],
                    alloc["max_drawdown_pct"], alloc["sortino"], alloc["calmar"],
                    alloc["annual_vol"], h,
                ),
            )
            saved += 1
        self._conn.commit()
        logger.info(
            "portfolio_optimization_saved",
            run_id=run_id, n_strategies=len(slugs), saved=saved, skipped=skipped,
        )
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

    def save_walk_forward(
        self,
        result: dict[str, Any],
        symbol: str,
        start: str,
        end: str,
        n_folds: int,
        oos_fraction: float,
        run_id: int | None = None,
    ) -> int:
        """Persist a portfolio walk-forward result.

        ``result`` must be the ``as_dict()`` output of
        ``PortfolioWalkForwardResult``. ``run_id`` is an optional foreign
        key back to ``portfolio_runs`` — pass it when the walk-forward
        used the same strategies + params as an optimization run.
        """
        now = datetime.now(_TAIPEI_TZ).isoformat()
        cur = self._conn.execute(
            """INSERT INTO portfolio_walk_forward_runs
               (run_id, ran_at, symbol, start_date, end_date,
                n_folds, oos_fraction, objective, strategy_slugs,
                n_folds_computed, aggregate_oos_sharpe, aggregate_oos_mdd,
                worst_fold_oos_mdd, weight_drift_cv, correlation_stability,
                thresholds_applied_json, per_fold_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                run_id, now, symbol, start, end,
                n_folds, oos_fraction,
                result.get("objective", "max_sharpe"),
                json.dumps(result["strategy_slugs"]),
                result.get("n_folds_computed", 0),
                result["aggregate_oos_sharpe"],
                result["aggregate_oos_mdd"],
                result["worst_fold_oos_mdd"],
                result["weight_drift_cv"],
                result["correlation_stability"],
                json.dumps(result.get("thresholds_applied", {})),
                json.dumps(result.get("per_fold", [])),
            ),
        )
        self._conn.commit()
        wf_id = cur.lastrowid
        logger.info(
            "portfolio_walk_forward_saved",
            wf_id=wf_id,
            run_id=run_id,
            oos_sharpe=result["aggregate_oos_sharpe"],
            n_folds=result.get("n_folds_computed", 0),
        )
        return wf_id

    def get_walk_forward(self, wf_id: int) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM portfolio_walk_forward_runs WHERE id=?", (wf_id,),
        ).fetchone()
        if not row:
            return None
        d = dict(row)
        d["strategy_slugs"] = json.loads(d.pop("strategy_slugs"))
        d["thresholds_applied"] = json.loads(d.pop("thresholds_applied_json") or "{}")
        d["per_fold"] = json.loads(d.pop("per_fold_json"))
        return d

    def list_walk_forwards(
        self,
        run_id: int | None = None,
        symbol: str | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        params: list[Any] = []
        where: list[str] = []
        if run_id is not None:
            where.append("run_id=?")
            params.append(run_id)
        if symbol:
            where.append("symbol=?")
            params.append(symbol)
        sql = "SELECT * FROM portfolio_walk_forward_runs"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        rows = self._conn.execute(sql, params).fetchall()
        out: list[dict[str, Any]] = []
        for r in rows:
            d = dict(r)
            d["strategy_slugs"] = json.loads(d.pop("strategy_slugs"))
            d["thresholds_applied"] = json.loads(
                d.pop("thresholds_applied_json") or "{}",
            )
            d["per_fold"] = json.loads(d.pop("per_fold_json"))
            out.append(d)
        return out

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
            "UPDATE portfolio_allocations "
            "SET is_selected=1, selected_at=? "
            "WHERE run_id=? AND objective=?",
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

    def get_active_seed_config(self) -> list[dict[str, Any]] | None:
        """Return the seeder config from the most recently selected allocation.

        Looks for any allocation with ``is_selected=1``, ordered by most
        recently selected. Returns a list of dicts with keys
        ``slug``, ``weight``, ``symbol``, suitable for the warroom seeder.
        Returns ``None`` when no allocation has been selected.
        """
        row = self._conn.execute(
            """
            SELECT pa.weights_json, pr.symbol, pr.strategy_slugs
            FROM portfolio_allocations pa
            JOIN portfolio_runs pr ON pr.id = pa.run_id
            WHERE pa.is_selected = 1
            ORDER BY pa.selected_at DESC
            LIMIT 1
            """,
        ).fetchone()
        if not row:
            return None
        weights = json.loads(row["weights_json"])
        symbol = row["symbol"]
        return [
            {"slug": slug, "weight": w, "symbol": symbol}
            for slug, w in weights.items()
        ]

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
        # Attach walk-forward runs (ids + aggregate metrics only, avoid
        # bloating the payload with per-fold JSON).
        wf_rows = self._conn.execute(
            """SELECT id, ran_at, objective, n_folds_computed,
                      aggregate_oos_sharpe, worst_fold_oos_mdd,
                      weight_drift_cv, correlation_stability
               FROM portfolio_walk_forward_runs WHERE run_id=?""",
            (run["id"],),
        ).fetchall()
        run["walk_forwards"] = [dict(r) for r in wf_rows]
        return run
