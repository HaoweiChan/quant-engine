"""Tests for BlockBootstrapMC."""
from __future__ import annotations

import numpy as np
import pytest

from src.monte_carlo.block_bootstrap import (
    BlockBootstrapMC,
    MCSimulationResult,
    _optimal_block_length,
)


@pytest.fixture
def trending_returns() -> np.ndarray:
    """Synthetic returns with positive serial correlation."""
    rng = np.random.default_rng(42)
    n = 500
    raw = rng.normal(0.0003, 0.01, n)
    # AR(1) with rho=0.3 to create serial correlation
    out = np.empty(n)
    out[0] = raw[0]
    for i in range(1, n):
        out[i] = 0.3 * out[i - 1] + raw[i]
    return out


@pytest.fixture
def iid_returns() -> np.ndarray:
    """Pure i.i.d. returns (no serial correlation)."""
    rng = np.random.default_rng(99)
    return rng.normal(0.0003, 0.012, 300)


class TestOptimalBlockLength:
    def test_returns_positive_integer(self, iid_returns: np.ndarray):
        bl = _optimal_block_length(iid_returns)
        assert isinstance(bl, int)
        assert bl >= 2

    def test_short_series(self):
        short = np.random.default_rng(1).normal(0, 0.01, 10)
        bl = _optimal_block_length(short)
        assert 1 <= bl <= 5

    def test_correlated_returns_reasonable_length(self, trending_returns: np.ndarray):
        bl = _optimal_block_length(trending_returns)
        assert 2 <= bl <= len(trending_returns) // 3


class TestStationaryBootstrap:
    def test_result_type(self, iid_returns: np.ndarray):
        mc = BlockBootstrapMC(iid_returns, initial_equity=1_000_000)
        result = mc.simulate(n_paths=50, n_days=60, method="stationary", seed=1)
        assert isinstance(result, MCSimulationResult)
        assert result.method == "stationary"
        assert result.n_paths == 50
        assert result.n_days == 60

    def test_path_shape(self, iid_returns: np.ndarray):
        mc = BlockBootstrapMC(iid_returns, initial_equity=1_000_000)
        result = mc.simulate(n_paths=20, n_days=100, method="stationary", seed=2)
        assert len(result.paths) == 20
        # n_days returns + 1 for initial equity
        assert len(result.paths[0]) == 101

    def test_deterministic_with_seed(self, iid_returns: np.ndarray):
        mc = BlockBootstrapMC(iid_returns, initial_equity=1_000_000)
        r1 = mc.simulate(n_paths=30, n_days=50, method="stationary", seed=42)
        r2 = mc.simulate(n_paths=30, n_days=50, method="stationary", seed=42)
        assert r1.paths == r2.paths
        assert r1.var_95 == r2.var_95

    def test_var_ordering(self, iid_returns: np.ndarray):
        mc = BlockBootstrapMC(iid_returns, initial_equity=1_000_000)
        result = mc.simulate(n_paths=200, n_days=252, method="stationary", seed=7)
        assert result.var_99 <= result.var_95

    def test_cvar_less_than_var(self, iid_returns: np.ndarray):
        mc = BlockBootstrapMC(iid_returns, initial_equity=1_000_000)
        result = mc.simulate(n_paths=200, n_days=252, method="stationary", seed=7)
        assert result.cvar_95 <= result.var_95
        assert result.cvar_99 <= result.var_99

    def test_prob_ruin_range(self, iid_returns: np.ndarray):
        mc = BlockBootstrapMC(iid_returns, initial_equity=1_000_000, ruin_threshold=0.5)
        result = mc.simulate(n_paths=100, n_days=252, method="stationary", seed=3)
        assert 0.0 <= result.prob_ruin <= 1.0

    def test_initial_equity_in_paths(self, iid_returns: np.ndarray):
        eq = 2_000_000.0
        mc = BlockBootstrapMC(iid_returns, initial_equity=eq)
        result = mc.simulate(n_paths=10, n_days=50, method="stationary", seed=5)
        for path in result.paths:
            assert path[0] == eq


class TestCircularBootstrap:
    def test_result_method(self, iid_returns: np.ndarray):
        mc = BlockBootstrapMC(iid_returns, initial_equity=1_000_000)
        result = mc.simulate(n_paths=30, n_days=60, method="circular", seed=10)
        assert result.method == "circular"

    def test_deterministic_with_seed(self, iid_returns: np.ndarray):
        mc = BlockBootstrapMC(iid_returns, initial_equity=1_000_000)
        r1 = mc.simulate(n_paths=30, n_days=50, method="circular", seed=42)
        r2 = mc.simulate(n_paths=30, n_days=50, method="circular", seed=42)
        assert r1.paths == r2.paths


class TestGARCHBootstrap:
    def test_garch_fit_and_simulate(self, trending_returns: np.ndarray):
        mc = BlockBootstrapMC(trending_returns, initial_equity=1_000_000)
        mc.fit(method="garch")
        result = mc.simulate(n_paths=50, n_days=60, method="garch", seed=20)
        assert result.method == "garch"
        assert len(result.paths) == 50

    def test_garch_fallback_on_short_data(self):
        """GARCH on very short data should fallback to stationary internally."""
        short = np.random.default_rng(1).normal(0, 0.01, 15)
        mc = BlockBootstrapMC(short, initial_equity=1_000_000)
        mc.fit(method="garch")
        # Even if GARCH fit fails, simulate should still work (falls back to stationary)
        result = mc.simulate(n_paths=20, n_days=30, method="garch", seed=30)
        assert len(result.paths) == 20

    def test_garch_deterministic(self, trending_returns: np.ndarray):
        mc = BlockBootstrapMC(trending_returns, initial_equity=1_000_000)
        mc.fit(method="garch")
        r1 = mc.simulate(n_paths=30, n_days=50, method="garch", seed=42)
        mc2 = BlockBootstrapMC(trending_returns, initial_equity=1_000_000)
        mc2.fit(method="garch")
        r2 = mc2.simulate(n_paths=30, n_days=50, method="garch", seed=42)
        np.testing.assert_allclose(
            [p[-1] for p in r1.paths],
            [p[-1] for p in r2.paths],
            rtol=1e-10,
        )
