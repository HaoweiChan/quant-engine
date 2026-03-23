"""SQLite-backed parameter registry for optimization runs, trials, and candidates.

Replaces the single-TOML approach with append-only versioning, Pareto frontier
extraction, and an explicit is_active flag for production param selection.
"""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import structlog

from src.simulator.types import OptimizerResult

logger = structlog.get_logger(__name__)

_DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "param_registry.db"
_DEFAULT_PARETO_OBJECTIVES = ["sharpe", "calmar"]
_METRIC_COLS = [
    "sharpe", "calmar", "sortino", "profit_factor",
    "win_rate", "max_drawdown_pct", "trade_count", "total_pnl",
]
_LARGE_TRIAL_THRESHOLD = 5000

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS param_runs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    run_at       TEXT NOT NULL,
    strategy     TEXT NOT NULL,
    symbol       TEXT NOT NULL,
    train_start  TEXT,
    train_end    TEXT,
    test_start   TEXT,
    test_end     TEXT,
    objective    TEXT NOT NULL,
    is_fraction  REAL,
    n_trials     INTEGER NOT NULL,
    search_type  TEXT NOT NULL,
    source       TEXT NOT NULL,
    tag          TEXT,
    notes        TEXT
);

CREATE TABLE IF NOT EXISTS param_trials (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id       INTEGER NOT NULL REFERENCES param_runs(id),
    params       TEXT NOT NULL,
    sharpe       REAL,
    calmar       REAL,
    sortino      REAL,
    profit_factor REAL,
    win_rate     REAL,
    max_drawdown_pct REAL,
    trade_count  INTEGER,
    total_pnl    REAL,
    is_oos       INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS param_candidates (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id       INTEGER NOT NULL REFERENCES param_runs(id),
    trial_id     INTEGER REFERENCES param_trials(id),
    strategy     TEXT NOT NULL,
    params       TEXT NOT NULL,
    label        TEXT NOT NULL,
    regime       TEXT,
    is_active    INTEGER NOT NULL DEFAULT 0,
    activated_at TEXT,
    notes        TEXT
);

CREATE INDEX IF NOT EXISTS idx_runs_strategy ON param_runs(strategy);
CREATE INDEX IF NOT EXISTS idx_trials_run ON param_trials(run_id);
CREATE INDEX IF NOT EXISTS idx_candidates_strategy ON param_candidates(strategy);
CREATE INDEX IF NOT EXISTS idx_candidates_active ON param_candidates(strategy, is_active);
"""


class ParamRegistry:
    """Persistent registry for optimization runs, trials, and active param sets."""

    def __init__(self, db_path: Path | None = None) -> None:
        env_path = os.environ.get("PARAM_REGISTRY_DB")
        if db_path is not None:
            self._db_path = db_path
        elif env_path:
            self._db_path = Path(env_path)
        else:
            self._db_path = _DEFAULT_DB_PATH
        self._conn = sqlite3.connect(str(self._db_path))
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._ensure_tables()

    def _ensure_tables(self) -> None:
        self._conn.executescript(_SCHEMA_SQL)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    # -- save_run ---------------------------------------------------------

    def save_run(
        self,
        result: OptimizerResult,
        strategy: str,
        symbol: str,
        objective: str,
        train_start: str | None = None,
        train_end: str | None = None,
        test_start: str | None = None,
        test_end: str | None = None,
        is_fraction: float = 0.8,
        search_type: str = "grid",
        source: str = "cli",
        tag: str | None = None,
        notes: str | None = None,
    ) -> int:
        """Persist a full OptimizerResult. Returns the run_id."""
        trials_dicts = result.trials.to_dicts() if len(result.trials) > 0 else []
        now = datetime.now(UTC).isoformat(timespec="seconds")
        cur = self._conn.execute(
            """INSERT INTO param_runs
               (run_at, strategy, symbol, train_start, train_end, test_start, test_end,
                objective, is_fraction, n_trials, search_type, source, tag, notes)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (now, strategy, symbol, train_start, train_end, test_start, test_end,
             objective, is_fraction, len(trials_dicts), search_type, source, tag, notes),
        )
        run_id = cur.lastrowid
        assert run_id is not None
        param_keys = [k for k in (trials_dicts[0].keys() if trials_dicts else [])
                      if k not in _METRIC_COLS and not k.startswith("_")]
        for row in trials_dicts:
            params_json = json.dumps({k: row[k] for k in param_keys if k in row})
            self._conn.execute(
                """INSERT INTO param_trials
                   (run_id, params, sharpe, calmar, sortino, profit_factor,
                    win_rate, max_drawdown_pct, trade_count, total_pnl, is_oos)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)""",
                (run_id, params_json,
                 row.get("sharpe"), row.get("calmar"), row.get("sortino"),
                 row.get("profit_factor"), row.get("win_rate"),
                 row.get("max_drawdown_pct"),
                 int(row.get("trade_count") or row.get("_trade_count") or 0),
                 row.get("total_pnl")),
            )
        # OOS best result
        if result.best_oos_result:
            m = result.best_oos_result.metrics
            self._conn.execute(
                """INSERT INTO param_trials
                   (run_id, params, sharpe, calmar, sortino, profit_factor,
                    win_rate, max_drawdown_pct, trade_count, total_pnl, is_oos)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)""",
                (run_id, json.dumps(result.best_params),
                 m.get("sharpe"), m.get("calmar"), m.get("sortino"),
                 m.get("profit_factor"), m.get("win_rate"),
                 m.get("max_drawdown_pct"), int(m.get("trade_count", 0)),
                 m.get("total_pnl")),
            )
        # Auto-create best candidate
        best_candidate_id = self.save_candidate(
            run_id=run_id, trial_id=None,
            params=result.best_params, label=f"best_{objective}",
        )
        # Auto-extract Pareto frontier
        if len(trials_dicts) > 1:
            n = len(trials_dicts)
            if n > _LARGE_TRIAL_THRESHOLD:
                logger.warning("pareto_large_trial_set", n_trials=n, run_id=run_id)
            pareto = self.get_pareto_frontier(run_id)
            for pt in pareto:
                s = pt.get("sharpe", 0) or 0
                c = pt.get("calmar", 0) or 0
                self.save_candidate(
                    run_id=run_id, trial_id=None,
                    params=pt["params"], label=f"pareto_sharpe{s:.2f}_calmar{c:.2f}",
                )
        self._conn.commit()
        return run_id

    # -- save_candidate ---------------------------------------------------

    def save_candidate(
        self,
        run_id: int,
        trial_id: int | None,
        params: dict[str, Any],
        label: str,
        regime: str | None = None,
        notes: str | None = None,
    ) -> int:
        """Insert a candidate row. Returns the candidate_id."""
        strategy = self._conn.execute(
            "SELECT strategy FROM param_runs WHERE id = ?", (run_id,),
        ).fetchone()
        if strategy is None:
            raise ValueError(f"Run {run_id} not found")
        cur = self._conn.execute(
            """INSERT INTO param_candidates
               (run_id, trial_id, strategy, params, label, regime, is_active, notes)
               VALUES (?, ?, ?, ?, ?, ?, 0, ?)""",
            (run_id, trial_id, strategy["strategy"], json.dumps(params),
             label, regime, notes),
        )
        self._conn.commit()
        return cur.lastrowid  # type: ignore[return-value]

    # -- activate ---------------------------------------------------------

    def activate(self, candidate_id: int) -> None:
        """Mark a candidate as active, deactivating all others for that strategy."""
        row = self._conn.execute(
            "SELECT strategy FROM param_candidates WHERE id = ?", (candidate_id,),
        ).fetchone()
        if row is None:
            raise ValueError(f"Candidate {candidate_id} not found")
        now = datetime.now(UTC).isoformat(timespec="seconds")
        self._conn.execute(
            "UPDATE param_candidates SET is_active = 0 WHERE strategy = ?",
            (row["strategy"],),
        )
        self._conn.execute(
            "UPDATE param_candidates SET is_active = 1, activated_at = ? WHERE id = ?",
            (now, candidate_id),
        )
        self._conn.commit()

    # -- get_active -------------------------------------------------------

    def get_active(self, strategy: str) -> dict[str, Any] | None:
        """Return the active candidate's params dict, or None."""
        row = self._conn.execute(
            "SELECT params FROM param_candidates WHERE strategy = ? AND is_active = 1",
            (strategy,),
        ).fetchone()
        if row is None:
            return None
        return json.loads(row["params"])

    def get_active_detail(self, strategy: str) -> dict[str, Any] | None:
        """Return the active candidate with full metadata."""
        row = self._conn.execute(
            """SELECT c.id, c.run_id, c.params, c.label, c.regime,
                      c.activated_at, c.notes,
                      r.objective, r.tag, r.run_at, r.symbol
               FROM param_candidates c
               JOIN param_runs r ON r.id = c.run_id
               WHERE c.strategy = ? AND c.is_active = 1""",
            (strategy,),
        ).fetchone()
        if row is None:
            return None
        return {
            "candidate_id": row["id"],
            "run_id": row["run_id"],
            "params": json.loads(row["params"]),
            "label": row["label"],
            "regime": row["regime"],
            "activated_at": row["activated_at"],
            "notes": row["notes"],
            "objective": row["objective"],
            "tag": row["tag"],
            "run_at": row["run_at"],
            "symbol": row["symbol"],
        }

    # -- Pareto frontier --------------------------------------------------

    def get_pareto_frontier(
        self,
        run_id: int,
        objectives: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Compute Pareto-optimal trials for a run across given objectives."""
        objs = objectives or _DEFAULT_PARETO_OBJECTIVES
        rows = self._conn.execute(
            "SELECT id, params, sharpe, calmar, sortino, profit_factor, "
            "win_rate, max_drawdown_pct, trade_count, total_pnl "
            "FROM param_trials WHERE run_id = ? AND is_oos = 0",
            (run_id,),
        ).fetchall()
        if not rows:
            return []
        trials = []
        for r in rows:
            d: dict[str, Any] = {
                "trial_id": r["id"],
                "params": json.loads(r["params"]),
            }
            for col in _METRIC_COLS:
                d[col] = r[col]
            trials.append(d)
        dominated: set[int] = set()
        for i, a in enumerate(trials):
            if i in dominated:
                continue
            for j, b in enumerate(trials):
                if i == j or j in dominated:
                    continue
                if all((b.get(o) or 0) >= (a.get(o) or 0) for o in objs) and \
                   any((b.get(o) or 0) > (a.get(o) or 0) for o in objs):
                    dominated.add(i)
                    break
        return [t for i, t in enumerate(trials) if i not in dominated]

    # -- get_run_history --------------------------------------------------

    def get_run_history(
        self,
        strategy: str,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Return recent runs for a strategy, most recent first."""
        runs = self._conn.execute(
            """SELECT r.id, r.run_at, r.strategy, r.symbol, r.objective,
                      r.is_fraction, r.n_trials, r.search_type, r.source,
                      r.tag, r.notes, r.train_start, r.train_end,
                      r.test_start, r.test_end
               FROM param_runs r
               WHERE r.strategy = ?
               ORDER BY r.run_at DESC, r.id DESC
               LIMIT ?""",
            (strategy, limit),
        ).fetchall()
        result = []
        for r in runs:
            run_id = r["id"]
            best = self._conn.execute(
                """SELECT params, sharpe, calmar, sortino, profit_factor,
                          win_rate, max_drawdown_pct, trade_count, total_pnl
                   FROM param_trials
                   WHERE run_id = ? AND is_oos = 0
                   ORDER BY {} DESC LIMIT 1""".format(r["objective"]),
                (run_id,),
            ).fetchone()
            n_candidates = self._conn.execute(
                "SELECT COUNT(*) as cnt FROM param_candidates WHERE run_id = ?",
                (run_id,),
            ).fetchone()["cnt"]
            entry: dict[str, Any] = {
                "run_id": run_id,
                "run_at": r["run_at"],
                "strategy": r["strategy"],
                "symbol": r["symbol"],
                "objective": r["objective"],
                "is_fraction": r["is_fraction"],
                "n_trials": r["n_trials"],
                "search_type": r["search_type"],
                "source": r["source"],
                "tag": r["tag"],
                "notes": r["notes"],
                "train_start": r["train_start"],
                "train_end": r["train_end"],
                "test_start": r["test_start"],
                "test_end": r["test_end"],
                "n_candidates": n_candidates,
            }
            if best:
                entry["best_params"] = json.loads(best["params"])
                entry["best_metrics"] = {
                    col: best[col] for col in _METRIC_COLS if best[col] is not None
                }
            result.append(entry)
        return result

    # -- compare_runs -----------------------------------------------------

    def compare_runs(self, run_ids: list[int]) -> list[dict[str, Any]]:
        """Return best trial metrics for each run, for side-by-side comparison."""
        result = []
        for rid in run_ids:
            run = self._conn.execute(
                "SELECT * FROM param_runs WHERE id = ?", (rid,),
            ).fetchone()
            if run is None:
                continue
            best = self._conn.execute(
                """SELECT params, sharpe, calmar, sortino, profit_factor,
                          win_rate, max_drawdown_pct, trade_count, total_pnl
                   FROM param_trials
                   WHERE run_id = ? AND is_oos = 0
                   ORDER BY {} DESC LIMIT 1""".format(run["objective"]),
                (rid,),
            ).fetchone()
            entry: dict[str, Any] = {
                "run_id": rid,
                "run_at": run["run_at"],
                "strategy": run["strategy"],
                "symbol": run["symbol"],
                "objective": run["objective"],
                "tag": run["tag"],
            }
            if best:
                entry["best_params"] = json.loads(best["params"])
                entry["best_metrics"] = {
                    col: best[col] for col in _METRIC_COLS if best[col] is not None
                }
            result.append(entry)
        return result
