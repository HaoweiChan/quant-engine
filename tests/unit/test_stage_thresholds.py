"""Unit tests for multi-stage quality thresholds and hardware-aware resource detection."""

from __future__ import annotations

import os
import tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from src.strategies import (
    HoldingPeriod,
    OptimizationLevel,
    StageThresholds,
    get_quality_thresholds,
    get_stage_thresholds,
    get_thresholds_for_strategy,
    read_optimization_level,
    write_optimization_level,
)


# ---------------------------------------------------------------------------
# StageThresholds data model
# ---------------------------------------------------------------------------

class TestStageThresholds:
    """Verify all 9 (period x level) combos return correct values."""

    @pytest.mark.parametrize("period", list(HoldingPeriod))
    @pytest.mark.parametrize("level", [
        OptimizationLevel.L1_EXPLORATORY,
        OptimizationLevel.L2_VALIDATED,
        OptimizationLevel.L3_PRODUCTION,
    ])
    def test_all_combos_exist(self, period: HoldingPeriod, level: OptimizationLevel) -> None:
        st = get_stage_thresholds(period, level)
        assert isinstance(st, StageThresholds)
        assert st.holding_period == period
        assert st.optimization_level == level

    def test_l0_raises(self) -> None:
        with pytest.raises(ValueError, match="L0_UNOPTIMIZED"):
            get_stage_thresholds(HoldingPeriod.SHORT_TERM, OptimizationLevel.L0_UNOPTIMIZED)

    def test_swing_l1_is_most_lenient(self) -> None:
        st = get_stage_thresholds(HoldingPeriod.SWING, OptimizationLevel.L1_EXPLORATORY)
        assert st.sharpe_floor == 0.4
        assert st.min_trade_count == 10
        assert st.mdd_max_pct is None  # no hard gate at L1

    def test_short_term_l2_is_strictest_l2(self) -> None:
        st = get_stage_thresholds(HoldingPeriod.SHORT_TERM, OptimizationLevel.L2_VALIDATED)
        assert st.sharpe_floor == 1.0
        assert st.min_trade_count == 100
        assert st.mdd_max_pct == 10.0

    def test_l3_adds_slippage_stress(self) -> None:
        for period in HoldingPeriod:
            l2 = get_stage_thresholds(period, OptimizationLevel.L2_VALIDATED)
            l3 = get_stage_thresholds(period, OptimizationLevel.L3_PRODUCTION)
            assert l2.slippage_stress_sharpe is None
            assert l3.slippage_stress_sharpe is not None
            assert l3.slippage_stress_sharpe > 0

    def test_to_dict_roundtrip(self) -> None:
        st = get_stage_thresholds(HoldingPeriod.MEDIUM_TERM, OptimizationLevel.L2_VALIDATED)
        d = st.to_dict()
        assert d["holding_period"] == "medium_term"
        assert d["optimization_level"] == 2
        assert d["sharpe_floor"] == 0.8
        assert d["min_trade_count"] == 30
        assert "win_rate_min" in d
        assert "win_rate_max" in d

    def test_progressive_strictness(self) -> None:
        """L1 < L2 <= L3 in strictness for each period."""
        for period in HoldingPeriod:
            l1 = get_stage_thresholds(period, OptimizationLevel.L1_EXPLORATORY)
            l2 = get_stage_thresholds(period, OptimizationLevel.L2_VALIDATED)
            assert l1.sharpe_floor <= l2.sharpe_floor
            assert l1.min_trade_count <= l2.min_trade_count
            assert l1.profit_factor_floor <= l2.profit_factor_floor


# ---------------------------------------------------------------------------
# Backward compatibility: get_quality_thresholds
# ---------------------------------------------------------------------------

class TestLegacyBackwardCompat:
    def test_returns_same_shape(self) -> None:
        old = get_quality_thresholds(HoldingPeriod.SHORT_TERM)
        assert "win_rate" in old
        assert "profit_factor" in old
        assert "max_drawdown" in old
        assert isinstance(old["win_rate"], tuple)
        assert len(old["win_rate"]) == 2

    def test_short_term_matches_l2(self) -> None:
        old = get_quality_thresholds(HoldingPeriod.SHORT_TERM)
        l2 = get_stage_thresholds(HoldingPeriod.SHORT_TERM, OptimizationLevel.L2_VALIDATED)
        assert old["win_rate"] == l2.win_rate
        assert old["profit_factor"][0] == l2.profit_factor_floor


# ---------------------------------------------------------------------------
# TOML persistence
# ---------------------------------------------------------------------------

class TestTomlPersistence:
    def test_read_nonexistent_returns_l0(self) -> None:
        level, gates = read_optimization_level("nonexistent_xyz_abc")
        assert level == OptimizationLevel.L0_UNOPTIMIZED
        assert gates == {}

    def test_write_and_read_roundtrip(self, tmp_path: Path) -> None:
        with patch("src.strategies._CONFIG_STRATEGIES_DIR", tmp_path):
            write_optimization_level(
                "short_term/breakout/test_strat",
                OptimizationLevel.L2_VALIDATED,
                {"sharpe": 1.2, "trades_per_fold": 145},
                holding_period=HoldingPeriod.SHORT_TERM,
            )
            level, gates = read_optimization_level("short_term/breakout/test_strat")
            assert level == OptimizationLevel.L2_VALIDATED
            assert gates["sharpe"] == 1.2
            assert gates["trades_per_fold"] == 145

    def test_slug_flattening(self, tmp_path: Path) -> None:
        with patch("src.strategies._CONFIG_STRATEGIES_DIR", tmp_path):
            path = write_optimization_level(
                "medium_term/trend_following/ema",
                OptimizationLevel.L1_EXPLORATORY,
                {},
            )
            assert path.name == "mt_ema.toml"

    def test_preserves_existing_sections(self, tmp_path: Path) -> None:
        """Writing optimization should not clobber other TOML sections."""
        import tomli_w

        toml_path = tmp_path / "st_test.toml"
        # Pre-populate with a [params] section
        with open(toml_path, "wb") as f:
            tomli_w.dump({"params": {"stop_atr_mult": 1.5}}, f)

        with patch("src.strategies._CONFIG_STRATEGIES_DIR", tmp_path):
            write_optimization_level(
                "st_test",
                OptimizationLevel.L1_EXPLORATORY,
                {"sharpe": 0.6},
            )

        try:
            import tomllib
        except ModuleNotFoundError:
            import tomli as tomllib  # type: ignore[no-redef]

        with open(toml_path, "rb") as f:
            data = tomllib.load(f)

        assert data["params"]["stop_atr_mult"] == 1.5
        assert data["optimization"]["level"] == 1


# ---------------------------------------------------------------------------
# get_thresholds_for_strategy
# ---------------------------------------------------------------------------

class TestGetThresholdsForStrategy:
    def test_unknown_slug_defaults_to_short_term_l1(self) -> None:
        st = get_thresholds_for_strategy("totally_unknown_xyz")
        assert st.holding_period == HoldingPeriod.SHORT_TERM
        assert st.optimization_level == OptimizationLevel.L1_EXPLORATORY

    def test_explicit_level_override(self) -> None:
        st = get_thresholds_for_strategy(
            "totally_unknown_xyz",
            level=OptimizationLevel.L3_PRODUCTION,
        )
        assert st.optimization_level == OptimizationLevel.L3_PRODUCTION

    def test_pyramid_resolves_to_swing(self) -> None:
        st = get_thresholds_for_strategy("pyramid")
        assert st.holding_period == HoldingPeriod.SWING


# ---------------------------------------------------------------------------
# Walk-forward quality gates with thresholds
# ---------------------------------------------------------------------------

class TestParametrizedQualityGates:
    def _make_fold(
        self,
        sharpe: float = 1.0,
        mdd: float = 5.0,
        wr: float = 50.0,
        trades: int = 100,
        pf: float = 1.5,
    ) -> "FoldResult":
        from src.simulator.walk_forward import FoldResult

        return FoldResult(
            fold_index=0,
            is_start=datetime(2020, 1, 1),
            is_end=datetime(2020, 6, 1),
            oos_start=datetime(2020, 6, 1),
            oos_end=datetime(2020, 8, 1),
            is_best_params={},
            is_sharpe=1.2,
            oos_sharpe=sharpe,
            oos_mdd_pct=mdd,
            oos_win_rate=wr,
            oos_n_trades=trades,
            oos_profit_factor=pf,
            overfit_ratio=0.8,
        )

    def test_swing_strategy_passes_with_relaxed_thresholds(self) -> None:
        from src.simulator.walk_forward import evaluate_quality_gates

        fold = self._make_fold(sharpe=0.8, mdd=0.18, wr=0.40, trades=25, pf=1.3)
        swing_l2 = get_stage_thresholds(HoldingPeriod.SWING, OptimizationLevel.L2_VALIDATED)
        passed, reasons = evaluate_quality_gates(
            [fold], 0.8, "none", thresholds=swing_l2.to_dict()
        )
        assert passed, f"Should pass SWING L2 gates but got: {reasons}"

    def test_same_fold_fails_short_term_gates(self) -> None:
        from src.simulator.walk_forward import evaluate_quality_gates

        fold = self._make_fold(sharpe=0.8, mdd=0.18, wr=0.40, trades=25, pf=1.3)
        short_l2 = get_stage_thresholds(HoldingPeriod.SHORT_TERM, OptimizationLevel.L2_VALIDATED)
        passed, reasons = evaluate_quality_gates(
            [fold], 0.8, "none", thresholds=short_l2.to_dict()
        )
        assert not passed
        # Should fail on: Sharpe < 1.0, MDD > 10%, trades < 100, WR outside 45-70%
        assert len(reasons) >= 3

    def test_none_thresholds_uses_legacy_defaults(self) -> None:
        from src.simulator.walk_forward import evaluate_quality_gates

        fold = self._make_fold(sharpe=1.1, mdd=0.05, wr=0.50, trades=100, pf=1.5)
        passed, reasons = evaluate_quality_gates([fold], 1.1, "none", thresholds=None)
        assert passed

    def test_l1_has_no_mdd_gate(self) -> None:
        from src.simulator.walk_forward import evaluate_quality_gates

        fold = self._make_fold(sharpe=0.5, mdd=0.50, wr=0.40, trades=15, pf=1.1)
        medium_l1 = get_stage_thresholds(HoldingPeriod.MEDIUM_TERM, OptimizationLevel.L1_EXPLORATORY)
        passed, reasons = evaluate_quality_gates(
            [fold], 0.5, "none", thresholds=medium_l1.to_dict()
        )
        # MDD=50% should NOT cause failure at L1 (no hard gate)
        assert not any("MDD" in r for r in reasons)


# ---------------------------------------------------------------------------
# Hardware classification
# ---------------------------------------------------------------------------

class TestHardwareClassification:
    """Test _classify_hardware() by mocking psutil at the import level."""

    def _run_classify(self, cpu: int, ram_gb: float, env: dict | None = None) -> dict:
        """Helper: run _classify_hardware with mocked cpu/ram."""
        import sys
        import importlib

        mock_mem = MagicMock()
        mock_mem.total = int(ram_gb * 1024**3)
        mock_psutil = MagicMock()
        mock_psutil.virtual_memory.return_value = mock_mem

        from contextlib import ExitStack

        with ExitStack() as stack:
            stack.enter_context(patch("os.cpu_count", return_value=cpu))
            stack.enter_context(patch.dict(sys.modules, {"psutil": mock_psutil}))
            if env:
                stack.enter_context(patch.dict(os.environ, env))

            import src.mcp_server.facade as facade_mod
            importlib.reload(facade_mod)
            try:
                return facade_mod._classify_hardware()
            finally:
                importlib.reload(facade_mod)

    def test_powerful_tier(self) -> None:
        hw = self._run_classify(cpu=16, ram_gb=64.0)
        assert hw["tier"] == "powerful"
        assert hw["mc_workers"] == 8  # 16 // 2
        assert hw["n_paths_cap"] == 2000
        assert hw["optimizer_n_jobs"] >= 4

    def test_constrained_tier(self) -> None:
        hw = self._run_classify(cpu=4, ram_gb=4.0)
        assert hw["tier"] == "constrained"
        assert hw["mc_workers"] == 1  # max(1, 4//4)
        assert hw["n_paths_cap"] == 500
        assert hw["optimizer_n_jobs"] == 1

    def test_env_var_override(self) -> None:
        hw = self._run_classify(
            cpu=4, ram_gb=4.0,
            env={"QUANT_MC_WORKERS": "8", "QUANT_N_PATHS_CAP": "3000"},
        )
        assert hw["mc_workers"] == 8
        assert hw["n_paths_cap"] == 3000
        assert hw["tier"] == "constrained"  # env vars don't change tier
