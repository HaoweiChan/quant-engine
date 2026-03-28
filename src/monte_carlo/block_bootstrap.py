"""Block-bootstrap Monte Carlo simulation with stationary, circular, and GARCH methods."""
from __future__ import annotations

import warnings
from dataclasses import dataclass
from typing import Literal

import numpy as np
import structlog

logger = structlog.get_logger(__name__)

MCMethod = Literal["stationary", "circular", "garch"]


@dataclass
class MCSimulationResult:
    paths: list[list[float]]
    var_95: float
    var_99: float
    cvar_95: float
    cvar_99: float
    median_final: float
    prob_ruin: float
    method: str
    n_paths: int
    n_days: int


def _optimal_block_length(returns: np.ndarray) -> int:
    """Politis-Romano automatic block length selection (simplified)."""
    n = len(returns)
    if n < 20:
        return max(1, n // 2)
    acf_vals = np.correlate(returns - returns.mean(), returns - returns.mean(), mode="full")
    acf_vals = acf_vals[n - 1:] / acf_vals[n - 1]
    # Find first zero-crossing
    for lag in range(1, min(n // 3, 100)):
        if acf_vals[lag] < 0:
            break
    else:
        lag = min(n // 3, 20)
    block_len = max(2, int(np.ceil(1.5 * lag)))
    return min(block_len, n // 3)


class BlockBootstrapMC:
    """Block-bootstrap Monte Carlo with multiple methods."""

    def __init__(
        self,
        returns: np.ndarray,
        initial_equity: float = 1_000_000.0,
        ruin_threshold: float = 0.5,
    ) -> None:
        self._returns = np.asarray(returns, dtype=np.float64)
        self._initial_equity = initial_equity
        self._ruin_threshold = ruin_threshold
        self._garch_resid: np.ndarray | None = None
        self._garch_params: dict | None = None

    def fit(self, method: MCMethod = "stationary") -> None:
        """Pre-fit any models required by the chosen method."""
        if method == "garch":
            self._fit_garch()

    def _fit_garch(self) -> None:
        """Fit GARCH(1,1) and store standardized residuals."""
        try:
            from arch import arch_model
            scaled = self._returns * 100
            am = arch_model(scaled, vol="Garch", p=1, q=1, mean="Constant", dist="normal")
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                res = am.fit(disp="off", show_warning=False)
            cond_vol = res.conditional_volatility
            resid = res.resid
            mask = cond_vol > 1e-10
            std_resid = np.zeros_like(resid)
            std_resid[mask] = resid[mask] / cond_vol[mask]
            self._garch_resid = std_resid
            self._garch_params = {
                "omega": res.params.get("omega", 0.01),
                "alpha": res.params.get("alpha[1]", 0.05),
                "beta": res.params.get("beta[1]", 0.90),
                "mu": res.params.get("mu", 0.0),
                "last_vol": float(cond_vol.iloc[-1]) if hasattr(cond_vol, "iloc") else float(cond_vol[-1]),
            }
            logger.info("garch_fitted", omega=self._garch_params["omega"],
                        alpha=self._garch_params["alpha"], beta=self._garch_params["beta"])
        except Exception as exc:
            logger.warning("garch_fit_failed_fallback_to_stationary", error=str(exc))
            self._garch_resid = None
            self._garch_params = None

    def simulate(
        self,
        n_paths: int = 500,
        n_days: int = 252,
        method: MCMethod = "stationary",
        seed: int | None = None,
    ) -> MCSimulationResult:
        rng = np.random.default_rng(seed)
        if method == "garch" and self._garch_resid is not None and self._garch_params is not None:
            sim_returns = self._simulate_garch(n_paths, n_days, rng)
        elif method == "circular":
            sim_returns = self._simulate_circular(n_paths, n_days, rng)
        else:
            sim_returns = self._simulate_stationary(n_paths, n_days, rng)
        paths = self._returns_to_equity_paths(sim_returns)
        finals = np.array([p[-1] for p in paths])
        ruin_level = self._initial_equity * self._ruin_threshold
        return MCSimulationResult(
            paths=paths,
            var_95=float(np.percentile(finals, 5)),
            var_99=float(np.percentile(finals, 1)),
            cvar_95=float(np.mean(finals[finals <= np.percentile(finals, 5)])),
            cvar_99=float(np.mean(finals[finals <= np.percentile(finals, 1)])),
            median_final=float(np.median(finals)),
            prob_ruin=float(np.mean(np.min(np.array([[self._initial_equity] + p for p in paths])[:, :], axis=1) < ruin_level)),
            method=method,
            n_paths=n_paths,
            n_days=n_days,
        )

    def _simulate_stationary(self, n_paths: int, n_days: int, rng: np.random.Generator) -> np.ndarray:
        """Stationary block bootstrap (Politis-Romano geometric block length)."""
        n = len(self._returns)
        avg_block_len = _optimal_block_length(self._returns)
        prob_new_block = 1.0 / avg_block_len
        out = np.empty((n_paths, n_days))
        for i in range(n_paths):
            idx = rng.integers(0, n)
            for d in range(n_days):
                out[i, d] = self._returns[idx % n]
                if rng.random() < prob_new_block:
                    idx = rng.integers(0, n)
                else:
                    idx += 1
        return out

    def _simulate_circular(self, n_paths: int, n_days: int, rng: np.random.Generator) -> np.ndarray:
        """Circular block bootstrap with fixed block length."""
        n = len(self._returns)
        block_len = _optimal_block_length(self._returns)
        n_blocks = (n_days + block_len - 1) // block_len
        out = np.empty((n_paths, n_days))
        for i in range(n_paths):
            sampled: list[float] = []
            for _ in range(n_blocks):
                start = rng.integers(0, n)
                for j in range(block_len):
                    sampled.append(self._returns[(start + j) % n])
            out[i, :] = sampled[:n_days]
        return out

    def _simulate_garch(self, n_paths: int, n_days: int, rng: np.random.Generator) -> np.ndarray:
        """GARCH-filtered residual bootstrap: block-resample standardized residuals, then reconstruct."""
        assert self._garch_resid is not None and self._garch_params is not None
        resid = self._garch_resid
        n = len(resid)
        block_len = _optimal_block_length(resid)
        p = self._garch_params
        omega, alpha, beta = p["omega"], p["alpha"], p["beta"]
        mu = p["mu"]
        last_vol = p["last_vol"]
        n_blocks = (n_days + block_len - 1) // block_len
        out = np.empty((n_paths, n_days))
        for i in range(n_paths):
            # Block-resample residuals
            sampled_z: list[float] = []
            for _ in range(n_blocks):
                start = rng.integers(0, n)
                for j in range(block_len):
                    sampled_z.append(resid[(start + j) % n])
            z = sampled_z[:n_days]
            # Reconstruct returns using GARCH(1,1) recursion
            vol_sq = last_vol ** 2
            for d in range(n_days):
                vol = np.sqrt(max(vol_sq, 1e-10))
                ret_scaled = mu + vol * z[d]
                out[i, d] = ret_scaled / 100.0
                vol_sq = omega + alpha * (ret_scaled - mu) ** 2 + beta * vol_sq
        return out

    def _returns_to_equity_paths(self, sim_returns: np.ndarray) -> list[list[float]]:
        """Convert simulated return arrays to equity paths."""
        paths: list[list[float]] = []
        for i in range(sim_returns.shape[0]):
            equity = self._initial_equity
            path = [equity]
            for d in range(sim_returns.shape[1]):
                equity *= 1 + sim_returns[i, d]
                path.append(equity)
            paths.append(path)
        return paths
