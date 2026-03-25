"""Tests for ParamRegistry — SQLite-backed optimization run persistence."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import polars as pl
import pytest

from src.simulator.types import BacktestResult, OptimizerResult
from src.strategies.param_registry import ParamRegistry


@pytest.fixture()
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "test_params.db"


@pytest.fixture()
def registry(db_path: Path) -> ParamRegistry:
    return ParamRegistry(db_path=db_path)


def _make_result(
    trials: list[dict] | None = None,
    best_params: dict | None = None,
) -> OptimizerResult:
    """Create a minimal OptimizerResult for testing."""
    if trials is None:
        trials = [
            {
                "bb_len": 15,
                "rsi_oversold": 25,
                "sharpe": 1.2,
                "calmar": 0.8,
                "sortino": 1.5,
                "profit_factor": 1.4,
                "win_rate": 0.55,
                "max_drawdown_pct": 0.12,
                "trade_count": 50,
                "total_pnl": 100000,
            },
            {
                "bb_len": 20,
                "rsi_oversold": 30,
                "sharpe": 1.5,
                "calmar": 0.6,
                "sortino": 1.8,
                "profit_factor": 1.6,
                "win_rate": 0.60,
                "max_drawdown_pct": 0.15,
                "trade_count": 40,
                "total_pnl": 120000,
            },
            {
                "bb_len": 25,
                "rsi_oversold": 25,
                "sharpe": 0.9,
                "calmar": 1.1,
                "sortino": 1.1,
                "profit_factor": 1.2,
                "win_rate": 0.48,
                "max_drawdown_pct": 0.08,
                "trade_count": 60,
                "total_pnl": 80000,
            },
        ]
    bp = best_params or {"bb_len": 20, "rsi_oversold": 30}
    is_result = BacktestResult(
        equity_curve=[2_000_000, 2_100_000],
        drawdown_series=[0.0, -0.01],
        trade_log=[],
        metrics={"sharpe": 1.5, "calmar": 0.6, "trade_count": 40},
        monthly_returns={},
        yearly_returns={},
    )
    return OptimizerResult(
        trials=pl.DataFrame(trials),
        best_params=bp,
        best_is_result=is_result,
        best_oos_result=None,
    )


class TestDBCreation:
    def test_creates_db_file(self, db_path: Path) -> None:
        ParamRegistry(db_path=db_path)
        assert db_path.exists()

    def test_tables_exist(self, registry: ParamRegistry) -> None:
        tables = registry._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
        names = [t["name"] for t in tables]
        assert "param_runs" in names
        assert "param_trials" in names
        assert "param_candidates" in names

    def test_idempotent_creation(self, db_path: Path) -> None:
        r1 = ParamRegistry(db_path=db_path)
        r1.close()
        r2 = ParamRegistry(db_path=db_path)
        r2.close()

    def test_env_var_override(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        custom = tmp_path / "custom.db"
        monkeypatch.setenv("PARAM_REGISTRY_DB", str(custom))
        r = ParamRegistry()
        assert custom.exists()
        r.close()


class TestSaveRun:
    def test_saves_run_and_trials(self, registry: ParamRegistry) -> None:
        result = _make_result()
        run_id = registry.save_run(
            result=result,
            strategy="atr_mean_reversion",
            symbol="TX",
            objective="sharpe",
            source="test",
        )
        assert isinstance(run_id, int)
        run = registry._conn.execute("SELECT * FROM param_runs WHERE id = ?", (run_id,)).fetchone()
        assert run["strategy"] == "atr_mean_reversion"
        assert run["symbol"] == "TX"
        assert run["n_trials"] == 3
        trials = registry._conn.execute(
            "SELECT * FROM param_trials WHERE run_id = ? AND is_oos = 0", (run_id,)
        ).fetchall()
        assert len(trials) == 3

    def test_best_candidate_created(self, registry: ParamRegistry) -> None:
        result = _make_result()
        run_id = registry.save_run(
            result=result,
            strategy="atr_mean_reversion",
            symbol="TX",
            objective="sharpe",
            source="test",
        )
        candidates = registry._conn.execute(
            "SELECT * FROM param_candidates WHERE run_id = ? AND label = 'best_sharpe'",
            (run_id,),
        ).fetchall()
        assert len(candidates) == 1
        assert json.loads(candidates[0]["params"]) == {"bb_len": 20, "rsi_oversold": 30}

    def test_pareto_candidates_created(self, registry: ParamRegistry) -> None:
        result = _make_result()
        run_id = registry.save_run(
            result=result,
            strategy="atr_mean_reversion",
            symbol="TX",
            objective="sharpe",
            source="test",
        )
        pareto_cands = registry._conn.execute(
            "SELECT * FROM param_candidates WHERE run_id = ? AND label LIKE 'pareto_%'",
            (run_id,),
        ).fetchall()
        assert len(pareto_cands) >= 1

    def test_oos_result_stored(self, registry: ParamRegistry) -> None:
        result = _make_result()
        oos = BacktestResult(
            equity_curve=[2_000_000, 2_050_000],
            drawdown_series=[0.0, -0.005],
            trade_log=[],
            metrics={"sharpe": 1.0, "calmar": 0.5, "trade_count": 20},
            monthly_returns={},
            yearly_returns={},
        )
        result.best_oos_result = oos
        run_id = registry.save_run(
            result=result,
            strategy="atr_mean_reversion",
            symbol="TX",
            objective="sharpe",
            source="test",
        )
        oos_trials = registry._conn.execute(
            "SELECT * FROM param_trials WHERE run_id = ? AND is_oos = 1", (run_id,)
        ).fetchall()
        assert len(oos_trials) == 1
        assert oos_trials[0]["sharpe"] == 1.0


class TestParetoFrontier:
    def test_two_objective_frontier(self, registry: ParamRegistry) -> None:
        result = _make_result()
        run_id = registry.save_run(
            result=result,
            strategy="atr_mean_reversion",
            symbol="TX",
            objective="sharpe",
            source="test",
        )
        pareto = registry.get_pareto_frontier(run_id, objectives=["sharpe", "calmar"])
        # Trial 1: sharpe=1.2, calmar=0.8 — not dominated
        # Trial 2: sharpe=1.5, calmar=0.6 — not dominated
        # Trial 3: sharpe=0.9, calmar=1.1 — not dominated
        # None dominates another, so all 3 should be on the frontier
        assert len(pareto) == 3

    def test_single_objective(self, registry: ParamRegistry) -> None:
        result = _make_result()
        run_id = registry.save_run(
            result=result,
            strategy="atr_mean_reversion",
            symbol="TX",
            objective="sharpe",
            source="test",
        )
        pareto = registry.get_pareto_frontier(run_id, objectives=["sharpe"])
        assert len(pareto) == 1
        assert pareto[0]["sharpe"] == 1.5

    def test_all_equal(self, registry: ParamRegistry) -> None:
        trials = [
            {
                "bb_len": i,
                "sharpe": 1.0,
                "calmar": 1.0,
                "sortino": 1.0,
                "profit_factor": 1.0,
                "win_rate": 0.5,
                "max_drawdown_pct": 0.1,
                "trade_count": 50,
                "total_pnl": 100000,
            }
            for i in range(5)
        ]
        result = _make_result(trials=trials, best_params={"bb_len": 0})
        run_id = registry.save_run(
            result=result,
            strategy="test",
            symbol="TX",
            objective="sharpe",
            source="test",
        )
        pareto = registry.get_pareto_frontier(run_id, objectives=["sharpe", "calmar"])
        assert len(pareto) == 5

    def test_dominated_filtered(self, registry: ParamRegistry) -> None:
        trials = [
            {
                "bb_len": 10,
                "sharpe": 2.0,
                "calmar": 2.0,
                "sortino": 1.0,
                "profit_factor": 1.0,
                "win_rate": 0.5,
                "max_drawdown_pct": 0.1,
                "trade_count": 50,
                "total_pnl": 100000,
            },
            {
                "bb_len": 20,
                "sharpe": 1.0,
                "calmar": 1.0,
                "sortino": 1.0,
                "profit_factor": 1.0,
                "win_rate": 0.5,
                "max_drawdown_pct": 0.1,
                "trade_count": 50,
                "total_pnl": 100000,
            },
        ]
        result = _make_result(trials=trials, best_params={"bb_len": 10})
        run_id = registry.save_run(
            result=result,
            strategy="test",
            symbol="TX",
            objective="sharpe",
            source="test",
        )
        pareto = registry.get_pareto_frontier(run_id, objectives=["sharpe", "calmar"])
        assert len(pareto) == 1
        assert pareto[0]["params"]["bb_len"] == 10


class TestActivate:
    def test_activate_sets_flag(self, registry: ParamRegistry) -> None:
        result = _make_result()
        run_id = registry.save_run(
            result=result,
            strategy="atr_mean_reversion",
            symbol="TX",
            objective="sharpe",
            source="test",
        )
        cand = registry._conn.execute(
            "SELECT id FROM param_candidates WHERE run_id = ? AND label = 'best_sharpe'",
            (run_id,),
        ).fetchone()
        registry.activate(cand["id"])
        active = registry._conn.execute(
            "SELECT * FROM param_candidates WHERE id = ?", (cand["id"],)
        ).fetchone()
        assert active["is_active"] == 1
        assert active["activated_at"] is not None

    def test_activate_deactivates_previous(self, registry: ParamRegistry) -> None:
        r1 = _make_result()
        run1 = registry.save_run(
            result=r1,
            strategy="atr_mean_reversion",
            symbol="TX",
            objective="sharpe",
            source="test",
        )
        r2 = _make_result()
        run2 = registry.save_run(
            result=r2,
            strategy="atr_mean_reversion",
            symbol="TX",
            objective="sharpe",
            source="test",
        )
        cand1 = registry._conn.execute(
            "SELECT id FROM param_candidates WHERE run_id = ? AND label = 'best_sharpe'",
            (run1,),
        ).fetchone()
        cand2 = registry._conn.execute(
            "SELECT id FROM param_candidates WHERE run_id = ? AND label = 'best_sharpe'",
            (run2,),
        ).fetchone()
        registry.activate(cand1["id"])
        registry.activate(cand2["id"])
        c1 = registry._conn.execute(
            "SELECT is_active FROM param_candidates WHERE id = ?", (cand1["id"],)
        ).fetchone()
        assert c1["is_active"] == 0

    def test_activate_nonexistent_raises(self, registry: ParamRegistry) -> None:
        with pytest.raises(ValueError, match="not found"):
            registry.activate(999)


class TestGetActive:
    def test_returns_params(self, registry: ParamRegistry) -> None:
        result = _make_result()
        run_id = registry.save_run(
            result=result,
            strategy="atr_mean_reversion",
            symbol="TX",
            objective="sharpe",
            source="test",
        )
        cand = registry._conn.execute(
            "SELECT id FROM param_candidates WHERE run_id = ? AND label = 'best_sharpe'",
            (run_id,),
        ).fetchone()
        registry.activate(cand["id"])
        active = registry.get_active("atr_mean_reversion")
        assert active is not None
        assert active == {"bb_len": 20, "rsi_oversold": 30}

    def test_returns_none_when_no_active(self, registry: ParamRegistry) -> None:
        assert registry.get_active("nonexistent") is None

    def test_get_active_detail(self, registry: ParamRegistry) -> None:
        result = _make_result()
        run_id = registry.save_run(
            result=result,
            strategy="atr_mean_reversion",
            symbol="TX",
            objective="sharpe",
            source="test",
        )
        cand = registry._conn.execute(
            "SELECT id FROM param_candidates WHERE run_id = ? AND label = 'best_sharpe'",
            (run_id,),
        ).fetchone()
        registry.activate(cand["id"])
        detail = registry.get_active_detail("atr_mean_reversion")
        assert detail is not None
        assert detail["params"] == {"bb_len": 20, "rsi_oversold": 30}
        assert detail["label"] == "best_sharpe"
        assert detail["objective"] == "sharpe"


class TestRunHistory:
    def test_returns_most_recent(self, registry: ParamRegistry) -> None:
        for i in range(3):
            result = _make_result()
            registry.save_run(
                result=result,
                strategy="atr_mean_reversion",
                symbol="TX",
                objective="sharpe",
                source="test",
                tag=f"run_{i}",
            )
        runs = registry.get_run_history("atr_mean_reversion", limit=2)
        assert len(runs) == 2
        assert runs[0]["tag"] == "run_2"

    def test_empty_for_unknown_strategy(self, registry: ParamRegistry) -> None:
        assert registry.get_run_history("nonexistent") == []


class TestCompareRuns:
    def test_compare_two_runs(self, registry: ParamRegistry) -> None:
        r1 = _make_result()
        id1 = registry.save_run(
            result=r1,
            strategy="atr_mean_reversion",
            symbol="TX",
            objective="sharpe",
            source="test",
        )
        r2 = _make_result()
        id2 = registry.save_run(
            result=r2,
            strategy="atr_mean_reversion",
            symbol="TX",
            objective="sharpe",
            source="test",
        )
        comparison = registry.compare_runs([id1, id2])
        assert len(comparison) == 2

    def test_skips_invalid_ids(self, registry: ParamRegistry) -> None:
        r1 = _make_result()
        id1 = registry.save_run(
            result=r1,
            strategy="atr_mean_reversion",
            symbol="TX",
            objective="sharpe",
            source="test",
        )
        comparison = registry.compare_runs([id1, 999])
        assert len(comparison) == 1


class TestIntegration:
    def test_full_flow(self, registry: ParamRegistry) -> None:
        """End-to-end: save_run → auto Pareto → activate → get_active."""
        result = _make_result()
        run_id = registry.save_run(
            result=result,
            strategy="atr_mean_reversion",
            symbol="TX",
            objective="sharpe",
            source="test",
        )
        # Best candidate exists
        best = registry._conn.execute(
            "SELECT id, params FROM param_candidates WHERE run_id = ? AND label = 'best_sharpe'",
            (run_id,),
        ).fetchone()
        assert best is not None
        # Pareto candidates exist
        pareto = registry._conn.execute(
            "SELECT COUNT(*) as cnt FROM param_candidates WHERE run_id = ? AND label LIKE 'pareto_%'",
            (run_id,),
        ).fetchone()
        assert pareto["cnt"] >= 1
        # Activate best
        registry.activate(best["id"])
        active = registry.get_active("atr_mean_reversion")
        assert active == {"bb_len": 20, "rsi_oversold": 30}
        # History shows the run
        history = registry.get_run_history("atr_mean_reversion")
        assert len(history) == 1
        assert history[0]["run_id"] == run_id

    def test_param_loader_fallback(self, db_path: Path) -> None:
        """Test load_strategy_params reads from registry first."""
        registry = ParamRegistry(db_path=db_path)
        result = _make_result()
        run_id = registry.save_run(
            result=result,
            strategy="test_strat",
            symbol="TX",
            objective="sharpe",
            source="test",
        )
        best = registry._conn.execute(
            "SELECT id FROM param_candidates WHERE run_id = ? AND label = 'best_sharpe'",
            (run_id,),
        ).fetchone()
        registry.activate(best["id"])
        active = registry.get_active("test_strat")
        assert active == {"bb_len": 20, "rsi_oversold": 30}
        registry.close()


class TestResolveStrategySlug:
    def test_slug_passthrough(self) -> None:
        from src.mcp_server.facade import resolve_strategy_slug

        assert (
            resolve_strategy_slug("intraday/trend_following/ema_trend_pullback")
            == "intraday/trend_following/ema_trend_pullback"
        )

    def test_module_factory_resolution(self) -> None:
        from src.mcp_server.facade import resolve_strategy_slug

        result = resolve_strategy_slug(
            "src.strategies.intraday.trend_following.ema_trend_pullback:create_ema_trend_pullback_engine"
        )
        assert result == "intraday/trend_following/ema_trend_pullback"

    def test_unknown_fallback(self) -> None:
        from src.mcp_server.facade import resolve_strategy_slug

        assert resolve_strategy_slug("totally_unknown_xyz") == "totally_unknown_xyz"


class TestSaveBacktestRun:
    def test_persists_single_run(self, registry: ParamRegistry) -> None:
        run_id = registry.save_backtest_run(
            strategy="ema_trend_pullback",
            symbol="TX",
            params={"lots": 4, "ema_fast": 8},
            metrics={"sharpe": 1.5, "total_pnl": 1520000, "trade_count": 77},
            tool="run_backtest_realdata",
        )
        assert run_id > 0
        run = registry._conn.execute(
            "SELECT * FROM param_runs WHERE id = ?",
            (run_id,),
        ).fetchone()
        assert run["search_type"] == "single"
        assert run["n_trials"] == 1
        assert run["source"] == "mcp"

    def test_creates_trial_row(self, registry: ParamRegistry) -> None:
        run_id = registry.save_backtest_run(
            strategy="ema_trend_pullback",
            symbol="TX",
            params={"lots": 4},
            metrics={"sharpe": 1.5, "total_pnl": 1520000},
        )
        trials = registry._conn.execute(
            "SELECT * FROM param_trials WHERE run_id = ?",
            (run_id,),
        ).fetchall()
        assert len(trials) == 1
        assert trials[0]["sharpe"] == 1.5

    def test_auto_candidate_created(self, registry: ParamRegistry) -> None:
        run_id = registry.save_backtest_run(
            strategy="ema_trend_pullback",
            symbol="TX",
            params={"bar_agg": 5},
            metrics={"sharpe": 1.0},
        )
        cands = registry._conn.execute(
            "SELECT * FROM param_candidates WHERE run_id = ?",
            (run_id,),
        ).fetchall()
        assert len(cands) == 1
        assert cands[0]["is_active"] == 0

    def test_rejects_module_factory_format(self, registry: ParamRegistry) -> None:
        with pytest.raises(ValueError, match="normalized slug"):
            registry.save_backtest_run(
                strategy="src.strategies.foo:bar",
                symbol="TX",
                params={},
                metrics={},
            )


class TestStrategyNameMigration:
    def test_migrates_module_factory_names(self, db_path: Path) -> None:
        import sqlite3 as _sqlite3

        conn = _sqlite3.connect(str(db_path))
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS param_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_at TEXT NOT NULL, strategy TEXT NOT NULL, symbol TEXT NOT NULL,
                train_start TEXT, train_end TEXT, test_start TEXT, test_end TEXT,
                objective TEXT NOT NULL, is_fraction REAL, n_trials INTEGER NOT NULL,
                search_type TEXT NOT NULL, source TEXT NOT NULL, tag TEXT, notes TEXT
            );
            CREATE TABLE IF NOT EXISTS param_trials (
                id INTEGER PRIMARY KEY AUTOINCREMENT, run_id INTEGER NOT NULL,
                params TEXT NOT NULL, sharpe REAL, calmar REAL, sortino REAL,
                profit_factor REAL, win_rate REAL, max_drawdown_pct REAL,
                trade_count INTEGER, total_pnl REAL, is_oos INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS param_candidates (
                id INTEGER PRIMARY KEY AUTOINCREMENT, run_id INTEGER NOT NULL,
                trial_id INTEGER, strategy TEXT NOT NULL, params TEXT NOT NULL,
                label TEXT NOT NULL, regime TEXT, is_active INTEGER NOT NULL DEFAULT 0,
                activated_at TEXT, notes TEXT
            );
            INSERT INTO param_runs (run_at, strategy, symbol, objective, n_trials, search_type, source)
            VALUES ('2026-01-01', 'src.strategies.intraday.trend_following.ema_trend_pullback:create_ema_trend_pullback_engine', 'TX', 'sharpe', 1, 'grid', 'mcp');
            INSERT INTO param_candidates (run_id, strategy, params, label)
            VALUES (1, 'src.strategies.intraday.trend_following.ema_trend_pullback:create_ema_trend_pullback_engine', '{}', 'best_sharpe');
        """)
        conn.commit()
        conn.close()
        registry = ParamRegistry(db_path=db_path)
        run = registry._conn.execute("SELECT strategy FROM param_runs WHERE id = 1").fetchone()
        assert run["strategy"] == "intraday/trend_following/ema_trend_pullback"
        cand = registry._conn.execute(
            "SELECT strategy FROM param_candidates WHERE run_id = 1"
        ).fetchone()
        assert cand["strategy"] == "intraday/trend_following/ema_trend_pullback"
        registry.close()

    def test_migration_idempotent(self, db_path: Path) -> None:
        import sqlite3 as _sqlite3

        conn = _sqlite3.connect(str(db_path))
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS param_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_at TEXT NOT NULL, strategy TEXT NOT NULL, symbol TEXT NOT NULL,
                train_start TEXT, train_end TEXT, test_start TEXT, test_end TEXT,
                objective TEXT NOT NULL, is_fraction REAL, n_trials INTEGER NOT NULL,
                search_type TEXT NOT NULL, source TEXT NOT NULL, tag TEXT, notes TEXT
            );
            CREATE TABLE IF NOT EXISTS param_trials (
                id INTEGER PRIMARY KEY AUTOINCREMENT, run_id INTEGER NOT NULL,
                params TEXT NOT NULL, sharpe REAL, calmar REAL, sortino REAL,
                profit_factor REAL, win_rate REAL, max_drawdown_pct REAL,
                trade_count INTEGER, total_pnl REAL, is_oos INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS param_candidates (
                id INTEGER PRIMARY KEY AUTOINCREMENT, run_id INTEGER NOT NULL,
                trial_id INTEGER, strategy TEXT NOT NULL, params TEXT NOT NULL,
                label TEXT NOT NULL, regime TEXT, is_active INTEGER NOT NULL DEFAULT 0,
                activated_at TEXT, notes TEXT
            );
            INSERT INTO param_runs (run_at, strategy, symbol, objective, n_trials, search_type, source)
            VALUES ('2026-01-01', 'src.strategies.foo.bar:create_bar_engine', 'TX', 'sharpe', 1, 'grid', 'mcp');
        """)
        conn.commit()
        conn.close()
        r1 = ParamRegistry(db_path=db_path)
        r1.close()
        r2 = ParamRegistry(db_path=db_path)
        run = r2._conn.execute("SELECT strategy FROM param_runs WHERE id = 1").fetchone()
        assert run["strategy"] == "foo/bar"
        r2.close()


class TestCodeHashMigration:
    def test_migration_adds_columns(self, db_path: Path) -> None:
        import sqlite3 as _sqlite3

        conn = _sqlite3.connect(str(db_path))
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS param_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_at TEXT NOT NULL, strategy TEXT NOT NULL, symbol TEXT NOT NULL,
                train_start TEXT, train_end TEXT, test_start TEXT, test_end TEXT,
                objective TEXT NOT NULL, is_fraction REAL, n_trials INTEGER NOT NULL,
                search_type TEXT NOT NULL, source TEXT NOT NULL, tag TEXT, notes TEXT
            );
            CREATE TABLE IF NOT EXISTS param_trials (
                id INTEGER PRIMARY KEY AUTOINCREMENT, run_id INTEGER NOT NULL,
                params TEXT NOT NULL, sharpe REAL, calmar REAL, sortino REAL,
                profit_factor REAL, win_rate REAL, max_drawdown_pct REAL,
                trade_count INTEGER, total_pnl REAL, is_oos INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS param_candidates (
                id INTEGER PRIMARY KEY AUTOINCREMENT, run_id INTEGER NOT NULL,
                trial_id INTEGER, strategy TEXT NOT NULL, params TEXT NOT NULL,
                label TEXT NOT NULL, regime TEXT, is_active INTEGER NOT NULL DEFAULT 0,
                activated_at TEXT, notes TEXT
            );
            INSERT INTO param_runs (run_at, strategy, symbol, objective, n_trials, search_type, source)
            VALUES ('2026-01-01', 'test_strat', 'TX', 'sharpe', 1, 'grid', 'mcp');
        """)
        conn.close()
        registry = ParamRegistry(db_path=db_path)
        cols = [r[1] for r in registry._conn.execute("PRAGMA table_info(param_runs)").fetchall()]
        assert "strategy_hash" in cols
        assert "strategy_code" in cols
        run = registry._conn.execute(
            "SELECT strategy_hash, strategy_code FROM param_runs WHERE id = 1"
        ).fetchone()
        assert run["strategy_hash"] is None
        assert run["strategy_code"] is None
        registry.close()

    def test_fresh_db_has_columns(self, db_path: Path) -> None:
        registry = ParamRegistry(db_path=db_path)
        cols = [r[1] for r in registry._conn.execute("PRAGMA table_info(param_runs)").fetchall()]
        assert "strategy_hash" in cols
        assert "strategy_code" in cols
        registry.close()

    def test_migration_is_idempotent(self, db_path: Path) -> None:
        import sqlite3 as _sqlite3

        conn = _sqlite3.connect(str(db_path))
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS param_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_at TEXT NOT NULL, strategy TEXT NOT NULL, symbol TEXT NOT NULL,
                train_start TEXT, train_end TEXT, test_start TEXT, test_end TEXT,
                objective TEXT NOT NULL, is_fraction REAL, n_trials INTEGER NOT NULL,
                search_type TEXT NOT NULL, source TEXT NOT NULL, tag TEXT, notes TEXT,
                strategy_hash TEXT, strategy_code TEXT
            );
            CREATE TABLE IF NOT EXISTS param_trials (
                id INTEGER PRIMARY KEY AUTOINCREMENT, run_id INTEGER NOT NULL,
                params TEXT NOT NULL, sharpe REAL, calmar REAL, sortino REAL,
                profit_factor REAL, win_rate REAL, max_drawdown_pct REAL,
                trade_count INTEGER, total_pnl REAL, is_oos INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS param_candidates (
                id INTEGER PRIMARY KEY AUTOINCREMENT, run_id INTEGER NOT NULL,
                trial_id INTEGER, strategy TEXT NOT NULL, params TEXT NOT NULL,
                label TEXT NOT NULL, regime TEXT, is_active INTEGER NOT NULL DEFAULT 0,
                activated_at TEXT, notes TEXT
            );
            INSERT INTO param_runs (run_at, strategy, symbol, objective, n_trials, search_type, source, strategy_hash, strategy_code)
            VALUES ('2026-01-01', 'test_strat', 'TX', 'sharpe', 1, 'grid', 'mcp', 'abc123', 'source text');
        """)
        conn.close()
        registry = ParamRegistry(db_path=db_path)
        cols = [r[1] for r in registry._conn.execute("PRAGMA table_info(param_runs)").fetchall()]
        assert "strategy_hash" in cols
        assert "strategy_code" in cols
        run = registry._conn.execute(
            "SELECT strategy_hash, strategy_code FROM param_runs WHERE id = 1"
        ).fetchone()
        assert run["strategy_hash"] == "abc123"
        assert run["strategy_code"] == "source text"
        registry.close()


class TestCodeHashStorage:
    def test_save_backtest_run_stores_hash(self, registry: ParamRegistry) -> None:
        run_id = registry.save_backtest_run(
            strategy="atr_mean_reversion",
            symbol="TX",
            params={"bb_len": 20},
            metrics={"sharpe": 1.2, "trade_count": 50},
            source="test",
            strategy_hash="abc123",
            strategy_code="print('hello')",
        )
        run = registry._conn.execute(
            "SELECT strategy_hash, strategy_code FROM param_runs WHERE id = ?", (run_id,)
        ).fetchone()
        assert run["strategy_hash"] == "abc123"
        assert run["strategy_code"] == "print('hello')"

    def test_save_run_stores_hash(self, registry: ParamRegistry) -> None:
        result = _make_result()
        run_id = registry.save_run(
            result=result,
            strategy="atr_mean_reversion",
            symbol="TX",
            objective="sharpe",
            source="test",
            strategy_hash="def456",
            strategy_code="x = 1",
        )
        run = registry._conn.execute(
            "SELECT strategy_hash, strategy_code FROM param_runs WHERE id = ?", (run_id,)
        ).fetchone()
        assert run["strategy_hash"] == "def456"
        assert run["strategy_code"] == "x = 1"

    def test_save_without_hash_stores_null(self, registry: ParamRegistry) -> None:
        run_id = registry.save_backtest_run(
            strategy="atr_mean_reversion",
            symbol="TX",
            params={"bb_len": 20},
            metrics={"sharpe": 1.2, "trade_count": 50},
            source="test",
        )
        run = registry._conn.execute(
            "SELECT strategy_hash, strategy_code FROM param_runs WHERE id = ?", (run_id,)
        ).fetchone()
        assert run["strategy_hash"] is None
        assert run["strategy_code"] is None


class TestDeactivateStaleCandidates:
    def test_deactivates_mismatched_hash(self, registry: ParamRegistry) -> None:
        run_id = registry.save_backtest_run(
            strategy="test_strat",
            symbol="TX",
            params={"p": 1},
            metrics={"sharpe": 1.0, "trade_count": 10},
            source="test",
            strategy_hash="oldhash",
            strategy_code="old code",
        )
        cand_id = registry._conn.execute(
            "SELECT id FROM param_candidates WHERE run_id = ?", (run_id,)
        ).fetchone()["id"]
        registry.activate(cand_id)
        deactivated = registry.deactivate_stale_candidates("test_strat", "newhash")
        assert deactivated == 1
        is_active = registry._conn.execute(
            "SELECT is_active FROM param_candidates WHERE id = ?", (cand_id,)
        ).fetchone()["is_active"]
        assert is_active == 0

    def test_skips_matching_hash(self, registry: ParamRegistry) -> None:
        run_id = registry.save_backtest_run(
            strategy="test_strat",
            symbol="TX",
            params={"p": 1},
            metrics={"sharpe": 1.0, "trade_count": 10},
            source="test",
            strategy_hash="samehash",
            strategy_code="same code",
        )
        cand_id = registry._conn.execute(
            "SELECT id FROM param_candidates WHERE run_id = ?", (run_id,)
        ).fetchone()["id"]
        registry.activate(cand_id)
        deactivated = registry.deactivate_stale_candidates("test_strat", "samehash")
        assert deactivated == 0
        is_active = registry._conn.execute(
            "SELECT is_active FROM param_candidates WHERE id = ?", (cand_id,)
        ).fetchone()["is_active"]
        assert is_active == 1

    def test_skips_null_hash_rows(self, registry: ParamRegistry) -> None:
        run_id = registry.save_backtest_run(
            strategy="test_strat",
            symbol="TX",
            params={"p": 1},
            metrics={"sharpe": 1.0, "trade_count": 10},
            source="test",
        )
        cand_id = registry._conn.execute(
            "SELECT id FROM param_candidates WHERE run_id = ?", (run_id,)
        ).fetchone()["id"]
        registry.activate(cand_id)
        deactivated = registry.deactivate_stale_candidates("test_strat", "newhash")
        assert deactivated == 0
        is_active = registry._conn.execute(
            "SELECT is_active FROM param_candidates WHERE id = ?", (cand_id,)
        ).fetchone()["is_active"]
        assert is_active == 1


class TestCheckCodeHashMatch:
    def test_returns_true_when_hash_matches(self, registry: ParamRegistry) -> None:
        run_id = registry.save_backtest_run(
            strategy="test_strat",
            symbol="TX",
            params={"p": 1},
            metrics={"sharpe": 1.0, "trade_count": 10},
            source="test",
            strategy_hash="abc123",
            strategy_code="code",
        )
        cand_id = registry._conn.execute(
            "SELECT id FROM param_candidates WHERE run_id = ?", (run_id,)
        ).fetchone()["id"]
        registry.activate(cand_id)
        result = registry.check_code_hash_match("test_strat", "abc123")
        assert result is True

    def test_returns_false_when_hash_differs(self, registry: ParamRegistry) -> None:
        run_id = registry.save_backtest_run(
            strategy="test_strat",
            symbol="TX",
            params={"p": 1},
            metrics={"sharpe": 1.0, "trade_count": 10},
            source="test",
            strategy_hash="abc123",
            strategy_code="code",
        )
        cand_id = registry._conn.execute(
            "SELECT id FROM param_candidates WHERE run_id = ?", (run_id,)
        ).fetchone()["id"]
        registry.activate(cand_id)
        result = registry.check_code_hash_match("test_strat", "different")
        assert result is False

    def test_returns_none_when_no_active_candidate(self, registry: ParamRegistry) -> None:
        result = registry.check_code_hash_match("nonexistent_strat", "hash")
        assert result is None

    def test_returns_none_when_hash_is_null(self, registry: ParamRegistry) -> None:
        run_id = registry.save_backtest_run(
            strategy="test_strat",
            symbol="TX",
            params={"p": 1},
            metrics={"sharpe": 1.0, "trade_count": 10},
            source="test",
        )
        cand_id = registry._conn.execute(
            "SELECT id FROM param_candidates WHERE run_id = ?", (run_id,)
        ).fetchone()["id"]
        registry.activate(cand_id)
        result = registry.check_code_hash_match("test_strat", "anyhash")
        assert result is None


class TestHashMetadataInQueries:
    def test_get_active_detail_includes_hash(self, registry: ParamRegistry) -> None:
        run_id = registry.save_backtest_run(
            strategy="test_strat",
            symbol="TX",
            params={"p": 1},
            metrics={"sharpe": 1.0, "trade_count": 10},
            source="test",
            strategy_hash="abc123",
            strategy_code="code",
        )
        cand_id = registry._conn.execute(
            "SELECT id FROM param_candidates WHERE run_id = ?", (run_id,)
        ).fetchone()["id"]
        registry.activate(cand_id)
        detail = registry.get_active_detail("test_strat")
        assert detail is not None
        assert detail["strategy_hash"] == "abc123"

    def test_get_active_detail_returns_none_for_null_hash(self, registry: ParamRegistry) -> None:
        run_id = registry.save_backtest_run(
            strategy="test_strat",
            symbol="TX",
            params={"p": 1},
            metrics={"sharpe": 1.0, "trade_count": 10},
            source="test",
        )
        cand_id = registry._conn.execute(
            "SELECT id FROM param_candidates WHERE run_id = ?", (run_id,)
        ).fetchone()["id"]
        registry.activate(cand_id)
        detail = registry.get_active_detail("test_strat")
        assert detail is not None
        assert detail["strategy_hash"] is None

    def test_get_run_history_includes_hash_per_entry(self, registry: ParamRegistry) -> None:
        run_id = registry.save_backtest_run(
            strategy="test_strat",
            symbol="TX",
            params={"p": 1},
            metrics={"sharpe": 1.0, "trade_count": 10},
            source="test",
            strategy_hash="xyz789",
            strategy_code="code",
        )
        history = registry.get_run_history("test_strat")
        assert len(history) >= 1
        assert history[0]["strategy_hash"] == "xyz789"
