"""SQLite-backed parameter registry for optimization runs, trials, and candidates.

Replaces the single-TOML approach with append-only versioning, Pareto frontier
extraction, and an explicit is_active flag for production param selection.
"""

from __future__ import annotations

import os
import json
import sqlite3

import structlog

from typing import Any
from pathlib import Path
from datetime import datetime, timezone, timedelta

_TAIPEI_TZ = timezone(timedelta(hours=8))
from src.simulator.types import OptimizerResult

logger = structlog.get_logger(__name__)

_DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "param_registry.db"
_DEFAULT_PARETO_OBJECTIVES = ["sharpe", "calmar"]
_METRIC_COLS = [
    "sharpe",
    "calmar",
    "sortino",
    "profit_factor",
    "win_rate",
    "max_drawdown_pct",
    "trade_count",
    "total_pnl",
    "alpha",
]
_LARGE_TRIAL_THRESHOLD = 5000


def _sanitize_objective_column(objective: str) -> str:
    return objective if objective in _METRIC_COLS else "sortino"

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS param_runs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    run_at          TEXT NOT NULL,
    strategy        TEXT NOT NULL,
    symbol          TEXT NOT NULL,
    train_start     TEXT,
    train_end       TEXT,
    test_start      TEXT,
    test_end        TEXT,
    objective       TEXT NOT NULL,
    is_fraction     REAL,
    n_trials        INTEGER NOT NULL,
    search_type     TEXT NOT NULL,
    source          TEXT NOT NULL,
    tag             TEXT,
    notes           TEXT,
    initial_capital REAL,
    strategy_hash   TEXT,
    strategy_code   TEXT,
    objective_direction TEXT NOT NULL DEFAULT 'maximize',
    mode            TEXT NOT NULL DEFAULT 'research',
    disqualified_trials INTEGER NOT NULL DEFAULT 0,
    gate_results_json TEXT,
    gate_details_json TEXT,
    promotable      INTEGER NOT NULL DEFAULT 0
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
    alpha        REAL,
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
        self._migrate_strategy_names()

    @staticmethod
    def _validate_strategy_slug(strategy: str) -> None:
        """Reject module:factory format — callers must normalize first."""
        if ":" in strategy or strategy.startswith("src."):
            raise ValueError(
                f"Strategy must be a normalized slug, got '{strategy}'. "
                "Use resolve_strategy_slug() before calling registry methods."
            )

    def _ensure_tables(self) -> None:
        self._conn.executescript(_SCHEMA_SQL)
        self._conn.commit()
        self._migrate_add_initial_capital()
        self._migrate_add_code_hash()
        self._migrate_add_alpha()
        self._migrate_add_governance_columns()

    def _migrate_add_governance_columns(self) -> None:
        cols = [r[1] for r in self._conn.execute("PRAGMA table_info(param_runs)").fetchall()]
        if "objective_direction" not in cols:
            self._conn.execute(
                "ALTER TABLE param_runs ADD COLUMN objective_direction TEXT NOT NULL DEFAULT 'maximize'"
            )
        if "mode" not in cols:
            self._conn.execute(
                "ALTER TABLE param_runs ADD COLUMN mode TEXT NOT NULL DEFAULT 'research'"
            )
        if "disqualified_trials" not in cols:
            self._conn.execute(
                "ALTER TABLE param_runs ADD COLUMN disqualified_trials INTEGER NOT NULL DEFAULT 0"
            )
        if "gate_results_json" not in cols:
            self._conn.execute("ALTER TABLE param_runs ADD COLUMN gate_results_json TEXT")
        if "gate_details_json" not in cols:
            self._conn.execute("ALTER TABLE param_runs ADD COLUMN gate_details_json TEXT")
        if "promotable" not in cols:
            self._conn.execute(
                "ALTER TABLE param_runs ADD COLUMN promotable INTEGER NOT NULL DEFAULT 0"
            )
        self._conn.commit()

    def _migrate_add_code_hash(self) -> None:
        """Add strategy_hash and strategy_code columns if missing (idempotent)."""
        cols = [r[1] for r in self._conn.execute("PRAGMA table_info(param_runs)").fetchall()]
        if "strategy_hash" not in cols:
            self._conn.execute("ALTER TABLE param_runs ADD COLUMN strategy_hash TEXT")
        if "strategy_code" not in cols:
            self._conn.execute("ALTER TABLE param_runs ADD COLUMN strategy_code TEXT")
        self._conn.commit()

    def _migrate_add_alpha(self) -> None:
        """Add alpha column to param_trials if missing (idempotent)."""
        cols = [r[1] for r in self._conn.execute("PRAGMA table_info(param_trials)").fetchall()]
        if "alpha" not in cols:
            self._conn.execute("ALTER TABLE param_trials ADD COLUMN alpha REAL")
            self._conn.commit()

    def _migrate_add_initial_capital(self) -> None:
        """Add initial_capital column to param_runs if missing (one-time migration)."""
        cols = [r[1] for r in self._conn.execute("PRAGMA table_info(param_runs)").fetchall()]
        if "initial_capital" not in cols:
            self._conn.execute("ALTER TABLE param_runs ADD COLUMN initial_capital REAL")
            self._conn.commit()

    def _migrate_strategy_names(self) -> None:
        """One-time fix: convert module:factory strategy names to slugs."""
        rows = self._conn.execute(
            "SELECT DISTINCT strategy FROM param_runs WHERE strategy LIKE '%:%'"
        ).fetchall()
        if not rows:
            return
        for row in rows:
            old = row["strategy"]
            slug = self._resolve_module_to_slug(old)
            if slug == old:
                logger.warning("migration_unresolvable", strategy=old)
                continue
            self._conn.execute(
                "UPDATE param_runs SET strategy = ? WHERE strategy = ?",
                (slug, old),
            )
            self._conn.execute(
                "UPDATE param_candidates SET strategy = ? WHERE strategy = ?",
                (slug, old),
            )
            logger.info("migrated_strategy_name", old=old, new=slug)
        self._conn.commit()

    @staticmethod
    def _resolve_module_to_slug(strategy: str) -> str:
        """Extract slug from module:factory format, e.g.
        'src.strategies.medium_term.trend_following.foo:create_foo_engine'
        -> 'medium_term/trend_following/foo'
        """
        if ":" not in strategy:
            return strategy
        mod_part = strategy.split(":")[0]
        prefix = "src.strategies."
        if mod_part.startswith(prefix):
            return mod_part[len(prefix) :].replace(".", "/")
        return strategy

    def close(self) -> None:
        self._conn.close()

    # -- save_backtest_run ------------------------------------------------

    def save_backtest_run(
        self,
        strategy: str,
        symbol: str,
        params: dict[str, Any],
        metrics: dict[str, Any],
        source: str = "mcp",
        tool: str = "run_backtest",
        tag: str | None = None,
        notes: str | None = None,
        start: str | None = None,
        end: str | None = None,
        timeframe: str | None = None,
        initial_capital: float = 2_000_000.0,
        strategy_hash: str | None = None,
        strategy_code: str | None = None,
        objective: str = "sortino",
    ) -> int:
        """Persist a single backtest result (not a full sweep). Returns run_id or -1 on error.

        Deduplicates by (strategy_hash, symbol, train_start, train_end, notes).
        Notes include timeframe AND cost info, so different costs = different runs.
        Returns existing run_id if a matching run already exists.
        """
        self._validate_strategy_slug(strategy)
        try:
            # Build notes first so dedup can check the full string (incl. costs)
            tf_notes = f"tf={timeframe}" if timeframe else None
            combined_notes = "; ".join(filter(None, [notes, tf_notes]))
            if strategy_hash and start and end and timeframe:
                existing = self._conn.execute(
                    """SELECT r.id FROM param_runs r
                       WHERE r.strategy_hash = ? AND r.symbol = ?
                         AND r.train_start = ? AND r.train_end = ?
                         AND r.notes = ?""",
                    (strategy_hash, symbol, start, end, combined_notes or None),
                ).fetchone()
                if existing:
                    return existing[0]
            now = datetime.now(_TAIPEI_TZ).isoformat(timespec="seconds")
            run_tag = tag or f"tool:{tool}"
            cur = self._conn.execute(
                """INSERT INTO param_runs
                   (run_at, strategy, symbol, train_start, train_end, test_start, test_end,
                    objective, is_fraction, n_trials, search_type, source, tag, notes,
                    initial_capital, strategy_hash, strategy_code)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 'single', ?, ?, ?, ?, ?, ?)""",
                (
                    now,
                    strategy,
                    symbol,
                    start,
                    end,
                    None,
                    None,
                    objective,
                    None,
                    source,
                    run_tag,
                    combined_notes or None,
                    initial_capital,
                    strategy_hash,
                    strategy_code,
                ),
            )
            run_id = cur.lastrowid
            assert run_id is not None
            self._conn.execute(
                """INSERT INTO param_trials
                   (run_id, params, sharpe, calmar, sortino, profit_factor,
                    win_rate, max_drawdown_pct, trade_count, total_pnl, alpha, is_oos)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)""",
                (
                    run_id,
                    json.dumps(params),
                    metrics.get("sharpe"),
                    metrics.get("calmar"),
                    metrics.get("sortino"),
                    metrics.get("profit_factor"),
                    metrics.get("win_rate"),
                    metrics.get("max_drawdown_pct"),
                    int(metrics.get("trade_count", 0)),
                    metrics.get("total_pnl"),
                    metrics.get("alpha"),
                ),
            )
            obj_val = metrics.get(objective, 0) or 0
            self._conn.execute(
                """INSERT INTO param_candidates
                   (run_id, trial_id, strategy, params, label, regime, is_active, notes)
                   VALUES (?, NULL, ?, ?, ?, NULL, 0, NULL)""",
                (run_id, strategy, json.dumps(params), f"single_{objective}{obj_val:.2f}"),
            )
            self._conn.commit()
            return run_id
        except Exception:
            logger.exception("save_backtest_run_failed", strategy=strategy, symbol=symbol)
            return -1

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
        initial_capital: float = 2_000_000.0,
        strategy_hash: str | None = None,
        strategy_code: str | None = None,
        base_params: dict[str, Any] | None = None,
    ) -> int:
        """Persist a full OptimizerResult. Returns the run_id.

        base_params: fixed parameters that were held constant during the sweep.
        They are merged with result.best_params before saving candidates so that
        activating a candidate always yields the complete parameter set.
        """
        self._validate_strategy_slug(strategy)
        trials_dicts = result.trials.to_dicts() if len(result.trials) > 0 else []
        now = datetime.now(_TAIPEI_TZ).isoformat(timespec="seconds")
        # Merge base_params into best_params so candidates always store the full set.
        # base_params are fixed during the sweep and would otherwise fall back to
        # schema defaults when the candidate is activated in the dashboard.
        full_best_params = {**(base_params or {}), **(result.best_params or {})}
        cur = self._conn.execute(
            """INSERT INTO param_runs
               (run_at, strategy, symbol, train_start, train_end, test_start, test_end,
                objective, is_fraction, n_trials, search_type, source, tag, notes,
                initial_capital, strategy_hash, strategy_code, objective_direction, mode,
                disqualified_trials, gate_results_json, gate_details_json, promotable)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                now,
                strategy,
                symbol,
                train_start,
                train_end,
                test_start,
                test_end,
                result.objective_name or objective,
                is_fraction,
                len(trials_dicts),
                search_type,
                source,
                tag,
                notes,
                initial_capital,
                strategy_hash,
                strategy_code,
                result.objective_direction,
                result.mode,
                result.disqualified_trials,
                json.dumps(result.gate_results),
                json.dumps(result.gate_details),
                int(result.promotable),
            ),
        )
        run_id = cur.lastrowid
        assert run_id is not None
        param_keys = [
            k
            for k in (trials_dicts[0].keys() if trials_dicts else [])
            if k not in _METRIC_COLS and not k.startswith("_")
        ]
        for row in trials_dicts:
            params_json = json.dumps({k: row[k] for k in param_keys if k in row})
            self._conn.execute(
                """INSERT INTO param_trials
                   (run_id, params, sharpe, calmar, sortino, profit_factor,
                    win_rate, max_drawdown_pct, trade_count, total_pnl, alpha, is_oos)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)""",
                (
                    run_id,
                    params_json,
                    row.get("sharpe"),
                    row.get("calmar"),
                    row.get("sortino"),
                    row.get("profit_factor"),
                    row.get("win_rate"),
                    row.get("max_drawdown_pct"),
                    int(row.get("trade_count") or row.get("_trade_count") or 0),
                    row.get("total_pnl"),
                    row.get("alpha"),
                ),
            )
        # OOS best result
        if result.best_oos_result:
            m = result.best_oos_result.metrics
            self._conn.execute(
                """INSERT INTO param_trials
                   (run_id, params, sharpe, calmar, sortino, profit_factor,
                    win_rate, max_drawdown_pct, trade_count, total_pnl, alpha, is_oos)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)""",
                (
                    run_id,
                    json.dumps(full_best_params),
                    m.get("sharpe"),
                    m.get("calmar"),
                    m.get("sortino"),
                    m.get("profit_factor"),
                    m.get("win_rate"),
                    m.get("max_drawdown_pct"),
                    int(m.get("trade_count", 0)),
                    m.get("total_pnl"),
                    m.get("alpha"),
                ),
            )
        # Auto-create best candidate (full params = base + swept)
        self.save_candidate(
            run_id=run_id,
            trial_id=None,
            params=full_best_params,
            label=f"best_{objective}",
        )
        # Auto-extract Pareto frontier — also merge base_params into each Pareto candidate
        if len(trials_dicts) > 1:
            n = len(trials_dicts)
            if n > _LARGE_TRIAL_THRESHOLD:
                logger.warning("pareto_large_trial_set", n_trials=n, run_id=run_id)
            pareto = self.get_pareto_frontier(run_id)
            for pt in pareto:
                s = pt.get("sharpe", 0) or 0
                c = pt.get("calmar", 0) or 0
                full_pareto_params = {**(base_params or {}), **pt["params"]}
                self.save_candidate(
                    run_id=run_id,
                    trial_id=None,
                    params=full_pareto_params,
                    label=f"pareto_sharpe{s:.2f}_calmar{c:.2f}",
                )
        self._conn.commit()
        return run_id

    # -- save_fullperiod_trial --------------------------------------------

    def save_fullperiod_trial(
        self,
        run_id: int,
        params: dict[str, Any],
        metrics: dict[str, Any],
    ) -> None:
        """Persist a full-period validation trial (is_oos=2) for the winning params.

        After a production_intent sweep, the winning params are re-run on
        the full date range (not the IS fraction). This trial stores those
        metrics so the dashboard can show the headline full-period result.
        """
        self._conn.execute(
            """INSERT INTO param_trials
               (run_id, params, sharpe, calmar, sortino, profit_factor,
                win_rate, max_drawdown_pct, trade_count, total_pnl, alpha, is_oos)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 2)""",
            (
                run_id,
                json.dumps(params),
                metrics.get("sharpe"),
                metrics.get("calmar"),
                metrics.get("sortino"),
                metrics.get("profit_factor"),
                metrics.get("win_rate"),
                metrics.get("max_drawdown_pct"),
                int(metrics.get("trade_count", 0)),
                metrics.get("total_pnl"),
                metrics.get("alpha"),
            ),
        )
        self._conn.commit()

    def update_run_notes_append(self, run_id: int, extra: str) -> None:
        """Append text to an existing run's notes (separated by '; ')."""
        row = self._conn.execute(
            "SELECT notes FROM param_runs WHERE id = ?", (run_id,)
        ).fetchone()
        if row is None:
            return
        existing = row["notes"] or ""
        updated = "; ".join(filter(None, [existing, extra]))
        self._conn.execute(
            "UPDATE param_runs SET notes = ? WHERE id = ?", (updated, run_id)
        )
        self._conn.commit()

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
            "SELECT strategy FROM param_runs WHERE id = ?",
            (run_id,),
        ).fetchone()
        if strategy is None:
            raise ValueError(f"Run {run_id} not found")
        cur = self._conn.execute(
            """INSERT INTO param_candidates
               (run_id, trial_id, strategy, params, label, regime, is_active, notes)
               VALUES (?, ?, ?, ?, ?, ?, 0, ?)""",
            (run_id, trial_id, strategy["strategy"], json.dumps(params), label, regime, notes),
        )
        self._conn.commit()
        return cur.lastrowid  # type: ignore[return-value]

    # -- activate ---------------------------------------------------------

    def activate(self, candidate_id: int, enforce_gates: bool = True) -> None:
        """Mark a candidate as active, deactivating all others for that strategy."""
        row = self._conn.execute(
            """SELECT c.strategy, c.run_id, r.mode, r.promotable, r.gate_results_json
               FROM param_candidates c
               JOIN param_runs r ON r.id = c.run_id
               WHERE c.id = ?""",
            (candidate_id,),
        ).fetchone()
        if row is None:
            raise ValueError(f"Candidate {candidate_id} not found")
        if enforce_gates and row["mode"] == "production_intent" and int(row["promotable"]) != 1:
            gate_results = row["gate_results_json"] or "{}"
            raise ValueError(
                "Candidate activation blocked: production-intent run failed promotion gates "
                f"(run_id={row['run_id']}, gates={gate_results})"
            )
        now = datetime.now(_TAIPEI_TZ).isoformat(timespec="seconds")
        self._conn.execute(
            "UPDATE param_candidates SET is_active = 0 WHERE strategy = ?",
            (row["strategy"],),
        )
        self._conn.execute(
            "UPDATE param_candidates SET is_active = 1, activated_at = ? WHERE id = ?",
            (now, candidate_id),
        )
        self._conn.commit()

    # -- delete_run -------------------------------------------------------

    def delete_run(self, run_id: int) -> dict[str, Any]:
        """Delete a run and all its trials and candidates.

        If the deleted run contained the active candidate, auto-activate the
        remaining candidate with the highest sortino for that strategy.
        Returns info about what happened (e.g. auto-activated candidate).
        """
        run_row = self._conn.execute(
            "SELECT id, strategy FROM param_runs WHERE id = ?",
            (run_id,),
        ).fetchone()
        if run_row is None:
            raise ValueError(f"Run {run_id} not found")
        strategy = run_row["strategy"]
        had_active = (
            self._conn.execute(
                "SELECT id FROM param_candidates WHERE run_id = ? AND is_active = 1",
                (run_id,),
            ).fetchone()
            is not None
        )
        self._conn.execute("DELETE FROM param_candidates WHERE run_id = ?", (run_id,))
        self._conn.execute("DELETE FROM param_trials WHERE run_id = ?", (run_id,))
        self._conn.execute("DELETE FROM param_runs WHERE id = ?", (run_id,))
        self._conn.commit()
        result: dict[str, Any] = {"deleted": True, "had_active": had_active}
        if had_active:
            auto = self._auto_activate_best(strategy)
            result["auto_activated"] = auto
        return result

    def _auto_activate_best(self, strategy: str) -> dict[str, Any] | None:
        """Activate the candidate with the highest sortino for a strategy."""
        row = self._conn.execute(
            """SELECT c.id AS cid, t.sortino
               FROM param_candidates c
               JOIN param_trials t ON t.run_id = c.run_id AND t.is_oos = 0
               JOIN param_runs r ON r.id = c.run_id
               WHERE c.strategy = ?
                 AND (r.mode != 'production_intent' OR r.promotable = 1)
               ORDER BY t.sortino DESC LIMIT 1""",
            (strategy,),
        ).fetchone()
        if row is None:
            return None
        self.activate(row["cid"])
        return {"candidate_id": row["cid"], "sortino": row["sortino"]}

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
                      r.objective, r.tag, r.run_at, r.symbol, r.strategy_hash
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
            "strategy_hash": row["strategy_hash"],
        }

    # -- deactivate_stale_candidates -------------------------------------

    def deactivate_stale_candidates(self, strategy: str, current_hash: str) -> int:
        """Deactivate active candidates where strategy_hash != current_hash (excluding NULL).

        Returns the count of deactivated candidates.
        """
        cur = self._conn.execute(
            """UPDATE param_candidates
               SET is_active = 0
               WHERE strategy = ?
                 AND is_active = 1
                 AND run_id IN (
                     SELECT id FROM param_runs
                     WHERE strategy = ? AND strategy_hash IS NOT NULL AND strategy_hash != ?
                 )""",
            (strategy, strategy, current_hash),
        )
        self._conn.commit()
        return cur.rowcount

    def check_code_hash_match(self, strategy: str, current_hash: str) -> bool | None:
        """Check if the active candidate's stored hash matches the current file hash.

        Returns True if hash matches, False if different, None if no active candidate
        or if the active candidate has a NULL hash (legacy).
        """
        row = self._conn.execute(
            """SELECT r.strategy_hash
               FROM param_candidates c
               JOIN param_runs r ON r.id = c.run_id
               WHERE c.strategy = ? AND c.is_active = 1""",
            (strategy,),
        ).fetchone()
        if row is None:
            return None
        stored_hash = row["strategy_hash"]
        if stored_hash is None:
            return None
        return stored_hash == current_hash

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
            "win_rate, max_drawdown_pct, trade_count, total_pnl, alpha "
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
                if all((b.get(o) or 0) >= (a.get(o) or 0) for o in objs) and any(
                    (b.get(o) or 0) > (a.get(o) or 0) for o in objs
                ):
                    dominated.add(i)
                    break
        return [t for i, t in enumerate(trials) if i not in dominated]

    # -- get_run_history --------------------------------------------------

    def get_run_history(
        self,
        strategy: str,
        limit: int = 20,
        search_type: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return recent runs for a strategy, most recent first."""
        sql = """SELECT r.id, r.run_at, r.strategy, r.symbol, r.objective,
                        r.is_fraction, r.n_trials, r.search_type, r.source,
                        r.tag, r.notes, r.train_start, r.train_end,
                        r.test_start, r.test_end, r.initial_capital, r.strategy_hash,
                        r.objective_direction, r.mode, r.disqualified_trials, r.promotable
                 FROM param_runs r
                 WHERE r.strategy = ?"""
        params: list[Any] = [strategy]
        if search_type is not None:
            sql += " AND r.search_type = ?"
            params.append(search_type)
        sql += " ORDER BY r.run_at DESC, r.id DESC LIMIT ?"
        params.append(limit)
        runs = self._conn.execute(sql, params).fetchall()
        result = []
        for r in runs:
            run_id = r["id"]
            objective_col = _sanitize_objective_column(r["objective"])
            direction = "ASC" if r["objective_direction"] == "minimize" else "DESC"
            # Prefer full-period validation (is_oos=2), fall back to best IS trial (is_oos=0)
            _trial_cols = """params, sharpe, calmar, sortino, profit_factor,
                          win_rate, max_drawdown_pct, trade_count, total_pnl, alpha"""
            best_full = self._conn.execute(
                f"""SELECT {_trial_cols}
                   FROM param_trials
                   WHERE run_id = ? AND is_oos = 2
                   LIMIT 1""",
                (run_id,),
            ).fetchone()
            best_is = self._conn.execute(
                f"""SELECT {_trial_cols}
                   FROM param_trials
                   WHERE run_id = ? AND is_oos = 0
                   ORDER BY {objective_col} {direction} LIMIT 1""",
                (run_id,),
            ).fetchone()
            best = best_full or best_is
            cand_row = self._conn.execute(
                "SELECT COUNT(*) as cnt, MIN(id) as first_id FROM param_candidates WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            n_candidates = cand_row["cnt"]
            best_candidate_id = cand_row["first_id"]
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
                "best_candidate_id": best_candidate_id,
                "initial_capital": r["initial_capital"],
                "strategy_hash": r["strategy_hash"],
                "objective_direction": r["objective_direction"],
                "mode": r["mode"],
                "disqualified_trials": r["disqualified_trials"],
                "promotable": bool(r["promotable"]),
            }
            if best:
                entry["best_params"] = json.loads(best["params"])
                entry["best_metrics"] = {
                    col: best[col] for col in _METRIC_COLS if best[col] is not None
                }
                entry["metrics_source"] = "full_period" if best_full else "is_only"
            result.append(entry)
        return result

    # -- compare_runs -----------------------------------------------------

    def compare_runs(self, run_ids: list[int]) -> list[dict[str, Any]]:
        """Return best trial metrics for each run, for side-by-side comparison."""
        result = []
        for rid in run_ids:
            run = self._conn.execute(
                "SELECT * FROM param_runs WHERE id = ?",
                (rid,),
            ).fetchone()
            if run is None:
                continue
            objective_col = _sanitize_objective_column(run["objective"])
            direction = "ASC" if run["objective_direction"] == "minimize" else "DESC"
            _trial_cols = """params, sharpe, calmar, sortino, profit_factor,
                          win_rate, max_drawdown_pct, trade_count, total_pnl, alpha"""
            best_full = self._conn.execute(
                f"""SELECT {_trial_cols}
                   FROM param_trials WHERE run_id = ? AND is_oos = 2
                   LIMIT 1""",
                (rid,),
            ).fetchone()
            best_is = self._conn.execute(
                f"""SELECT {_trial_cols}
                   FROM param_trials WHERE run_id = ? AND is_oos = 0
                   ORDER BY {objective_col} {direction} LIMIT 1""",
                (rid,),
            ).fetchone()
            best = best_full or best_is
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
                entry["metrics_source"] = "full_period" if best_full else "is_only"
            result.append(entry)
        return result
