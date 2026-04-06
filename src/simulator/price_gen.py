"""Synthetic price path generator with composable stochastic processes."""
from __future__ import annotations

import numpy as np
import numpy.typing as npt
from scipy.stats import t as student_t

from src.simulator.types import PRESETS, PathConfig

NDFloat = npt.NDArray[np.float64]


def generate_path(config: PathConfig | None = None, preset: str | None = None) -> NDFloat:
    """Generate a synthetic price path from composable stochastic processes.

    Components (toggled via PathConfig):
      - Base: GBM (drift + diffusion)
      - GARCH(1,1): time-varying volatility
      - Student-t: fat-tailed innovations
      - Poisson jumps: rare large moves
      - OU mean reversion: additive pull toward mu
    """
    if preset is not None:
        config = PRESETS[preset]
    if config is None:
        config = PathConfig()

    rng = np.random.default_rng(config.seed)
    n = config.n_bars
    prices = np.empty(n + 1)
    prices[0] = config.start_price

    innovations = _generate_innovations(rng, n, config)
    sigmas = _generate_volatility(rng, n, config, innovations)
    jumps = _generate_jumps(rng, n, config)
    ou = _generate_ou(rng, n, config)

    for i in range(n):
        log_return = config.drift + sigmas[i] * innovations[i] + jumps[i] + ou[i]
        prices[i + 1] = prices[i] * np.exp(log_return)

    return prices


def generate_paths(
    n_paths: int, config: PathConfig | None = None, preset: str | None = None
) -> NDFloat:
    """Generate multiple price paths. Returns shape (n_paths, n_bars+1)."""
    if preset is not None:
        config = PRESETS[preset]
    if config is None:
        config = PathConfig()
    paths = np.empty((n_paths, config.n_bars + 1))
    for i in range(n_paths):
        cfg = PathConfig(
            drift=config.drift, volatility=config.volatility,
            garch_omega=config.garch_omega, garch_alpha=config.garch_alpha,
            garch_beta=config.garch_beta, student_t_df=config.student_t_df,
            jump_intensity=config.jump_intensity, jump_mean=config.jump_mean,
            jump_std=config.jump_std, ou_theta=config.ou_theta,
            ou_mu=config.ou_mu, ou_sigma=config.ou_sigma,
            n_bars=config.n_bars, start_price=config.start_price,
            seed=config.seed + i if config.seed is not None else None,
        )
        paths[i] = generate_path(cfg)
    return paths


def _generate_innovations(
    rng: np.random.Generator, n: int, config: PathConfig
) -> NDFloat:
    if config.student_t_df > 2:
        raw = student_t.rvs(config.student_t_df, size=n, random_state=rng)
        scale = np.sqrt(config.student_t_df / (config.student_t_df - 2))
        return np.asarray(raw / scale, dtype=np.float64)
    return np.asarray(rng.standard_normal(n), dtype=np.float64)


def _generate_volatility(
    rng: np.random.Generator, n: int, config: PathConfig, innovations: NDFloat
) -> NDFloat:
    if config.garch_alpha > 0 or config.garch_beta > 0:
        sigmas = np.empty(n)
        var = config.volatility**2
        for i in range(n):
            # Standard GARCH(1,1): var_t = omega + alpha * (sigma_{t-1} * epsilon_{t-1})^2 + beta * var_{t-1}
            # Use previous variance to compute previous sigma for the shock term
            prev_sigma = np.sqrt(var) if i > 0 else config.volatility
            shock_term = (
                config.garch_alpha * (prev_sigma * innovations[i - 1]) ** 2
                if i > 0
                else 0.0
            )
            var = config.garch_omega + shock_term + config.garch_beta * var
            sigmas[i] = np.sqrt(max(var, 1e-10))
        return sigmas
    return np.full(n, config.volatility)


def _generate_jumps(
    rng: np.random.Generator, n: int, config: PathConfig
) -> NDFloat:
    if config.jump_intensity > 0:
        jump_arrivals = rng.poisson(config.jump_intensity, size=n)
        jump_sizes = rng.normal(config.jump_mean, config.jump_std, size=n)
        return jump_arrivals * jump_sizes
    return np.zeros(n)


def _generate_ou(
    rng: np.random.Generator, n: int, config: PathConfig
) -> NDFloat:
    if config.ou_theta > 0:
        x = np.empty(n)
        x[0] = 0.0
        for i in range(1, n):
            x[i] = (
                x[i - 1]
                + config.ou_theta * (config.ou_mu - x[i - 1])
                + config.ou_sigma * rng.standard_normal()
            )
        return x
    return np.zeros(n)
