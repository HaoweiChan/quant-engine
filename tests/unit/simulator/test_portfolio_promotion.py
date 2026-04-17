"""Unit tests for portfolio-level promotion framework."""
from __future__ import annotations

from pathlib import Path

from src.simulator.portfolio_promotion import (
    GATE_THRESHOLDS,
    PortfolioOptimizationLevel,
    load_portfolio_config,
    promote_portfolio,
    save_portfolio_config,
)


class TestGateChecks:
    def test_l1_passes_with_sufficient_sharpe(self) -> None:
        result = promote_portfolio(
            current_level=PortfolioOptimizationLevel.L0_UNOPTIMIZED,
            target_level=PortfolioOptimizationLevel.L1_EXPLORATORY,
            gate_results={"combined_sharpe": 1.5},
        )
        assert result.passed is True
        assert result.new_level == PortfolioOptimizationLevel.L1_EXPLORATORY
        assert result.promoted_at is not None

    def test_l1_fails_below_sharpe_floor(self) -> None:
        result = promote_portfolio(
            current_level=PortfolioOptimizationLevel.L0_UNOPTIMIZED,
            target_level=PortfolioOptimizationLevel.L1_EXPLORATORY,
            gate_results={"combined_sharpe": 0.9},
        )
        assert result.passed is False
        assert result.new_level == PortfolioOptimizationLevel.L0_UNOPTIMIZED
        assert any("combined_sharpe" in r for r in result.failure_reasons)

    def test_l2_requires_all_hard_gates(self) -> None:
        """Missing any of the L2 HARD gates → promotion fails.
        (weight_drift_cv is an advisory now, not a hard gate.)"""
        base = {
            "aggregate_oos_sharpe": 2.0,
            "worst_fold_oos_mdd": 0.15,
            "weight_drift_cv": 0.2,
            "correlation_stability": 0.8,
        }
        # Block on MDD
        bad_mdd = {**base, "worst_fold_oos_mdd": 0.30}
        r = promote_portfolio(
            PortfolioOptimizationLevel.L1_EXPLORATORY,
            PortfolioOptimizationLevel.L2_VALIDATED,
            bad_mdd,
        )
        assert r.passed is False
        assert any("worst_fold_oos_mdd" in msg for msg in r.failure_reasons)

    def test_l2_passes_when_all_hard_gates_pass(self) -> None:
        gates = {
            "aggregate_oos_sharpe": 2.0,
            "worst_fold_oos_mdd": 0.12,
            "weight_drift_cv": 0.25,
            "correlation_stability": 0.85,
        }
        r = promote_portfolio(
            PortfolioOptimizationLevel.L1_EXPLORATORY,
            PortfolioOptimizationLevel.L2_VALIDATED,
            gates,
        )
        assert r.passed is True
        assert r.new_level == PortfolioOptimizationLevel.L2_VALIDATED
        assert r.warnings == []  # nothing advisory breached

    def test_l3_requires_paper_sessions(self) -> None:
        gates = {"slippage_stress_sharpe": 1.2, "paper_trade_sessions": 3}
        r = promote_portfolio(
            PortfolioOptimizationLevel.L2_VALIDATED,
            PortfolioOptimizationLevel.L3_PRODUCTION,
            gates,
        )
        assert r.passed is False
        assert any("paper_trade_sessions" in msg for msg in r.failure_reasons)

    def test_cannot_skip_levels(self) -> None:
        r = promote_portfolio(
            PortfolioOptimizationLevel.L0_UNOPTIMIZED,
            PortfolioOptimizationLevel.L2_VALIDATED,
            {"aggregate_oos_sharpe": 10.0},
        )
        assert r.passed is False
        assert any("skip" in msg for msg in r.failure_reasons)

    def test_cannot_demote(self) -> None:
        r = promote_portfolio(
            PortfolioOptimizationLevel.L2_VALIDATED,
            PortfolioOptimizationLevel.L1_EXPLORATORY,
            {},
        )
        assert r.passed is False
        assert any("must exceed" in msg for msg in r.failure_reasons)

    def test_missing_metric_is_failure(self) -> None:
        r = promote_portfolio(
            PortfolioOptimizationLevel.L0_UNOPTIMIZED,
            PortfolioOptimizationLevel.L1_EXPLORATORY,
            {},  # No combined_sharpe at all
        )
        assert r.passed is False
        assert any("Missing gate metric" in msg for msg in r.failure_reasons)


class TestConfigIO:
    def test_load_missing_config_returns_l0_skeleton(self, tmp_path: Path) -> None:
        cfg = load_portfolio_config("absent", config_root=tmp_path)
        assert cfg["optimization"]["level"] == 0
        assert cfg["optimization"]["level_name"] == "L0_UNOPTIMIZED"
        assert cfg["portfolio"]["name"] == "absent"

    def test_save_then_load_roundtrip(self, tmp_path: Path) -> None:
        original = {
            "portfolio": {
                "name": "tx_4strategy",
                "symbol": "TX",
                "strategies": [
                    {"slug": "a/b/c", "weight": 0.6},
                    {"slug": "d/e/f", "weight": 0.4},
                ],
                "kelly": {"fraction": 0.25, "long_only": True},
            },
            "optimization": {
                "level": 1,
                "level_name": "L1_EXPLORATORY",
                "gate_results": {
                    "combined_sharpe": 1.5,
                    "worst_fold_oos_mdd": 0.12,
                },
            },
        }
        path = save_portfolio_config("tx_4strategy", original, config_root=tmp_path)
        assert path.exists()
        loaded = load_portfolio_config("tx_4strategy", config_root=tmp_path)
        assert loaded["portfolio"]["name"] == "tx_4strategy"
        assert loaded["portfolio"]["symbol"] == "TX"
        assert loaded["optimization"]["level"] == 1
        assert loaded["optimization"]["gate_results"]["combined_sharpe"] == 1.5
        # List of strategies round-trips
        strats = loaded["portfolio"]["strategies"]
        assert len(strats) == 2
        assert strats[0]["slug"] == "a/b/c"
        assert strats[0]["weight"] == 0.6


class TestGateThresholdConstants:
    def test_every_level_has_gates(self) -> None:
        for level in (
            PortfolioOptimizationLevel.L1_EXPLORATORY,
            PortfolioOptimizationLevel.L2_VALIDATED,
            PortfolioOptimizationLevel.L3_PRODUCTION,
        ):
            assert level in GATE_THRESHOLDS
            assert len(GATE_THRESHOLDS[level]) >= 1

    def test_gate_keys_end_in_floor_or_ceiling(self) -> None:
        """Enforces naming convention for automatic _check_gates dispatch."""
        for level, gates in GATE_THRESHOLDS.items():
            for key in gates:
                assert key.endswith("_floor") or key.endswith("_ceiling"), (
                    f"{level.name}: gate key {key!r} must end in _floor or _ceiling"
                )


class TestAdvisoryThresholds:
    """weight_drift_cv is advisory — breaches WARN but do NOT block."""

    @staticmethod
    def _passing_hard_gates() -> dict[str, float]:
        return {
            "aggregate_oos_sharpe": 7.0,
            "worst_fold_oos_mdd": 0.05,
            "correlation_stability": 0.85,
        }

    def test_high_weight_drift_does_not_block(self) -> None:
        gates = {**self._passing_hard_gates(), "weight_drift_cv": 0.50}
        r = promote_portfolio(
            PortfolioOptimizationLevel.L1_EXPLORATORY,
            PortfolioOptimizationLevel.L2_VALIDATED,
            gates,
        )
        assert r.passed is True
        assert r.new_level == PortfolioOptimizationLevel.L2_VALIDATED
        # But a warning is raised
        assert len(r.warnings) == 1
        assert "weight_drift_cv" in r.warnings[0]
        assert "advisory" in r.warnings[0]

    def test_low_weight_drift_produces_no_warning(self) -> None:
        gates = {**self._passing_hard_gates(), "weight_drift_cv": 0.15}
        r = promote_portfolio(
            PortfolioOptimizationLevel.L1_EXPLORATORY,
            PortfolioOptimizationLevel.L2_VALIDATED,
            gates,
        )
        assert r.passed is True
        assert r.warnings == []

    def test_missing_advisory_metric_no_warning(self) -> None:
        """Absent advisory metrics are treated as 'not measured', not as
        a warning — the upstream walk-forward may simply not have
        computed them in older runs."""
        gates = self._passing_hard_gates()  # no weight_drift_cv key
        r = promote_portfolio(
            PortfolioOptimizationLevel.L1_EXPLORATORY,
            PortfolioOptimizationLevel.L2_VALIDATED,
            gates,
        )
        assert r.passed is True
        assert r.warnings == []

    def test_advisory_thresholds_checked_populated(self) -> None:
        r = promote_portfolio(
            PortfolioOptimizationLevel.L1_EXPLORATORY,
            PortfolioOptimizationLevel.L2_VALIDATED,
            {**self._passing_hard_gates(), "weight_drift_cv": 0.15},
        )
        assert "weight_drift_cv_ceiling" in r.advisory_thresholds_checked

    def test_hard_gate_failure_still_reports_warnings(self) -> None:
        """Even when the hard gate fails, advisories are evaluated so the
        operator sees all issues at once."""
        gates = {
            "aggregate_oos_sharpe": 1.0,  # fails floor 1.5
            "worst_fold_oos_mdd": 0.05,
            "correlation_stability": 0.85,
            "weight_drift_cv": 0.50,      # also breaches advisory
        }
        r = promote_portfolio(
            PortfolioOptimizationLevel.L1_EXPLORATORY,
            PortfolioOptimizationLevel.L2_VALIDATED,
            gates,
        )
        assert r.passed is False
        assert any("aggregate_oos_sharpe" in m for m in r.failure_reasons)
        assert any("weight_drift_cv" in w for w in r.warnings)


class TestWarningsPersistence:
    def test_warnings_round_trip_in_toml(self, tmp_path: Path) -> None:
        """When promotion passes WITH warnings, those warnings end up in
        ``[optimization].warnings`` on the persisted TOML."""
        config = {
            "portfolio": {"name": "tx_test", "symbol": "TX", "strategies": []},
            "optimization": {
                "level": 2,
                "level_name": "L2_VALIDATED",
                "gate_results": {"aggregate_oos_sharpe": 7.0},
                "warnings": ["advisory: weight_drift_cv=0.5 > ceiling 0.3"],
            },
        }
        path = save_portfolio_config("tx_test", config, config_root=tmp_path)
        assert path.exists()
        loaded = load_portfolio_config("tx_test", config_root=tmp_path)
        assert loaded["optimization"]["warnings"] == [
            "advisory: weight_drift_cv=0.5 > ceiling 0.3",
        ]
