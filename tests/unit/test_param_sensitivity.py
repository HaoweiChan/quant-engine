"""Unit tests for parameter sensitivity analysis."""

from __future__ import annotations

import pytest

from src.simulator.param_sensitivity import (
    SensitivityResult,
    aggregate_sensitivity,
    analyze_param_sensitivity,
    generate_perturbation_grid,
)


class TestAnalyzeParamSensitivity:
    def test_cliff_detected_when_sharpe_drops_over_30pct(self) -> None:
        # Sharpe drops from 1.0 to 0.5 (50% drop) between adjacent points
        result = analyze_param_sensitivity(
            param_name="bb_len",
            grid_values=[10, 12, 14, 16, 18],
            sharpe_values=[1.0, 1.0, 1.0, 0.5, 0.4],
            baseline_sharpe=1.0,
        )
        assert result.cliff_detected is True
        assert result.max_sharpe_drop_pct > 30.0

    def test_no_cliff_when_smooth(self) -> None:
        result = analyze_param_sensitivity(
            param_name="bb_len",
            grid_values=[10, 12, 14, 16, 18],
            sharpe_values=[0.9, 0.95, 1.0, 0.95, 0.9],
            baseline_sharpe=1.0,
        )
        assert result.cliff_detected is False

    def test_stability_cv_low_for_stable_params(self) -> None:
        result = analyze_param_sensitivity(
            param_name="bb_len",
            grid_values=[10, 12, 14, 16, 18],
            sharpe_values=[0.95, 0.97, 1.0, 0.97, 0.95],
            baseline_sharpe=1.0,
        )
        assert result.stability_cv < 0.15
        assert result.stable is True
        assert result.unstable is False

    def test_stability_cv_high_for_unstable_params(self) -> None:
        result = analyze_param_sensitivity(
            param_name="bb_len",
            grid_values=[10, 12, 14, 16, 18],
            sharpe_values=[0.2, 1.5, 0.3, 1.8, 0.1],
            baseline_sharpe=1.0,
        )
        assert result.stability_cv > 0.30
        assert result.unstable is True

    def test_stability_cv_inf_when_mean_negative(self) -> None:
        result = analyze_param_sensitivity(
            param_name="bb_len",
            grid_values=[10, 12, 14],
            sharpe_values=[-0.5, -0.3, -0.1],
            baseline_sharpe=-0.3,
        )
        assert result.stability_cv == float("inf")
        assert result.unstable is True

    def test_optimal_at_boundary(self) -> None:
        result = analyze_param_sensitivity(
            param_name="bb_len",
            grid_values=[10, 12, 14, 16, 18],
            sharpe_values=[1.5, 1.0, 0.8, 0.6, 0.4],
            baseline_sharpe=0.8,
        )
        assert result.optimal_at_boundary is True

    def test_optimal_not_at_boundary(self) -> None:
        result = analyze_param_sensitivity(
            param_name="bb_len",
            grid_values=[10, 12, 14, 16, 18],
            sharpe_values=[0.6, 0.8, 1.2, 0.9, 0.7],
            baseline_sharpe=1.2,
        )
        assert result.optimal_at_boundary is False


class TestAggregateSensitivity:
    def _make_result(
        self, cliff: bool = False, unstable: bool = False, cv: float = 0.1
    ) -> SensitivityResult:
        return SensitivityResult(
            param_name="test",
            grid_values=[1, 2, 3],
            sharpe_values=[1.0, 1.0, 1.0],
            baseline_sharpe=1.0,
            max_sharpe_drop_pct=0.0,
            cliff_detected=cliff,
            stability_cv=cv,
            optimal_at_boundary=False,
            unstable=unstable,
        )

    def test_likely_overfit_when_majority_problematic(self) -> None:
        results = [
            self._make_result(cliff=True),
            self._make_result(unstable=True),
            self._make_result(),  # fine
        ]
        agg = aggregate_sensitivity(results)
        assert agg.likely_overfit is True

    def test_not_overfit_when_minority_problematic(self) -> None:
        results = [
            self._make_result(cliff=True),
            self._make_result(),
            self._make_result(),
            self._make_result(),
        ]
        agg = aggregate_sensitivity(results)
        assert agg.likely_overfit is False

    def test_robust_when_no_issues(self) -> None:
        results = [
            self._make_result(cv=0.05),
            self._make_result(cv=0.10),
        ]
        agg = aggregate_sensitivity(results)
        assert agg.robust is True
        assert agg.likely_overfit is False

    def test_not_robust_with_cliff(self) -> None:
        results = [
            self._make_result(cliff=True, cv=0.05),
            self._make_result(cv=0.10),
        ]
        agg = aggregate_sensitivity(results)
        assert agg.robust is False

    def test_empty_results(self) -> None:
        agg = aggregate_sensitivity([])
        assert agg.likely_overfit is False
        assert agg.robust is True


class TestGeneratePerturbationGrid:
    def test_default_grid_size(self) -> None:
        grid = generate_perturbation_grid(14.0, pct_range=0.20, n_steps=5)
        assert len(grid) == 11  # 2*5 + 1

    def test_integer_dedup(self) -> None:
        grid = generate_perturbation_grid(5.0, pct_range=0.20, n_steps=5, is_integer=True)
        assert all(isinstance(v, int) for v in grid)
        assert len(grid) == len(set(grid))

    def test_clamping(self) -> None:
        grid = generate_perturbation_grid(
            2.0, pct_range=0.50, n_steps=5, min_bound=1.5, max_bound=3.0
        )
        assert all(1.5 <= v <= 3.0 for v in grid)

    def test_range(self) -> None:
        grid = generate_perturbation_grid(100.0, pct_range=0.20, n_steps=5)
        assert min(grid) == pytest.approx(80.0)
        assert max(grid) == pytest.approx(120.0)
