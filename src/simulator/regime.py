"""HMM-based market regime detection for conditioned Monte Carlo simulation."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import numpy.typing as npt


class RegimeModelError(Exception):
    """Raised when HMM regime fitting fails."""


@dataclass
class RegimeModel:
    """Fitted HMM regime model with labeled states."""

    n_states: int
    state_labels: list[str]
    means: list[float]
    variances: list[float]
    transition_matrix: npt.NDArray[np.float64]
    bic: float
    _hmm: object = None  # internal hmmlearn model reference

    def __repr__(self) -> str:
        return (
            f"RegimeModel(n_states={self.n_states}, "
            f"labels={self.state_labels}, "
            f"bic={self.bic:.1f})"
        )


@dataclass
class RegimeMetrics:
    """Performance metrics for a single market regime."""

    regime_label: str
    n_sessions: int
    sharpe: float
    mdd_pct: float
    win_rate: float
    avg_return: float
    total_pnl: float


def fit_regime_model(
    daily_returns: npt.NDArray[np.float64],
    n_states: int = 2,
    seed: int = 42,
    max_iter: int = 200,
) -> RegimeModel:
    """Fit a Gaussian HMM on daily returns to identify market regimes.

    Args:
        daily_returns: 1-D array of daily returns.
        n_states: Number of hidden states (2 or 3).
        seed: Random seed for reproducibility.
        max_iter: Maximum EM iterations.

    Returns:
        A fitted RegimeModel with states labeled by ascending variance.

    Raises:
        RegimeModelError: If the HMM fails to converge.
    """
    from hmmlearn.hmm import GaussianHMM

    returns = daily_returns.reshape(-1, 1)
    model = GaussianHMM(
        n_components=n_states,
        covariance_type="full",
        n_iter=max_iter,
        random_state=seed,
    )
    model.fit(returns)

    if not model.monitor_.converged:
        raise RegimeModelError(
            f"HMM failed to converge after {max_iter} iterations. "
            f"Log-likelihood history: {model.monitor_.history[-3:]}"
        )

    # Extract per-state variance and sort by ascending variance
    variances = [float(model.covars_[i][0, 0]) for i in range(n_states)]
    sort_idx = np.argsort(variances)

    sorted_means = [float(model.means_[i][0]) for i in sort_idx]
    sorted_vars = [variances[i] for i in sort_idx]
    sorted_transmat = model.transmat_[np.ix_(sort_idx, sort_idx)]

    # Label states by ascending variance
    if n_states == 2:
        labels = ["low_vol", "high_vol"]
    elif n_states == 3:
        labels = ["low_vol", "medium_vol", "high_vol"]
    else:
        labels = [f"state_{i}" for i in range(n_states)]

    # Compute BIC
    n_params = n_states * n_states + 2 * n_states - 1  # transmat + means + vars
    log_likelihood = model.score(returns)
    bic = -2 * log_likelihood * len(returns) + n_params * np.log(len(returns))

    # Build index mapping: original_state -> sorted_position
    inv_sort = np.argsort(sort_idx)

    return RegimeModel(
        n_states=n_states,
        state_labels=labels,
        means=sorted_means,
        variances=sorted_vars,
        transition_matrix=sorted_transmat,
        bic=float(bic),
        _hmm=(model, inv_sort),
    )


def label_regimes(
    model: RegimeModel,
    daily_returns: npt.NDArray[np.float64],
) -> npt.NDArray[np.int64]:
    """Label each return with its regime index using Viterbi decoding.

    Returns:
        Array of regime indices (0-based, sorted by ascending variance)
        of the same length as daily_returns.
    """
    hmm, inv_sort = model._hmm
    returns = daily_returns.reshape(-1, 1)
    raw_labels = hmm.predict(returns)
    # Map original HMM state indices to our sorted indices
    sorted_labels = np.array([int(inv_sort[s]) for s in raw_labels], dtype=np.int64)
    return sorted_labels


def compute_regime_metrics(
    returns: npt.NDArray[np.float64],
    labels: npt.NDArray[np.int64],
    model: RegimeModel,
    periods_per_year: float = 252.0,
) -> list[RegimeMetrics]:
    """Compute per-regime performance metrics.

    Args:
        returns: Array of returns (same length as labels).
        labels: Regime labels from label_regimes().
        model: The fitted RegimeModel for label names.
        periods_per_year: Annualization factor.
    """
    results = []
    for state_idx in range(model.n_states):
        mask = labels == state_idx
        regime_returns = returns[mask]
        n = int(np.sum(mask))
        if n == 0:
            results.append(RegimeMetrics(
                regime_label=model.state_labels[state_idx],
                n_sessions=0,
                sharpe=0.0,
                mdd_pct=0.0,
                win_rate=0.0,
                avg_return=0.0,
                total_pnl=0.0,
            ))
            continue

        avg_ret = float(np.mean(regime_returns))
        std_ret = float(np.std(regime_returns))
        sharpe = (
            avg_ret / std_ret * np.sqrt(periods_per_year)
            if std_ret > 0
            else 0.0
        )

        # MDD within regime segments
        equity = np.cumprod(1 + regime_returns)
        running_max = np.maximum.accumulate(equity)
        drawdowns = (running_max - equity) / running_max
        mdd = float(np.max(drawdowns)) * 100.0 if len(drawdowns) > 0 else 0.0

        win_rate = float(np.mean(regime_returns > 0)) * 100.0
        total_pnl = float(np.sum(regime_returns))

        results.append(RegimeMetrics(
            regime_label=model.state_labels[state_idx],
            n_sessions=n,
            sharpe=float(sharpe),
            mdd_pct=mdd,
            win_rate=win_rate,
            avg_return=avg_ret,
            total_pnl=total_pnl,
        ))
    return results
