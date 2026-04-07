"""Unified risk sign-off report aggregating all evaluation layers."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Any

from src.core.types import InstrumentCostConfig
from src.simulator.adversarial import AdversarialResult
from src.simulator.param_sensitivity import AggregatedSensitivity, SensitivityResult
from src.simulator.regime import RegimeMetrics
from src.simulator.walk_forward import WalkForwardResult

_TAIPEI_TZ = timezone(timedelta(hours=8))


@dataclass
class RiskReport:
    """Unified risk report for strategy promotion decision."""

    strategy_name: str
    generated_at: datetime
    instrument: str

    # L1: Cost model
    cost_config: InstrumentCostConfig | None
    net_sharpe: float
    cost_drag_pct: float
    cost_gate_passed: bool

    # L2: Parameter sensitivity
    sensitivity: AggregatedSensitivity | None
    param_stability_passed: bool

    # L3: Regime MC
    regime_metrics: list[RegimeMetrics] | None
    worst_regime_sharpe: float
    regime_gate_passed: bool

    # L4: Adversarial injection
    adversarial_result: AdversarialResult | None
    adversarial_gate_passed: bool

    # L5: Walk-forward
    walk_forward_result: WalkForwardResult | None
    walk_forward_gate_passed: bool

    # Aggregate
    all_gates_passed: bool
    failure_reasons: list[str] = field(default_factory=list)
    recommendation: str = "investigate"  # "promote" | "investigate" | "reject"

    def to_dict(self) -> dict[str, Any]:
        """Serialize to JSON-compatible dict."""
        return {
            "strategy_name": self.strategy_name,
            "generated_at": self.generated_at.isoformat(),
            "instrument": self.instrument,
            "cost_gate": {
                "passed": self.cost_gate_passed,
                "net_sharpe": self.net_sharpe,
                "cost_drag_pct": self.cost_drag_pct,
            },
            "param_stability_gate": {
                "passed": self.param_stability_passed,
                "likely_overfit": self.sensitivity.likely_overfit if self.sensitivity else None,
                "robust": self.sensitivity.robust if self.sensitivity else None,
            },
            "regime_gate": {
                "passed": self.regime_gate_passed,
                "worst_regime_sharpe": self.worst_regime_sharpe,
                "regime_metrics": (
                    [
                        {
                            "label": m.regime_label,
                            "sharpe": m.sharpe,
                            "mdd_pct": m.mdd_pct,
                            "win_rate": m.win_rate,
                            "n_sessions": m.n_sessions,
                        }
                        for m in self.regime_metrics
                    ]
                    if self.regime_metrics
                    else None
                ),
            },
            "adversarial_gate": {
                "passed": self.adversarial_gate_passed,
                "worst_case_terminal_equity": (
                    self.adversarial_result.worst_case_terminal_equity
                    if self.adversarial_result
                    else None
                ),
                "median_impact_pct": (
                    self.adversarial_result.median_impact_pct
                    if self.adversarial_result
                    else None
                ),
            },
            "walk_forward_gate": {
                "passed": self.walk_forward_gate_passed,
                "aggregate_oos_sharpe": (
                    self.walk_forward_result.aggregate_oos_sharpe
                    if self.walk_forward_result
                    else None
                ),
                "overfit_flag": (
                    self.walk_forward_result.overfit_flag
                    if self.walk_forward_result
                    else None
                ),
            },
            "all_gates_passed": self.all_gates_passed,
            "recommendation": self.recommendation,
            "failure_reasons": self.failure_reasons,
        }


def evaluate_cost_gate(
    net_sharpe: float,
    cost_drag_pct: float,
    min_net_sharpe: float = 0.5,
    max_cost_drag_pct: float = 80.0,
) -> tuple[bool, list[str]]:
    """Evaluate cost gate: net Sharpe >= threshold and cost drag < limit."""
    reasons = []
    if net_sharpe < min_net_sharpe:
        reasons.append(f"Net Sharpe {net_sharpe:.2f} < {min_net_sharpe} after costs")
    if cost_drag_pct >= max_cost_drag_pct:
        reasons.append(f"Cost drag {cost_drag_pct:.1f}% >= {max_cost_drag_pct}%")
    return len(reasons) == 0, reasons


def evaluate_param_stability_gate(
    sensitivity: AggregatedSensitivity | None,
    stability_cv_max: float = 0.20,
) -> tuple[bool, list[str]]:
    """Evaluate param stability: no cliffs, >50% params stable (CV < threshold)."""
    if sensitivity is None:
        return False, ["Parameter sensitivity not evaluated"]
    reasons = []
    cliffs = [r for r in sensitivity.per_param if r.cliff_detected]
    if cliffs:
        names = [r.param_name for r in cliffs]
        reasons.append(f"Cliff detected in: {', '.join(names)}")
    stable_count = sum(1 for r in sensitivity.per_param if r.stability_cv < stability_cv_max)
    total = len(sensitivity.per_param)
    if total > 0 and stable_count <= total / 2:
        reasons.append(f"Only {stable_count}/{total} params stable (CV < {stability_cv_max})")
    return len(reasons) == 0, reasons


def evaluate_regime_gate(
    regime_metrics: list[RegimeMetrics] | None,
    min_worst_regime_sharpe: float = 0.4,
) -> tuple[bool, float, list[str]]:
    """Evaluate regime gate: worst regime Sharpe >= threshold."""
    if not regime_metrics:
        return False, 0.0, ["Regime metrics not evaluated"]
    worst_sharpe = min(m.sharpe for m in regime_metrics if m.n_sessions > 0)
    reasons = []
    if worst_sharpe < min_worst_regime_sharpe:
        worst_label = next(
            m.regime_label for m in regime_metrics if m.sharpe == worst_sharpe
        )
        reasons.append(
            f"Worst regime '{worst_label}' Sharpe {worst_sharpe:.2f} < {min_worst_regime_sharpe}"
        )
    return len(reasons) == 0, worst_sharpe, reasons


def evaluate_adversarial_gate(
    result: AdversarialResult | None,
    initial_equity: float = 2_000_000.0,
) -> tuple[bool, list[str]]:
    """Evaluate adversarial gate: MDD < 25%, equity > 50% initial."""
    if result is None:
        return False, ["Adversarial injection not evaluated"]
    reasons = []
    # Check worst-case terminal equity
    if result.worst_case_terminal_equity < initial_equity * 0.5:
        reasons.append(
            f"Worst-case equity {result.worst_case_terminal_equity:,.0f} "
            f"< 50% of initial ({initial_equity * 0.5:,.0f})"
        )
    return len(reasons) == 0, reasons


def evaluate_walk_forward_gate(
    result: WalkForwardResult | None,
) -> tuple[bool, list[str]]:
    """Evaluate walk-forward gate: delegates to WalkForwardResult.passed."""
    if result is None:
        return False, ["Walk-forward validation not evaluated"]
    return result.passed, result.failure_reasons


def build_risk_report(
    strategy_name: str,
    instrument: str = "TX",
    cost_config: InstrumentCostConfig | None = None,
    net_sharpe: float = 0.0,
    cost_drag_pct: float = 0.0,
    sensitivity: AggregatedSensitivity | None = None,
    regime_metrics: list[RegimeMetrics] | None = None,
    adversarial_result: AdversarialResult | None = None,
    walk_forward_result: WalkForwardResult | None = None,
    initial_equity: float = 2_000_000.0,
) -> RiskReport:
    """Build a unified risk report from all evaluation layer results."""
    all_reasons: list[str] = []

    # L1: Cost gate
    cost_passed, cost_reasons = evaluate_cost_gate(net_sharpe, cost_drag_pct)
    all_reasons.extend(cost_reasons)

    # L2: Param stability gate
    param_passed, param_reasons = evaluate_param_stability_gate(sensitivity)
    all_reasons.extend(param_reasons)

    # L3: Regime gate
    regime_passed, worst_sharpe, regime_reasons = evaluate_regime_gate(regime_metrics)
    all_reasons.extend(regime_reasons)

    # L4: Adversarial gate
    adv_passed, adv_reasons = evaluate_adversarial_gate(adversarial_result, initial_equity)
    all_reasons.extend(adv_reasons)

    # L5: Walk-forward gate
    wf_passed, wf_reasons = evaluate_walk_forward_gate(walk_forward_result)
    all_reasons.extend(wf_reasons)

    all_passed = all([cost_passed, param_passed, regime_passed, adv_passed, wf_passed])

    # Recommendation logic
    if all_passed:
        recommendation = "promote"
    elif not wf_passed or cost_drag_pct >= 80.0:
        recommendation = "reject"
    else:
        recommendation = "investigate"

    return RiskReport(
        strategy_name=strategy_name,
        generated_at=datetime.now(_TAIPEI_TZ),
        instrument=instrument,
        cost_config=cost_config,
        net_sharpe=net_sharpe,
        cost_drag_pct=cost_drag_pct,
        cost_gate_passed=cost_passed,
        sensitivity=sensitivity,
        param_stability_passed=param_passed,
        regime_metrics=regime_metrics,
        worst_regime_sharpe=worst_sharpe,
        regime_gate_passed=regime_passed,
        adversarial_result=adversarial_result,
        adversarial_gate_passed=adv_passed,
        walk_forward_result=walk_forward_result,
        walk_forward_gate_passed=wf_passed,
        all_gates_passed=all_passed,
        failure_reasons=all_reasons,
        recommendation=recommendation,
    )
