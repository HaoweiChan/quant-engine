"""Tests for the backtest MCP server modules."""
from __future__ import annotations

import pytest
import textwrap

from pathlib import Path

from src.mcp_server.validation import (
    backup_strategy_file,
    list_strategy_files,
    validate_strategy_content,
)
from src.mcp_server.history import OptimizationHistory

# ---------------------------------------------------------------------------
# 7.1 — validate_strategy_content
# ---------------------------------------------------------------------------

class TestValidateStrategyContent:
    def test_valid_content_passes(self):
        code = "x = 1 + 2\nprint(x)"
        result = validate_strategy_content(code, "test.py")
        assert result.valid is True
        assert result.errors == []

    def test_syntax_error_caught(self):
        code = "def foo(\n"
        result = validate_strategy_content(code, "test.py")
        assert result.valid is False
        assert any("Syntax error" in e for e in result.errors)

    def test_forbidden_import_caught(self):
        for mod in ("os", "sys", "subprocess", "socket", "requests", "shutil"):
            code = f"import {mod}\nprint(1)"
            result = validate_strategy_content(code, "test.py")
            assert result.valid is False, f"import {mod} should be rejected"
            assert any(f"Forbidden import: {mod}" in e for e in result.errors)

    def test_forbidden_from_import_caught(self):
        code = "from subprocess import run\nrun(['ls'])"
        result = validate_strategy_content(code, "test.py")
        assert result.valid is False
        assert any("Forbidden import: subprocess" in e for e in result.errors)

    def test_forbidden_from_os_path(self):
        code = "from os.path import join\nprint(join('a', 'b'))"
        result = validate_strategy_content(code, "test.py")
        assert result.valid is False
        assert any("Forbidden import: os" in e for e in result.errors)

    def test_missing_abc_method_caught(self):
        code = textwrap.dedent("""\
            from src.core.policies import StopPolicy

            class MyStop(StopPolicy):
                def initial_stop(self, entry_price, direction, snapshot):
                    return entry_price - 100
        """)
        result = validate_strategy_content(code, "test.py")
        assert result.valid is False
        assert any("update_stop" in e for e in result.errors)

    def test_valid_policy_passes(self):
        code = textwrap.dedent("""\
            from src.core.policies import EntryPolicy

            class MyEntry(EntryPolicy):
                def should_enter(self, snapshot, signal, engine_state):
                    return None
        """)
        result = validate_strategy_content(code, "test.py")
        assert result.valid is True

    def test_allowed_imports_pass(self):
        code = "import math\nimport json\nfrom collections import deque"
        result = validate_strategy_content(code, "test.py")
        assert result.valid is True


# ---------------------------------------------------------------------------
# 7.2 — backup_strategy_file
# ---------------------------------------------------------------------------

class TestBackupStrategyFile:
    def test_backup_is_no_op(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        strategies_dir = tmp_path / "strategies"
        strategies_dir.mkdir()
        (strategies_dir / "test_strat.py").write_text("# original")
        monkeypatch.setattr("src.mcp_server.validation._STRATEGIES_DIR", strategies_dir)

        result = backup_strategy_file("test_strat")
        assert result is None

    def test_returns_none_for_new_file(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        strategies_dir = tmp_path / "strategies"
        strategies_dir.mkdir()
        monkeypatch.setattr("src.mcp_server.validation._STRATEGIES_DIR", strategies_dir)

        result = backup_strategy_file("nonexistent")
        assert result is None


# ---------------------------------------------------------------------------
# 7.3 — list_strategy_files
# ---------------------------------------------------------------------------

class TestListStrategyFiles:
    def test_lists_correct_files(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        strategies_dir = tmp_path / "strategies"
        strategies_dir.mkdir()
        (strategies_dir / "__init__.py").write_text("")
        (strategies_dir / "entry.py").write_text("# entry")
        (strategies_dir / "stop.py").write_text("# stop policy code")
        monkeypatch.setattr("src.mcp_server.validation._STRATEGIES_DIR", strategies_dir)

        files = list_strategy_files()
        names = [f["filename"] for f in files]
        assert "entry" in names
        assert "stop" in names
        assert "__init__" not in names

    def test_excludes_init(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        strategies_dir = tmp_path / "strategies"
        strategies_dir.mkdir()
        (strategies_dir / "__init__.py").write_text("")
        monkeypatch.setattr("src.mcp_server.validation._STRATEGIES_DIR", strategies_dir)

        files = list_strategy_files()
        assert len(files) == 0

    def test_empty_dir(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        strategies_dir = tmp_path / "strategies"
        strategies_dir.mkdir()
        monkeypatch.setattr("src.mcp_server.validation._STRATEGIES_DIR", strategies_dir)

        files = list_strategy_files()
        assert files == []


# ---------------------------------------------------------------------------
# 7.4 — OptimizationHistory
# ---------------------------------------------------------------------------

class TestOptimizationHistory:
    def test_empty_history(self):
        h = OptimizationHistory()
        assert h.count == 0
        assert h.get_all() == []

    def test_append_and_count(self):
        h = OptimizationHistory()
        h.append("run_backtest", {"stop": 1.5}, {"sharpe": 0.8}, "strong_bull")
        h.append("run_mc", {"stop": 2.0}, {"sharpe": 1.2}, "bear")
        assert h.count == 2

    def test_get_all_sorted_by_sharpe(self):
        h = OptimizationHistory()
        h.append("t1", {}, {"sharpe": 0.5}, "s1")
        h.append("t2", {}, {"sharpe": 1.5}, "s2")
        h.append("t3", {}, {"sharpe": 1.0}, "s3")
        runs = h.get_all(sort_by="sharpe")
        sharpes = [r["metrics"]["sharpe"] for r in runs]
        assert sharpes == [1.5, 1.0, 0.5]

    def test_entries_have_timestamp(self):
        h = OptimizationHistory()
        h.append("test", {}, {"sharpe": 1.0}, "strong_bull")
        runs = h.get_all()
        assert "timestamp" in runs[0]
        assert runs[0]["tool"] == "test"

    def test_session_scoped(self):
        h1 = OptimizationHistory()
        h1.append("t", {}, {"sharpe": 1.0}, "s")
        h2 = OptimizationHistory()
        assert h2.count == 0

    def test_append_supports_data_provenance(self):
        h = OptimizationHistory()
        h.append(
            "run_parameter_sweep",
            {"stop_atr_mult": 1.5},
            {"sharpe": 1.1},
            "real:TX:2025-01-01:2025-06-30",
            data_source="real",
            source_label="real:TX:2025-01-01:2025-06-30",
            termination_eligible=True,
        )
        run = h.get_all()[0]
        assert run["data_source"] == "real"
        assert run["source_label"].startswith("real:TX:")
        assert run["termination_eligible"] is True


# ---------------------------------------------------------------------------
# 7.5 — Facade functions
# ---------------------------------------------------------------------------

class TestFacade:
    def test_run_backtest_returns_expected_keys(self):
        from src.mcp_server.facade import run_backtest_for_mcp
        result = run_backtest_for_mcp("strong_bull")
        assert "scenario" in result
        assert "metrics" in result
        assert "trade_count" in result
        assert "total_pnl" in result
        assert result["scenario"] == "strong_bull"
        assert result["data_source"] == "synthetic"
        assert result["termination_eligible"] is False
        assert result["termination_block_reason"] == "synthetic_data"

    def test_run_backtest_invalid_scenario(self):
        from src.mcp_server.facade import run_backtest_for_mcp
        with pytest.raises(ValueError, match="Unknown scenario"):
            run_backtest_for_mcp("nonexistent_scenario")

    def test_run_monte_carlo_clamps_n_paths(self):
        from src.mcp_server.facade import run_monte_carlo_for_mcp
        result = run_monte_carlo_for_mcp("strong_bull", n_paths=5000)
        assert result["n_paths"] == 1000
        assert "warning" in result

    def test_run_monte_carlo_returns_distribution(self):
        from src.mcp_server.facade import run_monte_carlo_for_mcp
        result = run_monte_carlo_for_mcp("strong_bull", n_paths=10)
        assert "percentiles" in result
        assert "win_rate" in result
        assert "ruin_probability" in result
        assert result["n_paths"] == 10
        assert result["data_source"] == "synthetic"
        assert result["termination_eligible"] is False
        assert result["termination_block_reason"] == "synthetic_data"

    def test_run_sweep_rejects_too_many_params(self):
        from src.mcp_server.facade import run_sweep_for_mcp
        result = run_sweep_for_mcp(
            base_params={"max_loss": 500_000},
            sweep_params={
                "a": [1, 2], "b": [1, 2], "c": [1, 2], "d": [1, 2],
            },
        )
        assert "error" in result
        assert "Too many sweep parameters" in result["error"]

    def test_run_sweep_research_includes_gate_fields(self):
        from src.mcp_server.facade import run_sweep_for_mcp

        result = run_sweep_for_mcp(
            base_params={"max_loss": 500_000},
            sweep_params={"stop_atr_mult": [1.0, 1.5]},
            strategy="pyramid",
            mode="research",
            metric="sharpe",
            require_real_data=False,
        )
        assert result["mode"] == "research"
        assert "gate_results" in result
        assert "gate_details" in result
        assert result["auto_activation_disabled"] is True
        assert result["termination_eligible"] is False
        assert result["termination_block_reason"] == "synthetic_data"

    def test_run_sweep_production_requires_real_data_bounds(self):
        from src.mcp_server.facade import run_sweep_for_mcp

        result = run_sweep_for_mcp(
            base_params={"max_loss": 500_000},
            sweep_params={"stop_atr_mult": [1.0, 1.5]},
            strategy="pyramid",
            mode="production_intent",
        )
        assert "error" in result
        assert "requires symbol, start, and end" in result["error"]

    def test_factory_resolution_pyramid(self):
        from src.mcp_server.facade import resolve_factory
        f = resolve_factory("pyramid")
        assert callable(f)

    def test_factory_resolution_atr_mr(self):
        from src.mcp_server.facade import resolve_factory
        f = resolve_factory("atr_mean_reversion")
        assert callable(f)

    def test_factory_resolution_unknown(self):
        from src.mcp_server.facade import resolve_factory
        with pytest.raises(ValueError, match="Unknown strategy"):
            resolve_factory("nonexistent")

    def test_parameter_schema_pyramid(self):
        from src.mcp_server.facade import get_strategy_parameter_schema
        schema = get_strategy_parameter_schema("pyramid")
        assert schema["strategy"] == "daily/trend_following/pyramid_wrapper"
        assert "parameters" in schema
        assert "stop_atr_mult" in schema["parameters"]
        assert "scenarios" in schema

    def test_stress_test_returns_results(self):
        from src.mcp_server.facade import run_stress_for_mcp
        result = run_stress_for_mcp(scenarios=["gap_down"])
        assert "results" in result
        assert len(result["results"]) == 1
        assert result["results"][0]["scenario"] == "gap_down"

    def test_stress_test_invalid_scenario(self):
        from src.mcp_server.facade import run_stress_for_mcp
        result = run_stress_for_mcp(scenarios=["nonexistent"])
        assert "error" in result


# ---------------------------------------------------------------------------
# 7.6 — Integration: tool registration
# ---------------------------------------------------------------------------

class TestToolRegistration:
    def test_tools_list_has_correct_count(self):
        from src.mcp_server.tools import TOOLS
        assert len(TOOLS) == 13

    def test_all_tools_have_names_and_schemas(self):
        from src.mcp_server.tools import TOOLS
        expected_names = {
            "run_backtest", "run_monte_carlo", "run_parameter_sweep",
            "run_stress_test", "read_strategy_file", "write_strategy_file",
            "get_optimization_history", "get_parameter_schema",
            "get_active_params", "run_backtest_realdata",
            "scaffold_strategy", "get_run_history", "activate_candidate",
        }
        actual_names = {t.name for t in TOOLS}
        assert actual_names == expected_names
        for tool in TOOLS:
            assert tool.inputSchema is not None
            assert tool.description

    def test_parameter_sweep_tool_defaults_to_production_intent(self):
        from src.mcp_server.tools import TOOLS

        sweep_tool = next(t for t in TOOLS if t.name == "run_parameter_sweep")
        mode_schema = sweep_tool.inputSchema["properties"]["mode"]
        assert mode_schema["default"] == "production_intent"

    def test_server_creates_successfully(self):
        from src.mcp_server.server import app
        assert app.name == "backtest-engine"
