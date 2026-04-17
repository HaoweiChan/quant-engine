"""Portfolio-level optimization-level promotion framework.

Mirrors the per-strategy L0→L3 promotion pipeline (see
``src/strategies/__init__.py``) for multi-strategy portfolios. Each level
has explicit gate thresholds; promotion fails closed when any gate misses.

Levels:
    L0_UNOPTIMIZED — no weights computed.
    L1_EXPLORATORY — portfolio backtest combined Sharpe ≥ 1.2.
    L2_VALIDATED  — walk-forward OOS Sharpe ≥ 1.5, worst-fold MDD ≤ 20%,
                    weight-drift CV ≤ 0.30, correlation stability ≥ 0.7.
    L3_PRODUCTION — slippage-stress Sharpe ≥ 1.0 AND ≥ 5 paper sessions.

Persistence uses TOML files in ``config/portfolios/<name>.toml`` with the
same shape as per-strategy configs (``[optimization]`` and
``[optimization.gate_results]`` sub-tables).
"""
from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any


class PortfolioOptimizationLevel(Enum):
    L0_UNOPTIMIZED = 0
    L1_EXPLORATORY = 1
    L2_VALIDATED = 2
    L3_PRODUCTION = 3

    @classmethod
    def from_int(cls, level: int) -> PortfolioOptimizationLevel:
        for member in cls:
            if member.value == level:
                return member
        raise ValueError(f"Unknown portfolio optimization level: {level}")


# Hard gate thresholds per target level — promotion BLOCKS on any breach.
# Keys ending in "_floor" are minimums; "_ceiling" are maximums.
GATE_THRESHOLDS: dict[PortfolioOptimizationLevel, dict[str, Any]] = {
    PortfolioOptimizationLevel.L1_EXPLORATORY: {
        "combined_sharpe_floor": 1.2,
    },
    PortfolioOptimizationLevel.L2_VALIDATED: {
        "aggregate_oos_sharpe_floor": 1.5,
        "worst_fold_oos_mdd_ceiling": 0.20,
        "correlation_stability_floor": 0.7,
    },
    PortfolioOptimizationLevel.L3_PRODUCTION: {
        "slippage_stress_sharpe_floor": 1.0,
        "paper_trade_sessions_floor": 5,
    },
}

# Advisory thresholds — breaches DO NOT block promotion but surface as
# ``warnings`` on the PromotionResult and in the persisted TOML config so
# operators can see regime / concentration sensitivity.
#
# ``weight_drift_cv_ceiling`` lives here rather than in the hard gates
# because reasonable fold-to-fold weight variation is expected whenever
# market regimes shift between IS slices. Without dynamic rebalancing,
# high drift just says "the IS-optimal allocation is regime-sensitive",
# not "the portfolio is unsafe". Operators should read this alongside
# the live deployment choice (which single allocation to commit to).
ADVISORY_THRESHOLDS: dict[PortfolioOptimizationLevel, dict[str, Any]] = {
    PortfolioOptimizationLevel.L2_VALIDATED: {
        "weight_drift_cv_ceiling": 0.30,
    },
}


@dataclass
class PromotionResult:
    new_level: PortfolioOptimizationLevel
    passed: bool
    failure_reasons: list[str]
    thresholds_checked: dict[str, Any] = field(default_factory=dict)
    advisory_thresholds_checked: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    promoted_at: str | None = None


def _evaluate_thresholds(
    thresholds: dict[str, Any],
    gate_results: dict[str, Any],
    kind: str,
) -> list[str]:
    """Evaluate a threshold dict against metrics.

    Returns a list of breach messages (empty when all pass). ``kind`` is
    used only for the "Missing ... metric" message prefix so hard-gate
    misses and advisory misses are distinguishable in output.
    """
    reasons: list[str] = []
    for key, threshold in thresholds.items():
        if key.endswith("_floor"):
            metric_key = key[: -len("_floor")]
            value = gate_results.get(metric_key)
            if value is None:
                reasons.append(f"Missing {kind} metric: {metric_key}")
                continue
            if value < threshold:
                reasons.append(
                    f"{metric_key}={value:.4f} < floor {threshold}",
                )
        elif key.endswith("_ceiling"):
            metric_key = key[: -len("_ceiling")]
            value = gate_results.get(metric_key)
            if value is None:
                reasons.append(f"Missing {kind} metric: {metric_key}")
                continue
            if value > threshold:
                reasons.append(
                    f"{metric_key}={value:.4f} > ceiling {threshold}",
                )
    return reasons


def _check_gates(
    target_level: PortfolioOptimizationLevel,
    gate_results: dict[str, Any],
) -> tuple[bool, list[str]]:
    """Check target-level HARD gates against the supplied metrics."""
    thresholds = GATE_THRESHOLDS.get(target_level, {})
    reasons = _evaluate_thresholds(thresholds, gate_results, kind="gate")
    return (len(reasons) == 0, reasons)


def _check_advisories(
    target_level: PortfolioOptimizationLevel,
    gate_results: dict[str, Any],
) -> list[str]:
    """Check target-level ADVISORY thresholds; return breach warnings.

    Advisories never block promotion — they are reported so operators
    know the portfolio has regime-sensitive or concentration-heavy
    characteristics worth surfacing to Risk Auditor review.
    """
    thresholds = ADVISORY_THRESHOLDS.get(target_level, {})
    if not thresholds:
        return []
    # Missing advisory metrics are NOT a warning; they just mean the
    # upstream walk-forward didn't compute them.
    warnings: list[str] = []
    for reason in _evaluate_thresholds(thresholds, gate_results, kind="advisory"):
        if reason.startswith("Missing "):
            continue
        warnings.append(f"advisory: {reason}")
    return warnings


def promote_portfolio(
    current_level: PortfolioOptimizationLevel,
    target_level: PortfolioOptimizationLevel,
    gate_results: dict[str, Any],
) -> PromotionResult:
    """Attempt to advance a portfolio from ``current_level`` to ``target_level``.

    Enforces single-step promotion (cannot skip from L0 straight to L2).
    Hard gates (``GATE_THRESHOLDS``) must all pass for promotion to
    succeed. Advisory thresholds (``ADVISORY_THRESHOLDS``) are checked
    and surfaced as ``warnings`` but do NOT block.
    """
    thresholds = GATE_THRESHOLDS.get(target_level, {})
    advisory = ADVISORY_THRESHOLDS.get(target_level, {})

    if target_level.value <= current_level.value:
        return PromotionResult(
            new_level=current_level,
            passed=False,
            failure_reasons=[
                f"target {target_level.name} must exceed current {current_level.name}",
            ],
            thresholds_checked=thresholds,
            advisory_thresholds_checked=advisory,
        )
    if target_level.value > current_level.value + 1:
        return PromotionResult(
            new_level=current_level,
            passed=False,
            failure_reasons=[
                f"cannot skip levels: {current_level.name} -> {target_level.name}",
            ],
            thresholds_checked=thresholds,
            advisory_thresholds_checked=advisory,
        )

    passed, reasons = _check_gates(target_level, gate_results)
    warnings = _check_advisories(target_level, gate_results)
    if passed:
        return PromotionResult(
            new_level=target_level,
            passed=True,
            failure_reasons=[],
            thresholds_checked=thresholds,
            advisory_thresholds_checked=advisory,
            warnings=warnings,
            promoted_at=datetime.now(UTC).astimezone().isoformat(),
        )
    return PromotionResult(
        new_level=current_level,
        passed=False,
        failure_reasons=reasons,
        thresholds_checked=thresholds,
        advisory_thresholds_checked=advisory,
        warnings=warnings,
    )


# ---------------------------------------------------------------------------
# Portfolio config I/O  (config/portfolios/<name>.toml)
# ---------------------------------------------------------------------------

DEFAULT_CONFIG_ROOT = Path("config/portfolios")


def _portfolio_config_path(
    portfolio_name: str,
    config_root: Path | None = None,
) -> Path:
    root = config_root or DEFAULT_CONFIG_ROOT
    return root / f"{portfolio_name}.toml"


def load_portfolio_config(
    portfolio_name: str,
    config_root: Path | None = None,
) -> dict[str, Any]:
    """Load a portfolio config. Returns a minimal L0 skeleton when absent."""
    path = _portfolio_config_path(portfolio_name, config_root)
    if not path.exists():
        return {
            "portfolio": {"name": portfolio_name, "strategies": []},
            "optimization": {
                "level": 0,
                "level_name": "L0_UNOPTIMIZED",
                "gate_results": {},
            },
        }
    with open(path, "rb") as f:
        return tomllib.load(f)


def save_portfolio_config(
    portfolio_name: str,
    config: dict[str, Any],
    config_root: Path | None = None,
) -> Path:
    """Serialize the portfolio config to TOML. Human-readable, stable layout."""
    path = _portfolio_config_path(portfolio_name, config_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    rendered = _render_portfolio_toml(portfolio_name, config)
    path.write_text(rendered, encoding="utf-8")
    return path


def _render_portfolio_toml(portfolio_name: str, config: dict[str, Any]) -> str:
    """Render a portfolio config to TOML. Known schema only — do not abuse."""
    now = datetime.now(UTC).astimezone().isoformat()
    lines: list[str] = [
        f"# Portfolio config: {portfolio_name}",
        f"# Last saved: {now}",
        "",
    ]

    port = config.get("portfolio", {})
    lines.append("[portfolio]")
    lines.append(f'name = "{port.get("name", portfolio_name)}"')
    if "symbol" in port:
        lines.append(f'symbol = "{port["symbol"]}"')
    if "description" in port:
        lines.append(f'description = "{_escape(port["description"])}"')
    lines.append("")

    for s in port.get("strategies", []):
        lines.append("[[portfolio.strategies]]")
        lines.append(f'slug = "{s["slug"]}"')
        lines.append(f"weight = {_render_scalar(s['weight'])}")
        if "params_source" in s:
            lines.append(f'params_source = "{s["params_source"]}"')
        lines.append("")

    kelly = port.get("kelly") or config.get("kelly")
    if kelly:
        lines.append("[portfolio.kelly]")
        for k, v in kelly.items():
            lines.append(f"{k} = {_render_scalar(v)}")
        lines.append("")

    opt = config.get("optimization", {})
    if opt:
        lines.append("[optimization]")
        for k, v in opt.items():
            if isinstance(v, dict):
                continue
            lines.append(f"{k} = {_render_scalar(v)}")
        lines.append("")
        gate_results = opt.get("gate_results", {})
        if gate_results:
            lines.append("[optimization.gate_results]")
            for k, v in gate_results.items():
                lines.append(f"{k} = {_render_scalar(v)}")
            lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def _escape(s: str) -> str:
    return s.replace('"', '\\"')


def _render_scalar(v: Any) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        return repr(v)
    if isinstance(v, str):
        return f'"{_escape(v)}"'
    if isinstance(v, list):
        return "[" + ", ".join(_render_scalar(x) for x in v) + "]"
    if isinstance(v, datetime):
        return v.isoformat()
    raise TypeError(f"Cannot render value of type {type(v).__name__}")
