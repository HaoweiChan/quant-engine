"""Kelly-fractional multi-strategy capital allocator.

Given a vector of per-strategy mean returns μ and a covariance matrix Σ,
the growth-optimal capital fraction is w* = Σ⁻¹μ. The Kelly fraction f
scales this down: w = f × Σ⁻¹μ. A quarter-Kelly (f=0.25) is the
industry-standard conservative operating point — captures ~70% of the
growth rate at ~25% of the MDD risk of full Kelly.

This module is a pure math utility. The PortfolioSizer wires Kelly
weights into the live sizing decision (see ``src/core/sizing.py``).

Robustness:
- Uses ``scipy.linalg.solve`` (LU decomposition) instead of matrix
  inversion — faster and more numerically stable.
- Falls back to equal-weight (with structlog warning) when Σ is singular
  or all Kelly weights collapse to zero/negative.
- Optionally clips negative weights to zero for long-only portfolios
  (default True — the live TAIFEX book is long-biased).
- Renormalizes if the sum of clipped Kelly weights exceeds 1.0.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

import numpy as np
import structlog
from scipy import linalg

logger = structlog.get_logger(__name__)


@dataclass
class KellyResult:
    """Output from ``compute_kelly_fractions``."""

    weights: dict[str, float]
    fraction: float
    method: str  # "kelly" | "fallback_equal"
    warnings: list[str] = field(default_factory=list)


def compute_kelly_fractions(
    mu: dict[str, float] | Sequence[float] | np.ndarray,
    sigma: (
        dict[str, dict[str, float]]
        | Sequence[Sequence[float]]
        | np.ndarray
    ),
    strategy_slugs: Sequence[str] | None = None,
    fraction: float = 0.25,
    long_only: bool = True,
) -> KellyResult:
    """Compute Kelly-fractional capital allocation.

    Args:
        mu: Mean-return vector. Either a dict ``{slug: float}`` or a
            flat sequence/ndarray (requires ``strategy_slugs``).
        sigma: Covariance matrix. Either a nested dict
            ``{slug: {slug: float}}`` or a 2D sequence/ndarray of
            shape ``(n, n)``.
        strategy_slugs: Strategy names in canonical order. Required
            whenever ``mu`` is not a dict.
        fraction: Kelly fraction (e.g. 0.25 for quarter-Kelly).
            Must be in ``(0, 1]``.
        long_only: If True, clip negative Kelly weights to zero.
            Default True (long-biased TAIFEX book).

    Returns:
        ``KellyResult``. On success, ``method="kelly"`` and
        ``weights[slug]`` sums to ≤ 1 (renormalized down when raw Kelly
        over-leverages). On singular Sigma or non-positive total,
        ``method="fallback_equal"`` with an equal-weight vector.

    Raises:
        ValueError: On malformed inputs (shape mismatch, bad fraction).
    """
    warnings_: list[str] = []

    # Normalise inputs to ndarrays + slug list
    if isinstance(mu, dict):
        slugs = list(mu.keys())
        mu_arr = np.array([mu[s] for s in slugs], dtype=np.float64)
    else:
        mu_arr = np.asarray(mu, dtype=np.float64)
        if strategy_slugs is None:
            raise ValueError("strategy_slugs is required when mu is not a dict")
        slugs = list(strategy_slugs)

    if isinstance(sigma, dict):
        sigma_arr = np.array(
            [[sigma[s1][s2] for s2 in slugs] for s1 in slugs],
            dtype=np.float64,
        )
    else:
        sigma_arr = np.asarray(sigma, dtype=np.float64)

    n = len(slugs)
    if mu_arr.shape != (n,):
        raise ValueError(f"mu shape {mu_arr.shape} does not match strategy count {n}")
    if sigma_arr.shape != (n, n):
        raise ValueError(f"sigma shape {sigma_arr.shape} does not match ({n}, {n})")
    if not 0.0 < fraction <= 1.0:
        raise ValueError(f"fraction must be in (0, 1]; got {fraction}")

    # Solve Sigma @ w_raw = mu  →  w_raw = Sigma^-1 @ mu
    try:
        raw_weights = linalg.solve(sigma_arr, mu_arr, assume_a="sym")
    except (linalg.LinAlgError, ValueError) as exc:
        msg = f"Singular covariance matrix: {exc}; using equal-weight fallback"
        warnings_.append(msg)
        logger.warning(
            "kelly_sizer_fallback",
            reason="singular_covariance",
            error=str(exc),
            strategies=slugs,
        )
        return _equal_weight_result(slugs, fraction, warnings_)

    kelly_weights = fraction * raw_weights

    if long_only:
        n_negative = int(np.sum(kelly_weights < 0))
        if n_negative > 0:
            warnings_.append(
                f"{n_negative} strategies had negative Kelly weight (clipped to 0)",
            )
        kelly_weights = np.clip(kelly_weights, 0.0, None)

    total = float(kelly_weights.sum())
    if total <= 0:
        warnings_.append("All Kelly weights non-positive; using equal-weight fallback")
        logger.warning(
            "kelly_sizer_fallback",
            reason="non_positive_total",
            total=total,
            strategies=slugs,
        )
        return _equal_weight_result(slugs, fraction, warnings_)

    if total > 1.0:
        warnings_.append(f"Raw Kelly sum={total:.4f} > 1; renormalized to 1")
        kelly_weights = kelly_weights / total

    return KellyResult(
        weights={s: float(w) for s, w in zip(slugs, kelly_weights, strict=True)},
        fraction=fraction,
        method="kelly",
        warnings=warnings_,
    )


def _equal_weight_result(
    slugs: list[str],
    fraction: float,
    warnings_: list[str],
) -> KellyResult:
    """Return a fraction-scaled equal-weight allocation as fallback."""
    n = len(slugs)
    equal = fraction / n
    return KellyResult(
        weights={s: equal for s in slugs},
        fraction=fraction,
        method="fallback_equal",
        warnings=warnings_,
    )


def covariance_from_returns(
    daily_returns: dict[str, np.ndarray] | dict[str, Sequence[float]],
    annualize: bool = True,
    periods_per_year: float = 252.0,
) -> tuple[dict[str, float], dict[str, dict[str, float]]]:
    """Compute (mu, Sigma) from per-strategy daily-return arrays.

    Convenience for wiring Kelly into live code: the live runner has a
    rolling daily-returns buffer per strategy; this function estimates μ
    and Σ annualized (or left daily if ``annualize=False``).

    Returns:
        Tuple ``(mu_dict, sigma_dict)`` keyed by strategy slug.
    """
    slugs = list(daily_returns.keys())
    if len(slugs) < 2:
        raise ValueError("Need at least 2 strategies for covariance estimation")

    aligned = np.stack(
        [np.asarray(daily_returns[s], dtype=np.float64) for s in slugs],
    )
    if aligned.shape[1] < 2:
        raise ValueError(
            f"Need at least 2 observations per strategy for covariance "
            f"estimation; got {aligned.shape[1]}",
        )
    mean = aligned.mean(axis=1)  # per-strategy daily mean
    cov = np.cov(aligned, ddof=1)  # daily covariance

    if annualize:
        mean = mean * periods_per_year
        cov = cov * periods_per_year

    mu_dict = {s: float(mean[i]) for i, s in enumerate(slugs)}
    sigma_dict = {
        s1: {s2: float(cov[i, j]) for j, s2 in enumerate(slugs)}
        for i, s1 in enumerate(slugs)
    }
    return mu_dict, sigma_dict
