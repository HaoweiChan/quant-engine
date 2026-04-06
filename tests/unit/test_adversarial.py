"""Unit tests for adversarial scenario injection."""

from __future__ import annotations

import numpy as np
import pytest

from src.simulator.adversarial import (
    AdversarialResult,
    InjectionConfig,
    inject_adversarial_scenarios,
)
from src.simulator.types import StressScenario


def _make_equity_paths(n_paths: int = 100, n_steps: int = 252) -> np.ndarray:
    """Generate simple upward-trending equity paths."""
    rng = np.random.default_rng(42)
    initial = 2_000_000.0
    paths = np.empty((n_paths, n_steps + 1))
    paths[:, 0] = initial
    for t in range(1, n_steps + 1):
        returns = rng.normal(0.0003, 0.01, n_paths)
        paths[:, t] = paths[:, t - 1] * (1 + returns)
    return paths


class TestAdversarialInjection:
    def test_injection_probability(self) -> None:
        paths = _make_equity_paths(n_paths=200)
        config = InjectionConfig(
            scenario=StressScenario(name="gap_down", magnitude=0.10, duration=1, recovery=0),
            injection_probability=0.3,
            seed=42,
        )
        result = inject_adversarial_scenarios(paths, [config])
        # ~30% of 200 paths = ~60, allow wide margin
        n_injected = len(result.injection_metadata)
        assert 20 < n_injected < 120

    def test_path_prefix_preserved(self) -> None:
        paths = _make_equity_paths(n_paths=50)
        config = InjectionConfig(
            scenario=StressScenario(name="slow_bleed", magnitude=0.15, duration=30, recovery=0),
            injection_probability=1.0,
            min_warmup_bars=20,
            seed=42,
        )
        result = inject_adversarial_scenarios(paths, [config])
        for event in result.injection_metadata:
            idx = event.path_index
            t = event.injection_point
            # Path before injection point should be unchanged
            np.testing.assert_array_almost_equal(
                result.clean_paths[idx, :t],
                result.injected_paths[idx, :t],
            )

    def test_multi_scenario_at_most_one_per_path(self) -> None:
        paths = _make_equity_paths(n_paths=100)
        configs = [
            InjectionConfig(
                scenario=StressScenario(name="gap_down", magnitude=0.10, duration=1, recovery=0),
                injection_probability=0.5,
                seed=42,
            ),
            InjectionConfig(
                scenario=StressScenario(name="flash_crash", magnitude=0.12, duration=3, recovery=10),
                injection_probability=0.5,
                seed=42,
            ),
        ]
        result = inject_adversarial_scenarios(paths, configs)
        # Each path appears at most once in metadata
        injected_path_indices = [m.path_index for m in result.injection_metadata]
        assert len(injected_path_indices) == len(set(injected_path_indices))

    def test_worst_case_terminal_equity(self) -> None:
        paths = _make_equity_paths(n_paths=50)
        config = InjectionConfig(
            scenario=StressScenario(name="gap_down", magnitude=0.10, duration=1, recovery=0),
            injection_probability=1.0,
            seed=42,
        )
        result = inject_adversarial_scenarios(paths, [config])
        assert result.worst_case_terminal_equity < result.clean_median_final

    def test_median_impact_pct_negative_for_adverse(self) -> None:
        paths = _make_equity_paths(n_paths=50)
        config = InjectionConfig(
            scenario=StressScenario(name="slow_bleed", magnitude=0.15, duration=60, recovery=0),
            injection_probability=1.0,
            seed=42,
        )
        result = inject_adversarial_scenarios(paths, [config])
        assert result.median_impact_pct < 0.0

    def test_metrics_present(self) -> None:
        paths = _make_equity_paths(n_paths=30)
        config = InjectionConfig(
            scenario=StressScenario(name="gap_down", magnitude=0.10, duration=1, recovery=0),
            injection_probability=0.5,
            seed=42,
        )
        result = inject_adversarial_scenarios(paths, [config])
        assert result.clean_var_95 >= 0
        assert result.injected_var_95 >= 0
        assert result.clean_median_final > 0
        assert result.injected_median_final > 0

    def test_no_injection_when_zero_probability(self) -> None:
        paths = _make_equity_paths(n_paths=30)
        config = InjectionConfig(
            scenario=StressScenario(name="gap_down", magnitude=0.10, duration=1, recovery=0),
            injection_probability=0.0,
            seed=42,
        )
        result = inject_adversarial_scenarios(paths, [config])
        assert len(result.injection_metadata) == 0
        np.testing.assert_array_equal(result.clean_paths, result.injected_paths)
