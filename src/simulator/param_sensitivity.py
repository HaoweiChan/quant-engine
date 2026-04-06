"""Parameter sensitivity analysis with cliff-edge detection and stability scoring."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np


@dataclass
class SensitivityResult:
    """Sensitivity analysis for a single parameter."""

    param_name: str
    grid_values: list[float]
    sharpe_values: list[float]
    baseline_sharpe: float
    max_sharpe_drop_pct: float
    cliff_detected: bool
    stability_cv: float
    optimal_at_boundary: bool
    unstable: bool

    @property
    def stable(self) -> bool:
        return self.stability_cv < 0.15


@dataclass
class AggregatedSensitivity:
    """Aggregate sensitivity assessment across all parameters."""

    per_param: list[SensitivityResult]
    likely_overfit: bool
    robust: bool


def analyze_param_sensitivity(
    param_name: str,
    grid_values: list[float],
    sharpe_values: list[float],
    baseline_sharpe: float,
) -> SensitivityResult:
    """Analyze a single parameter's sensitivity from sweep results.

    Args:
        param_name: Name of the parameter.
        grid_values: Parameter values tested (sorted).
        sharpe_values: Sharpe ratio at each grid value.
        baseline_sharpe: Sharpe at the current (unperturbed) value.
    """
    if len(grid_values) != len(sharpe_values):
        raise ValueError("grid_values and sharpe_values must have same length")
    if len(grid_values) < 2:
        return SensitivityResult(
            param_name=param_name,
            grid_values=grid_values,
            sharpe_values=sharpe_values,
            baseline_sharpe=baseline_sharpe,
            max_sharpe_drop_pct=0.0,
            cliff_detected=False,
            stability_cv=0.0,
            optimal_at_boundary=False,
            unstable=False,
        )

    arr = np.array(sharpe_values)

    # Cliff detection: >30% drop between adjacent grid points
    cliff_detected = False
    max_drop_pct = 0.0
    for i in range(len(arr) - 1):
        if arr[i] > 0:
            drop_pct = (arr[i] - arr[i + 1]) / arr[i] * 100.0
            if drop_pct > max_drop_pct:
                max_drop_pct = drop_pct
            if drop_pct > 30.0:
                cliff_detected = True

    # Stability CV
    mean_sharpe = float(np.mean(arr))
    if mean_sharpe <= 0:
        stability_cv = float("inf")
        unstable = True
    else:
        std_sharpe = float(np.std(arr))
        stability_cv = std_sharpe / mean_sharpe
        unstable = stability_cv > 0.30

    # Boundary optimum check
    best_idx = int(np.argmax(arr))
    optimal_at_boundary = best_idx == 0 or best_idx == len(arr) - 1

    return SensitivityResult(
        param_name=param_name,
        grid_values=grid_values,
        sharpe_values=sharpe_values,
        baseline_sharpe=baseline_sharpe,
        max_sharpe_drop_pct=max_drop_pct,
        cliff_detected=cliff_detected,
        stability_cv=stability_cv,
        optimal_at_boundary=optimal_at_boundary,
        unstable=unstable,
    )


def aggregate_sensitivity(results: list[SensitivityResult]) -> AggregatedSensitivity:
    """Compute aggregate overfitting assessment across all parameters."""
    if not results:
        return AggregatedSensitivity(per_param=[], likely_overfit=False, robust=True)

    n_problematic = sum(
        1 for r in results if r.cliff_detected or r.unstable
    )
    likely_overfit = n_problematic > len(results) / 2

    robust = (
        not any(r.cliff_detected for r in results)
        and all(r.stability_cv < 0.20 for r in results)
    )

    return AggregatedSensitivity(
        per_param=results,
        likely_overfit=likely_overfit,
        robust=robust,
    )


def generate_perturbation_grid(
    current_value: float,
    pct_range: float = 0.20,
    n_steps: int = 5,
    is_integer: bool = False,
    min_bound: float | None = None,
    max_bound: float | None = None,
) -> list[float]:
    """Generate a grid of values around the current value.

    Args:
        current_value: The baseline parameter value.
        pct_range: Percentage range (0.20 = ±20%).
        n_steps: Number of steps per side (total = 2*n_steps + 1).
        is_integer: If True, round to nearest int and deduplicate.
        min_bound: Minimum allowed value (clamp).
        max_bound: Maximum allowed value (clamp).
    """
    low = current_value * (1 - pct_range)
    high = current_value * (1 + pct_range)
    grid = np.linspace(low, high, 2 * n_steps + 1).tolist()

    if min_bound is not None:
        grid = [max(v, min_bound) for v in grid]
    if max_bound is not None:
        grid = [min(v, max_bound) for v in grid]

    if is_integer:
        grid = sorted(set(round(v) for v in grid))

    return grid
