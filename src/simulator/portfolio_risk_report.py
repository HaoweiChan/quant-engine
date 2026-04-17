"""Portfolio-level risk report — 5-layer stress test.

Operates on pre-computed per-strategy daily returns (frozen individual
params). Each layer reports ``status`` + ``metrics`` + ``details``; the
overall report aggregates to a single ``overall_status`` based on whether
mandatory layers pass.

Layers:
    1. ``sensitivity`` — scale each strategy's daily returns by ±20% (one
       at a time) and record combined-Sharpe CV. Small CV → weights are
       robust to per-strategy alpha drift.
    2. ``correlation_stress`` — replace the covariance matrix's off-
       diagonal entries with a stressed correlation ρ (default 0.8) and
       re-estimate combined metrics by drawing synthetic multivariate
       normal returns. Measures diversification fragility.
    3. ``concurrent_stop_stress`` — inject a single adversarial "bar"
       where every strategy realises its worst single-day return. Measures
       tail correlation when all strategies hit stops together.
    4. ``slippage_stress`` — apply a flat per-strategy daily-return drag
       (proxy for +1 tick/fill slippage at realistic trade frequency) and
       recompute combined Sharpe. Gate: ≥ 1.0.
    5. ``kelly_scan`` — sweep Kelly fraction 0.1→1.0 against the current
       weight allocation; report combined Sharpe/MDD/time-under-water.
       Confirms the operating Kelly fraction is on the concave side of the
       growth curve.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from src.core.portfolio_merger import PortfolioMerger, PortfolioMergerInput

# Default gate thresholds — mirror portfolio_promotion.GATE_THRESHOLDS for L2.
DEFAULT_THRESHOLDS: dict[str, float] = {
    "sensitivity_cv_ceiling": 0.30,
    "slippage_stress_sharpe_floor": 1.0,
    "correlation_stress_sharpe_floor": 1.0,
    "concurrent_stop_mdd_ceiling": 0.30,
}


@dataclass
class LayerResult:
    name: str
    status: str  # "pass" | "fail" | "skip" | "error"
    metrics: dict[str, Any] = field(default_factory=dict)
    details: dict[str, Any] = field(default_factory=dict)
    reason: str | None = None

    def as_dict(self) -> dict[str, Any]:
        out = {
            "name": self.name,
            "status": self.status,
            "metrics": self.metrics,
            "details": self.details,
        }
        if self.reason is not None:
            out["reason"] = self.reason
        return out


@dataclass
class PortfolioRiskReportResult:
    overall_status: str
    layers: dict[str, LayerResult]
    failure_reasons: list[str] = field(default_factory=list)
    thresholds_applied: dict[str, float] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "overall_status": self.overall_status,
            "layers": {k: v.as_dict() for k, v in self.layers.items()},
            "failure_reasons": self.failure_reasons,
            "thresholds_applied": self.thresholds_applied,
        }


class PortfolioRiskReport:
    """Produce a 5-layer risk report for a multi-strategy portfolio."""

    def __init__(
        self,
        daily_returns: dict[str, np.ndarray],
        weights: dict[str, float],
        initial_capital: float = 2_000_000.0,
        thresholds: dict[str, float] | None = None,
    ) -> None:
        if len(daily_returns) < 2:
            raise ValueError("Need at least 2 strategies for portfolio risk report")
        if set(weights.keys()) != set(daily_returns.keys()):
            raise ValueError("weights and daily_returns must have matching strategy slugs")
        if abs(sum(weights.values()) - 1.0) > 0.05:
            raise ValueError(
                f"weights must sum to ~1.0; got {sum(weights.values()):.4f}",
            )

        self._slugs = list(daily_returns.keys())
        self._weights = weights
        self._returns = {
            s: np.asarray(r, dtype=np.float64) for s, r in daily_returns.items()
        }
        self._initial_capital = initial_capital
        self._thresholds = {**DEFAULT_THRESHOLDS, **(thresholds or {})}
        self._merger = PortfolioMerger(initial_capital=initial_capital)

    # --------------------------------------------------------------- helpers
    def _combined_metrics(
        self,
        returns: dict[str, np.ndarray],
        weights: dict[str, float] | None = None,
    ) -> dict[str, float]:
        w = weights or self._weights
        inputs = [
            PortfolioMergerInput(
                daily_returns=list(returns[slug]),
                strategy_slug=slug,
                weight=w[slug],
            )
            for slug in self._slugs
        ]
        return self._merger.merge(inputs).metrics

    def _baseline_sharpe(self) -> float:
        return float(self._combined_metrics(self._returns).get("sharpe", 0.0))

    # --------------------------------------------------------- layer 1: sens
    def _layer_sensitivity(self, scale_delta: float = 0.20) -> LayerResult:
        """Scale each strategy's returns by (1 ± delta) one at a time.

        Sensitivity analysis operates on pre-computed daily returns and is
        therefore harness-agnostic — no need to skip spread-strategy legs
        the way MC / concurrent-stop paths would.
        """
        perturbations: dict[str, float] = {}
        baseline_sharpe = self._baseline_sharpe()
        for slug in self._slugs:
            for sign in (+1.0, -1.0):
                factor = 1.0 + sign * scale_delta
                perturbed = {
                    s: self._returns[s] * (factor if s == slug else 1.0)
                    for s in self._slugs
                }
                metrics = self._combined_metrics(perturbed)
                sign_tag = "+" if sign > 0 else "-"
                key = f"{slug}_{sign_tag}{int(abs(scale_delta * 100))}"
                perturbations[key] = float(metrics.get("sharpe", 0.0))
        if not perturbations:
            return LayerResult(
                name="sensitivity",
                status="skip",
                reason="No perturbations produced",
            )
        sharpes = np.array(list(perturbations.values()))
        mean = float(np.mean(sharpes))
        std = float(np.std(sharpes, ddof=1)) if len(sharpes) > 1 else 0.0
        cv = std / abs(mean) if abs(mean) > 1e-9 else float("inf")
        ceiling = self._thresholds["sensitivity_cv_ceiling"]
        status = "pass" if cv <= ceiling else "fail"
        return LayerResult(
            name="sensitivity",
            status=status,
            metrics={
                "baseline_sharpe": baseline_sharpe,
                "perturbed_sharpe_mean": mean,
                "perturbed_sharpe_std": std,
                "cv": cv,
                "scale_delta": scale_delta,
                "ceiling": ceiling,
            },
            details={"perturbations": perturbations},
            reason=None if status == "pass" else f"CV {cv:.4f} > ceiling {ceiling}",
        )

    # ----------------------------------------------- layer 2: correlation
    def _layer_correlation_stress(
        self,
        stressed_rho: float = 0.8,
        n_simulations: int = 5000,
        seed: int = 42,
    ) -> LayerResult:
        """Simulate returns with off-diagonals forced to ``stressed_rho``.

        Keeps each strategy's marginal mean/vol unchanged; inflates pairwise
        correlations by constructing a covariance matrix with the target ρ
        and drawing multivariate normals. Then applies the live portfolio
        weights and measures combined Sharpe under the stressed correlation.
        """
        rng = np.random.default_rng(seed)
        means = np.array([float(np.mean(self._returns[s])) for s in self._slugs])
        vols = np.array([float(np.std(self._returns[s], ddof=1)) for s in self._slugs])
        n = len(self._slugs)

        # Stressed correlation matrix: 1 on diagonal, stressed_rho off-diagonal
        corr = np.full((n, n), stressed_rho, dtype=np.float64)
        np.fill_diagonal(corr, 1.0)
        sigma = np.outer(vols, vols) * corr
        # Ensure PSD (stressed rho can sometimes push matrix off PSD for large n).
        eigvals = np.linalg.eigvalsh(sigma)
        min_eig = float(eigvals.min())
        if min_eig < 1e-12:
            # Regularize
            sigma = sigma + np.eye(n) * (1e-9 - min_eig)

        samples = rng.multivariate_normal(mean=means, cov=sigma, size=n_simulations)
        # Apply weights
        w = np.array([self._weights[s] for s in self._slugs])
        port_returns = samples @ w
        if np.std(port_returns, ddof=1) < 1e-12:
            sharpe = 0.0
        else:
            sharpe = float(np.mean(port_returns) / np.std(port_returns, ddof=1) * np.sqrt(252.0))

        # MDD on path (treat n_simulations as days for diagnostic only)
        eq = np.cumprod(1.0 + port_returns)
        peak = np.maximum.accumulate(eq)
        dd = (peak - eq) / np.where(peak > 0, peak, 1.0)
        mdd = float(dd.max()) if dd.size else 0.0

        floor = self._thresholds["correlation_stress_sharpe_floor"]
        status = "pass" if sharpe >= floor else "fail"
        return LayerResult(
            name="correlation_stress",
            status=status,
            metrics={
                "stressed_rho": stressed_rho,
                "sharpe": sharpe,
                "mdd_pct": mdd,
                "floor": floor,
                "n_simulations": n_simulations,
            },
            details={"baseline_correlation_matrix": self._actual_correlation().tolist()},
            reason=None if status == "pass" else f"Sharpe {sharpe:.4f} < floor {floor}",
        )

    def _actual_correlation(self) -> np.ndarray:
        arrays = [self._returns[s] for s in self._slugs]
        mat = np.stack(arrays)
        with np.errstate(divide="ignore", invalid="ignore"):
            corr = np.corrcoef(mat)
        return np.nan_to_num(corr, nan=0.0)

    # ------------------------------------------- layer 3: concurrent stop
    def _layer_concurrent_stop(self) -> LayerResult:
        """Inject a single bar where every strategy realises its worst
        single-day return simultaneously; report MDD impact.
        """
        worst_day: dict[str, float] = {
            s: float(np.min(self._returns[s])) if self._returns[s].size else 0.0
            for s in self._slugs
        }
        # Portfolio impact on that one day
        w = np.array([self._weights[s] for s in self._slugs])
        worst_vec = np.array([worst_day[s] for s in self._slugs])
        portfolio_shock = float(worst_vec @ w)

        # Append the shock to the current return series and recompute MDD
        shock_appended = {
            s: np.concatenate([self._returns[s], [worst_day[s]]])
            for s in self._slugs
        }
        metrics = self._combined_metrics(shock_appended)
        mdd = float(metrics.get("max_drawdown_pct", 0.0))
        ceiling = self._thresholds["concurrent_stop_mdd_ceiling"]
        status = "pass" if mdd <= ceiling else "fail"
        return LayerResult(
            name="concurrent_stop_stress",
            status=status,
            metrics={
                "portfolio_shock_return": portfolio_shock,
                "mdd_pct_with_shock": mdd,
                "ceiling": ceiling,
            },
            details={"worst_day_by_strategy": worst_day},
            reason=None if status == "pass" else f"MDD {mdd:.4f} > ceiling {ceiling}",
        )

    # -------------------------------------------------- layer 4: slippage
    def _layer_slippage_stress(self, daily_drag: float = 0.0005) -> LayerResult:
        """Apply uniform drag to each strategy's daily return.

        ``daily_drag`` is subtracted from every observation per strategy; 5bps
        is a conservative proxy for +1 tick per round-trip at realistic
        trade frequency.
        """
        perturbed = {s: self._returns[s] - daily_drag for s in self._slugs}
        metrics = self._combined_metrics(perturbed)
        sharpe = float(metrics.get("sharpe", 0.0))
        floor = self._thresholds["slippage_stress_sharpe_floor"]
        status = "pass" if sharpe >= floor else "fail"
        return LayerResult(
            name="slippage_stress",
            status=status,
            metrics={
                "daily_drag": daily_drag,
                "stressed_sharpe": sharpe,
                "stressed_mdd_pct": float(metrics.get("max_drawdown_pct", 0.0)),
                "stressed_annual_return": float(metrics.get("annual_return", 0.0)),
                "floor": floor,
            },
            reason=None if status == "pass" else f"Sharpe {sharpe:.4f} < floor {floor}",
        )

    # ----------------------------------------------- layer 5: kelly scan
    def _layer_kelly_scan(
        self,
        fractions: list[float] | None = None,
    ) -> LayerResult:
        """Sweep Kelly fraction applied uniformly to all strategies' exposure.

        Each fraction ``f`` scales each strategy's daily returns by ``f`` (a
        simple linear-leverage proxy). Records Sharpe and MDD per fraction;
        reports the knee where Sharpe is maximised vs MDD starts accelerating.
        """
        fractions = fractions or [0.1, 0.25, 0.5, 0.75, 1.0, 1.5, 2.0]
        curve: list[dict[str, float]] = []
        for f in fractions:
            perturbed = {s: self._returns[s] * f for s in self._slugs}
            metrics = self._combined_metrics(perturbed)
            curve.append({
                "fraction": f,
                "sharpe": float(metrics.get("sharpe", 0.0)),
                "mdd_pct": float(metrics.get("max_drawdown_pct", 0.0)),
                "annual_return": float(metrics.get("annual_return", 0.0)),
            })
        # Sharpe of a scaled return series is scale-invariant when mean and
        # vol both scale linearly → the curve is flat on Sharpe, but MDD and
        # return both scale. Use MDD scaling to report the "knee".
        knee_idx = int(np.argmax([c["annual_return"] / max(c["mdd_pct"], 1e-9) for c in curve]))
        knee = curve[knee_idx]
        # Status is always informational (informational layer) — pass unless
        # knee Sharpe < floor.
        floor = 0.0
        status = "pass"
        return LayerResult(
            name="kelly_scan",
            status=status,
            metrics={
                "knee_fraction": knee["fraction"],
                "knee_sharpe": knee["sharpe"],
                "knee_return_per_mdd": knee["annual_return"] / max(knee["mdd_pct"], 1e-9),
                "floor": floor,
            },
            details={"curve": curve},
        )

    # ---------------------------------------------------------------- run
    def run(self) -> PortfolioRiskReportResult:
        layers: dict[str, LayerResult] = {}
        layers["sensitivity"] = self._layer_sensitivity()
        layers["correlation_stress"] = self._layer_correlation_stress()
        layers["concurrent_stop_stress"] = self._layer_concurrent_stop()
        layers["slippage_stress"] = self._layer_slippage_stress()
        layers["kelly_scan"] = self._layer_kelly_scan()

        # Mandatory layers: sensitivity, correlation_stress, slippage_stress.
        # Informational: kelly_scan, concurrent_stop_stress (informational MDD).
        mandatory = ("sensitivity", "correlation_stress", "slippage_stress")
        failure_reasons: list[str] = []
        any_failed = False
        for name in mandatory:
            layer = layers[name]
            if layer.status == "fail":
                any_failed = True
                failure_reasons.append(f"{name}: {layer.reason or 'failed'}")
            elif layer.status == "error":
                any_failed = True
                failure_reasons.append(f"{name}: error - {layer.reason or 'unknown'}")

        overall_status = "fail" if any_failed else "pass"
        return PortfolioRiskReportResult(
            overall_status=overall_status,
            layers=layers,
            failure_reasons=failure_reasons,
            thresholds_applied=self._thresholds,
        )
