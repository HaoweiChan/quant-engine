"""Unit tests for PortfolioStore walk-forward persistence + allocation activation."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from src.core.portfolio_store import PortfolioStore


def _sample_optimization_result() -> dict[str, Any]:
    """Minimal payload matching what run_portfolio_optimization_for_mcp produces."""
    allocation = {
        "max_sharpe": {
            "objective": "max_sharpe",
            "weights": {"a": 0.5, "b": 0.5},
            "sharpe": 2.0, "total_return": 0.3, "annual_return": 0.25,
            "max_drawdown_pct": 0.05, "sortino": 2.5, "calmar": 5.0,
            "annual_vol": 0.12,
        },
        "max_return": {
            "objective": "max_return",
            "weights": {"a": 0.8, "b": 0.2},
            "sharpe": 1.5, "total_return": 0.4, "annual_return": 0.33,
            "max_drawdown_pct": 0.10, "sortino": 1.8, "calmar": 3.3,
            "annual_vol": 0.22,
        },
        "min_drawdown": {
            "objective": "min_drawdown",
            "weights": {"a": 0.3, "b": 0.7},
            "sharpe": 1.8, "total_return": 0.2, "annual_return": 0.17,
            "max_drawdown_pct": 0.03, "sortino": 2.2, "calmar": 5.7,
            "annual_vol": 0.09,
        },
        "risk_parity": {
            "objective": "risk_parity",
            "weights": {"a": 0.4, "b": 0.6},
            "sharpe": 1.9, "total_return": 0.25, "annual_return": 0.21,
            "max_drawdown_pct": 0.04, "sortino": 2.3, "calmar": 5.3,
            "annual_vol": 0.10,
        },
        "equal_weight": {
            "objective": "equal_weight",
            "weights": {"a": 0.5, "b": 0.5},
            "sharpe": 1.0, "total_return": 0.15, "annual_return": 0.13,
            "max_drawdown_pct": 0.08, "sortino": 1.2, "calmar": 1.6,
            "annual_vol": 0.16,
        },
    }
    return {
        "strategy_slugs": ["a", "b"],
        "correlation_matrix": [[1.0, 0.1], [0.1, 1.0]],
        "n_days": 252,
        **allocation,
    }


def _sample_walk_forward_result() -> dict[str, Any]:
    return {
        "per_fold": [
            {
                "fold_index": 0, "is_start_idx": 0, "is_end_idx": 100,
                "oos_start_idx": 100, "oos_end_idx": 150,
                "is_weights": {"a": 0.5, "b": 0.5}, "is_sharpe": 2.0,
                "oos_sharpe": 1.8, "oos_mdd_pct": 0.06,
                "oos_annual_return": 0.22, "oos_annual_vol": 0.12,
                "correlation_matrix": [[1.0, 0.2], [0.2, 1.0]],
            },
            {
                "fold_index": 1, "is_start_idx": 0, "is_end_idx": 150,
                "oos_start_idx": 150, "oos_end_idx": 200,
                "is_weights": {"a": 0.6, "b": 0.4}, "is_sharpe": 2.1,
                "oos_sharpe": 1.9, "oos_mdd_pct": 0.04,
                "oos_annual_return": 0.25, "oos_annual_vol": 0.13,
                "correlation_matrix": [[1.0, 0.15], [0.15, 1.0]],
            },
        ],
        "aggregate_oos_sharpe": 1.85,
        "aggregate_oos_mdd": 0.05,
        "worst_fold_oos_mdd": 0.06,
        "weight_drift_cv": 0.15,
        "correlation_stability": 0.92,
        "strategy_slugs": ["a", "b"],
        "objective": "max_sharpe",
        "n_folds_computed": 2,
        "thresholds_applied": {
            "aggregate_oos_sharpe_floor": 1.5,
            "worst_fold_oos_mdd_ceiling": 0.20,
        },
    }


@pytest.fixture
def store(tmp_path: Path) -> PortfolioStore:
    db_path = tmp_path / "test_portfolio_opt.db"
    return PortfolioStore(db_path=db_path)


class TestSaveOptimization:
    def test_round_trip(self, store: PortfolioStore) -> None:
        run_id = store.save_optimization(
            result=_sample_optimization_result(),
            symbol="TX",
            start="2024-01-01",
            end="2024-12-31",
            initial_capital=2_000_000,
            min_weight=0.1,
        )
        assert run_id == 1
        run = store.get_run(run_id)
        assert run is not None
        assert run["symbol"] == "TX"
        assert run["n_strategies"] == 2
        assert "max_sharpe" in run["allocations"]
        assert run["allocations"]["max_sharpe"]["is_selected"] == 0


class TestSelectAllocation:
    def test_selects_target_only(self, store: PortfolioStore) -> None:
        run_id = store.save_optimization(
            result=_sample_optimization_result(),
            symbol="TX", start="2024-01-01", end="2024-12-31",
            initial_capital=2_000_000, min_weight=0.1,
        )
        ok = store.select_allocation(run_id, "max_sharpe")
        assert ok is True
        selected = store.get_selected_allocation(run_id)
        assert selected is not None
        assert selected["objective"] == "max_sharpe"
        assert selected["weights"] == {"a": 0.5, "b": 0.5}
        assert selected["is_selected"] == 1
        # Switch selection
        store.select_allocation(run_id, "risk_parity")
        selected_rp = store.get_selected_allocation(run_id)
        assert selected_rp["objective"] == "risk_parity"
        # Only one selected at a time
        count = store._conn.execute(
            "SELECT COUNT(*) FROM portfolio_allocations WHERE run_id=? AND is_selected=1",
            (run_id,),
        ).fetchone()[0]
        assert count == 1

    def test_unknown_objective_returns_false(self, store: PortfolioStore) -> None:
        run_id = store.save_optimization(
            result=_sample_optimization_result(),
            symbol="TX", start="2024-01-01", end="2024-12-31",
            initial_capital=2_000_000, min_weight=0.1,
        )
        assert store.select_allocation(run_id, "nonsense") is False


class TestSaveWalkForward:
    def test_persists_with_run_id(self, store: PortfolioStore) -> None:
        run_id = store.save_optimization(
            result=_sample_optimization_result(),
            symbol="TX", start="2024-01-01", end="2024-12-31",
            initial_capital=2_000_000, min_weight=0.1,
        )
        wf_id = store.save_walk_forward(
            result=_sample_walk_forward_result(),
            symbol="TX", start="2024-01-01", end="2024-12-31",
            n_folds=2, oos_fraction=0.2, run_id=run_id,
        )
        assert wf_id == 1
        wf = store.get_walk_forward(wf_id)
        assert wf is not None
        assert wf["run_id"] == run_id
        assert wf["aggregate_oos_sharpe"] == pytest.approx(1.85)
        assert wf["n_folds_computed"] == 2
        assert wf["strategy_slugs"] == ["a", "b"]
        assert wf["thresholds_applied"]["aggregate_oos_sharpe_floor"] == 1.5
        assert len(wf["per_fold"]) == 2

    def test_persists_without_run_id(self, store: PortfolioStore) -> None:
        wf_id = store.save_walk_forward(
            result=_sample_walk_forward_result(),
            symbol="TX", start="2024-01-01", end="2024-12-31",
            n_folds=2, oos_fraction=0.2, run_id=None,
        )
        wf = store.get_walk_forward(wf_id)
        assert wf["run_id"] is None
        assert wf["symbol"] == "TX"

    def test_list_walk_forwards_filters(self, store: PortfolioStore) -> None:
        run_id = store.save_optimization(
            result=_sample_optimization_result(),
            symbol="TX", start="2024-01-01", end="2024-12-31",
            initial_capital=2_000_000, min_weight=0.1,
        )
        for _ in range(3):
            store.save_walk_forward(
                result=_sample_walk_forward_result(),
                symbol="TX", start="2024-01-01", end="2024-12-31",
                n_folds=2, oos_fraction=0.2, run_id=run_id,
            )
        store.save_walk_forward(
            result=_sample_walk_forward_result(),
            symbol="MTX", start="2024-01-01", end="2024-12-31",
            n_folds=2, oos_fraction=0.2, run_id=None,
        )
        assert len(store.list_walk_forwards()) == 4
        assert len(store.list_walk_forwards(run_id=run_id)) == 3
        assert len(store.list_walk_forwards(symbol="MTX")) == 1
        assert len(store.list_walk_forwards(symbol="TX", run_id=run_id)) == 3

    def test_get_run_attaches_walk_forward_summary(self, store: PortfolioStore) -> None:
        run_id = store.save_optimization(
            result=_sample_optimization_result(),
            symbol="TX", start="2024-01-01", end="2024-12-31",
            initial_capital=2_000_000, min_weight=0.1,
        )
        store.save_walk_forward(
            result=_sample_walk_forward_result(),
            symbol="TX", start="2024-01-01", end="2024-12-31",
            n_folds=2, oos_fraction=0.2, run_id=run_id,
        )
        run = store.get_run(run_id)
        assert "walk_forwards" in run
        assert len(run["walk_forwards"]) == 1
        summary = run["walk_forwards"][0]
        assert summary["aggregate_oos_sharpe"] == pytest.approx(1.85)
        assert summary["n_folds_computed"] == 2
