"""Adversarial scenario injection into Monte Carlo equity paths."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import numpy.typing as npt

from src.simulator.types import StressScenario


@dataclass
class InjectionConfig:
    """Configuration for injecting a stress scenario into MC paths."""

    scenario: StressScenario
    injection_probability: float = 0.3
    min_warmup_bars: int = 20
    seed: int | None = None


@dataclass
class InjectionEvent:
    """Metadata about a single injection into a path."""

    path_index: int
    injection_point: int
    scenario_name: str
    duration: int


@dataclass
class AdversarialResult:
    """Result of adversarial scenario injection into MC paths."""

    clean_paths: npt.NDArray[np.float64]
    injected_paths: npt.NDArray[np.float64]
    injection_metadata: list[InjectionEvent]
    clean_var_95: float
    clean_var_99: float
    clean_median_final: float
    clean_prob_ruin: float
    injected_var_95: float
    injected_var_99: float
    injected_median_final: float
    injected_prob_ruin: float
    worst_case_terminal_equity: float
    median_impact_pct: float


def _apply_scenario_to_returns(
    returns: npt.NDArray[np.float64],
    scenario: StressScenario,
    injection_point: int,
) -> npt.NDArray[np.float64]:
    """Apply a stress scenario transform to a return series at a given point."""
    modified = returns.copy()
    name = scenario.name
    dur = scenario.duration

    if name == "gap_down":
        # Single-bar gap at injection point
        if injection_point < len(modified):
            modified[injection_point] = -scenario.magnitude
    elif name == "slow_bleed":
        daily_drop = scenario.magnitude / max(dur, 1)
        end = min(injection_point + dur, len(modified))
        for i in range(injection_point, end):
            modified[i] = -daily_drop
    elif name == "flash_crash":
        crash_bars = dur
        recovery_bars = scenario.recovery
        crash_drop = scenario.magnitude / max(crash_bars, 1)
        # Crash phase
        end_crash = min(injection_point + crash_bars, len(modified))
        for i in range(injection_point, end_crash):
            modified[i] = -crash_drop
        # Recovery phase
        recovery_gain = scenario.magnitude * 0.95 / max(recovery_bars, 1)
        end_recovery = min(end_crash + recovery_bars, len(modified))
        for i in range(end_crash, end_recovery):
            modified[i] = recovery_gain
    elif name == "vol_regime_shift":
        rng = np.random.default_rng(42)
        end = min(injection_point + dur, len(modified))
        for i in range(injection_point, end):
            modified[i] = rng.normal(0.0, scenario.magnitude)
    elif name == "liquidity_crisis":
        # Modeled as increased negative drift + higher vol
        rng = np.random.default_rng(42)
        end = min(injection_point + dur, len(modified))
        for i in range(injection_point, end):
            modified[i] = rng.normal(-0.005, 0.02)
    return modified


def _scenario_duration(scenario: StressScenario) -> int:
    """Total duration of a scenario in bars."""
    if scenario.name == "gap_down":
        return 1
    if scenario.name == "flash_crash":
        return scenario.duration + scenario.recovery
    return scenario.duration


def _compute_path_metrics(
    paths: npt.NDArray[np.float64],
    ruin_threshold: float = 0.5,
) -> tuple[float, float, float, float]:
    """Compute VaR95, VaR99, median final equity, P(Ruin)."""
    final_equities = paths[:, -1]
    initial = paths[:, 0]
    returns_total = (final_equities - initial) / initial
    var_95 = float(-np.percentile(returns_total, 5))
    var_99 = float(-np.percentile(returns_total, 1))
    median_final = float(np.median(final_equities))
    ruin_count = np.sum(final_equities < initial * ruin_threshold)
    prob_ruin = float(ruin_count / len(paths))
    return var_95, var_99, median_final, prob_ruin


def inject_adversarial_scenarios(
    equity_paths: npt.NDArray[np.float64],
    configs: list[InjectionConfig],
    ruin_threshold: float = 0.5,
) -> AdversarialResult:
    """Inject stress scenarios at random positions within MC equity paths.

    Args:
        equity_paths: Array of shape (n_paths, n_bars+1) — MC equity paths.
        configs: List of injection configurations (one per scenario type).
        ruin_threshold: Fraction of initial equity below which ruin is declared.

    Returns:
        AdversarialResult with clean vs injected metrics.
    """
    n_paths, n_steps = equity_paths.shape
    clean_paths = equity_paths.copy()
    injected_paths = equity_paths.copy()
    metadata: list[InjectionEvent] = []

    # Convert equity paths to return series for injection
    initial_equities = equity_paths[:, 0]

    # Use first config's seed or default
    seed = configs[0].seed if configs and configs[0].seed is not None else 42
    rng = np.random.default_rng(seed)

    for path_idx in range(n_paths):
        # Decide whether this path gets an injection
        inject_prob = max(c.injection_probability for c in configs)
        if rng.random() > inject_prob:
            continue

        # Select scenario uniformly from available configs
        config = configs[rng.integers(len(configs))]
        scenario = config.scenario
        dur = _scenario_duration(scenario)

        # Compute valid injection range
        min_start = config.min_warmup_bars
        max_start = n_steps - 1 - dur
        if max_start <= min_start:
            continue

        injection_point = int(rng.integers(min_start, max_start))

        # Convert equity to returns, apply scenario, convert back
        eq = equity_paths[path_idx]
        returns = np.diff(eq) / eq[:-1]
        modified_returns = _apply_scenario_to_returns(returns, scenario, injection_point)

        # Reconstruct equity from modified returns
        modified_eq = np.empty(n_steps)
        modified_eq[0] = eq[0]
        for t in range(1, n_steps):
            modified_eq[t] = modified_eq[t - 1] * (1 + modified_returns[t - 1])
        injected_paths[path_idx] = modified_eq

        metadata.append(InjectionEvent(
            path_index=path_idx,
            injection_point=injection_point,
            scenario_name=scenario.name,
            duration=dur,
        ))

    # Compute metrics for clean and injected paths
    c_var95, c_var99, c_median, c_ruin = _compute_path_metrics(clean_paths, ruin_threshold)
    i_var95, i_var99, i_median, i_ruin = _compute_path_metrics(injected_paths, ruin_threshold)

    # Worst-case terminal equity across injected paths
    injected_indices = [m.path_index for m in metadata]
    if injected_indices:
        worst_case = float(np.min(injected_paths[injected_indices, -1]))
        # Median impact: % change in terminal equity for injected paths
        clean_terminals = clean_paths[injected_indices, -1]
        injected_terminals = injected_paths[injected_indices, -1]
        impacts = (injected_terminals - clean_terminals) / clean_terminals * 100
        median_impact = float(np.median(impacts))
    else:
        worst_case = float(np.min(injected_paths[:, -1]))
        median_impact = 0.0

    return AdversarialResult(
        clean_paths=clean_paths,
        injected_paths=injected_paths,
        injection_metadata=metadata,
        clean_var_95=c_var95,
        clean_var_99=c_var99,
        clean_median_final=c_median,
        clean_prob_ruin=c_ruin,
        injected_var_95=i_var95,
        injected_var_99=i_var99,
        injected_median_final=i_median,
        injected_prob_ruin=i_ruin,
        worst_case_terminal_equity=worst_case,
        median_impact_pct=median_impact,
    )
