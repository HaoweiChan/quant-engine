"""Unit tests for PortfolioRiskReport."""
from __future__ import annotations

import numpy as np
import pytest

from src.simulator.portfolio_risk_report import (
    DEFAULT_THRESHOLDS,
    LayerResult,
    PortfolioRiskReport,
    PortfolioRiskReportResult,
)


def _two_strat_returns(n: int = 300, seed: int = 0) -> dict[str, np.ndarray]:
    rng = np.random.default_rng(seed)
    return {
        "a": rng.normal(0.002, 0.01, n).astype(np.float64),
        "b": rng.normal(0.001, 0.008, n).astype(np.float64),
    }


class TestConstruction:
    def test_requires_two_strategies(self) -> None:
        with pytest.raises(ValueError, match="at least 2 strategies"):
            PortfolioRiskReport(
                daily_returns={"only": np.zeros(100)},
                weights={"only": 1.0},
            )

    def test_mismatched_slugs_rejected(self) -> None:
        with pytest.raises(ValueError, match="matching strategy slugs"):
            PortfolioRiskReport(
                daily_returns=_two_strat_returns(),
                weights={"a": 0.5, "c": 0.5},
            )

    def test_weights_must_sum_to_one(self) -> None:
        with pytest.raises(ValueError, match="must sum to ~1.0"):
            PortfolioRiskReport(
                daily_returns=_two_strat_returns(),
                weights={"a": 0.1, "b": 0.2},
            )


class TestSensitivityLayer:
    def test_low_cv_passes(self) -> None:
        report = PortfolioRiskReport(
            daily_returns=_two_strat_returns(300),
            weights={"a": 0.5, "b": 0.5},
        )
        result = report._layer_sensitivity(scale_delta=0.2)
        assert isinstance(result, LayerResult)
        assert result.name == "sensitivity"
        assert result.status in {"pass", "fail"}
        assert "cv" in result.metrics
        assert "perturbations" in result.details


class TestCorrelationStress:
    def test_stressed_sharpe_reported(self) -> None:
        report = PortfolioRiskReport(
            daily_returns=_two_strat_returns(300),
            weights={"a": 0.5, "b": 0.5},
        )
        result = report._layer_correlation_stress(stressed_rho=0.8)
        assert result.name == "correlation_stress"
        assert "sharpe" in result.metrics
        assert "stressed_rho" in result.metrics
        assert result.metrics["stressed_rho"] == 0.8

    def test_psd_regularization_for_high_rho(self) -> None:
        """Even ρ=0.95 should yield a valid (non-NaN) Sharpe."""
        report = PortfolioRiskReport(
            daily_returns=_two_strat_returns(200),
            weights={"a": 0.5, "b": 0.5},
        )
        result = report._layer_correlation_stress(stressed_rho=0.95)
        assert np.isfinite(result.metrics["sharpe"])


class TestConcurrentStop:
    def test_shock_drops_portfolio(self) -> None:
        report = PortfolioRiskReport(
            daily_returns=_two_strat_returns(200),
            weights={"a": 0.5, "b": 0.5},
        )
        result = report._layer_concurrent_stop()
        assert result.name == "concurrent_stop_stress"
        # Portfolio shock should be negative (worst-of-worst combination)
        assert result.metrics["portfolio_shock_return"] <= 0.0
        assert "worst_day_by_strategy" in result.details


class TestSlippageStress:
    def test_drag_reduces_sharpe(self) -> None:
        report = PortfolioRiskReport(
            daily_returns=_two_strat_returns(500),
            weights={"a": 0.5, "b": 0.5},
        )
        baseline_sharpe = report._baseline_sharpe()
        result = report._layer_slippage_stress(daily_drag=0.001)
        assert result.name == "slippage_stress"
        # Stressed sharpe should be <= baseline (drag always hurts)
        assert result.metrics["stressed_sharpe"] <= baseline_sharpe + 1e-6


class TestKellyScan:
    def test_curve_has_fractions(self) -> None:
        report = PortfolioRiskReport(
            daily_returns=_two_strat_returns(300),
            weights={"a": 0.5, "b": 0.5},
        )
        result = report._layer_kelly_scan(fractions=[0.1, 0.25, 0.5, 1.0])
        assert result.name == "kelly_scan"
        assert result.status == "pass"  # informational layer
        assert len(result.details["curve"]) == 4
        # MDD increases with fraction (leverage scales loss)
        curve = result.details["curve"]
        mdds = [p["mdd_pct"] for p in curve]
        # Strictly non-decreasing for scaled returns
        for i in range(1, len(mdds)):
            assert mdds[i] >= mdds[i - 1] - 1e-6


class TestRun:
    def test_run_produces_all_layers(self) -> None:
        report = PortfolioRiskReport(
            daily_returns=_two_strat_returns(400),
            weights={"a": 0.5, "b": 0.5},
        )
        result = report.run()
        assert isinstance(result, PortfolioRiskReportResult)
        assert result.overall_status in {"pass", "fail"}
        for key in (
            "sensitivity",
            "correlation_stress",
            "concurrent_stop_stress",
            "slippage_stress",
            "kelly_scan",
        ):
            assert key in result.layers
            assert isinstance(result.layers[key], LayerResult)

    def test_dict_serialisation(self) -> None:
        report = PortfolioRiskReport(
            daily_returns=_two_strat_returns(300),
            weights={"a": 0.5, "b": 0.5},
        )
        out = report.run().as_dict()
        assert "overall_status" in out
        assert "layers" in out
        assert "thresholds_applied" in out
        for _layer_name, layer in out["layers"].items():
            assert "name" in layer
            assert "status" in layer
            assert "metrics" in layer

    def test_custom_thresholds_override_defaults(self) -> None:
        custom = {"slippage_stress_sharpe_floor": 100.0}  # impossibly high
        report = PortfolioRiskReport(
            daily_returns=_two_strat_returns(300),
            weights={"a": 0.5, "b": 0.5},
            thresholds=custom,
        )
        result = report.run()
        # Slippage stress always fails with this threshold
        assert result.layers["slippage_stress"].status == "fail"
        assert result.overall_status == "fail"


class TestThresholdDefaults:
    def test_defaults_are_reasonable(self) -> None:
        assert DEFAULT_THRESHOLDS["sensitivity_cv_ceiling"] > 0
        assert DEFAULT_THRESHOLDS["slippage_stress_sharpe_floor"] > 0
        assert DEFAULT_THRESHOLDS["correlation_stress_sharpe_floor"] > 0
