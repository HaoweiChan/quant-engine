"""Unit tests for risk sign-off report."""

from __future__ import annotations

import numpy as np
import pytest

from src.simulator.adversarial import AdversarialResult
from src.simulator.param_sensitivity import (
    AggregatedSensitivity,
    SensitivityResult,
)
from src.simulator.regime import RegimeMetrics
from src.simulator.risk_report import (
    build_risk_report,
    evaluate_adversarial_gate,
    evaluate_cost_gate,
    evaluate_param_stability_gate,
    evaluate_regime_gate,
    evaluate_walk_forward_gate,
)
from src.simulator.walk_forward import WalkForwardResult


class TestCostGate:
    def test_passes(self) -> None:
        passed, reasons = evaluate_cost_gate(net_sharpe=0.8, cost_drag_pct=30.0)
        assert passed is True
        assert reasons == []

    def test_fails_low_sharpe(self) -> None:
        passed, reasons = evaluate_cost_gate(net_sharpe=0.3, cost_drag_pct=30.0)
        assert passed is False
        assert any("Net Sharpe" in r for r in reasons)

    def test_fails_high_drag(self) -> None:
        passed, reasons = evaluate_cost_gate(net_sharpe=0.8, cost_drag_pct=85.0)
        assert passed is False
        assert any("Cost drag" in r for r in reasons)


class TestParamStabilityGate:
    def _make_sensitivity(
        self, n_params: int = 3, cliff: bool = False, cv: float = 0.1
    ) -> AggregatedSensitivity:
        results = [
            SensitivityResult(
                param_name=f"p{i}",
                grid_values=[1, 2, 3],
                sharpe_values=[1.0, 1.0, 1.0],
                baseline_sharpe=1.0,
                max_sharpe_drop_pct=0.0,
                cliff_detected=cliff if i == 0 else False,
                stability_cv=cv,
                optimal_at_boundary=False,
                unstable=cv > 0.30,
            )
            for i in range(n_params)
        ]
        return AggregatedSensitivity(
            per_param=results,
            likely_overfit=cliff,
            robust=not cliff and cv < 0.20,
        )

    def test_passes(self) -> None:
        sens = self._make_sensitivity(cv=0.10)
        passed, reasons = evaluate_param_stability_gate(sens)
        assert passed is True

    def test_fails_with_cliff(self) -> None:
        sens = self._make_sensitivity(cliff=True)
        passed, reasons = evaluate_param_stability_gate(sens)
        assert passed is False
        assert any("Cliff" in r for r in reasons)

    def test_fails_none(self) -> None:
        passed, reasons = evaluate_param_stability_gate(None)
        assert passed is False


class TestRegimeGate:
    def test_passes(self) -> None:
        metrics = [
            RegimeMetrics("low_vol", 100, 0.8, 10.0, 55.0, 0.001, 0.1),
            RegimeMetrics("high_vol", 50, 0.5, 15.0, 48.0, -0.001, -0.05),
        ]
        passed, worst, reasons = evaluate_regime_gate(metrics)
        assert passed is True
        assert worst == pytest.approx(0.5)

    def test_fails_low_worst_sharpe(self) -> None:
        metrics = [
            RegimeMetrics("low_vol", 100, 0.8, 10.0, 55.0, 0.001, 0.1),
            RegimeMetrics("high_vol", 50, 0.2, 20.0, 40.0, -0.002, -0.1),
        ]
        passed, worst, reasons = evaluate_regime_gate(metrics)
        assert passed is False
        assert any("high_vol" in r for r in reasons)

    def test_fails_none(self) -> None:
        passed, worst, reasons = evaluate_regime_gate(None)
        assert passed is False


class TestAdversarialGate:
    def test_passes(self) -> None:
        result = AdversarialResult(
            clean_paths=np.zeros((10, 100)),
            injected_paths=np.zeros((10, 100)),
            injection_metadata=[],
            clean_var_95=0.05,
            clean_var_99=0.08,
            clean_median_final=2_200_000,
            clean_prob_ruin=0.0,
            injected_var_95=0.06,
            injected_var_99=0.10,
            injected_median_final=2_100_000,
            injected_prob_ruin=0.01,
            worst_case_terminal_equity=1_500_000,
            median_impact_pct=-5.0,
        )
        passed, reasons = evaluate_adversarial_gate(result, initial_equity=2_000_000)
        assert passed is True

    def test_fails_low_equity(self) -> None:
        result = AdversarialResult(
            clean_paths=np.zeros((10, 100)),
            injected_paths=np.zeros((10, 100)),
            injection_metadata=[],
            clean_var_95=0.05,
            clean_var_99=0.08,
            clean_median_final=2_200_000,
            clean_prob_ruin=0.0,
            injected_var_95=0.15,
            injected_var_99=0.25,
            injected_median_final=800_000,
            injected_prob_ruin=0.3,
            worst_case_terminal_equity=500_000,
            median_impact_pct=-60.0,
        )
        passed, reasons = evaluate_adversarial_gate(result, initial_equity=2_000_000)
        assert passed is False

    def test_fails_none(self) -> None:
        passed, reasons = evaluate_adversarial_gate(None)
        assert passed is False


class TestWalkForwardGate:
    def test_passes(self) -> None:
        result = WalkForwardResult(
            folds=[], aggregate_oos_sharpe=0.9,
            mean_overfit_ratio=0.8, overfit_flag="none",
            passed=True, failure_reasons=[],
        )
        passed, reasons = evaluate_walk_forward_gate(result)
        assert passed is True

    def test_fails(self) -> None:
        result = WalkForwardResult(
            folds=[], aggregate_oos_sharpe=0.3,
            mean_overfit_ratio=0.2, overfit_flag="severe",
            passed=False, failure_reasons=["Severe overfit"],
        )
        passed, reasons = evaluate_walk_forward_gate(result)
        assert passed is False

    def test_fails_none(self) -> None:
        passed, reasons = evaluate_walk_forward_gate(None)
        assert passed is False


class TestBuildRiskReport:
    def test_promote_recommendation(self) -> None:
        sens = AggregatedSensitivity(per_param=[], likely_overfit=False, robust=True)
        regime = [RegimeMetrics("low_vol", 100, 0.8, 10, 55, 0.001, 0.1)]
        adv = AdversarialResult(
            clean_paths=np.zeros((1, 10)), injected_paths=np.zeros((1, 10)),
            injection_metadata=[], clean_var_95=0.05, clean_var_99=0.08,
            clean_median_final=2_200_000, clean_prob_ruin=0.0,
            injected_var_95=0.06, injected_var_99=0.10,
            injected_median_final=2_100_000, injected_prob_ruin=0.01,
            worst_case_terminal_equity=1_500_000, median_impact_pct=-5.0,
        )
        wf = WalkForwardResult(
            folds=[], aggregate_oos_sharpe=0.9,
            mean_overfit_ratio=0.8, overfit_flag="none",
            passed=True, failure_reasons=[],
        )
        report = build_risk_report(
            "test_strategy", net_sharpe=1.0, cost_drag_pct=20.0,
            sensitivity=sens, regime_metrics=regime,
            adversarial_result=adv, walk_forward_result=wf,
        )
        assert report.recommendation == "promote"
        assert report.all_gates_passed is True

    def test_reject_on_walk_forward_fail(self) -> None:
        wf = WalkForwardResult(
            folds=[], aggregate_oos_sharpe=0.3,
            mean_overfit_ratio=0.1, overfit_flag="severe",
            passed=False, failure_reasons=["Severe overfit"],
        )
        report = build_risk_report(
            "test_strategy", net_sharpe=1.0, cost_drag_pct=20.0,
            walk_forward_result=wf,
        )
        assert report.recommendation == "reject"

    def test_investigate_on_non_critical_fail(self) -> None:
        wf = WalkForwardResult(
            folds=[], aggregate_oos_sharpe=0.9,
            mean_overfit_ratio=0.8, overfit_flag="none",
            passed=True, failure_reasons=[],
        )
        report = build_risk_report(
            "test_strategy", net_sharpe=1.0, cost_drag_pct=20.0,
            walk_forward_result=wf,
            # No regime or adversarial — these are non-critical
        )
        assert report.recommendation == "investigate"

    def test_to_dict(self) -> None:
        report = build_risk_report("test_strategy", net_sharpe=0.8, cost_drag_pct=30.0)
        d = report.to_dict()
        assert d["strategy_name"] == "test_strategy"
        assert "cost_gate" in d
        assert "recommendation" in d
