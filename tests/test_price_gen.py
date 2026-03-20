"""Tests for price path generator statistical properties."""
from __future__ import annotations

import numpy as np
import pytest

from src.simulator.price_gen import generate_path, generate_paths
from src.simulator.types import PRESETS, PathConfig


class TestGBMBase:
    def test_path_length(self) -> None:
        config = PathConfig(n_bars=100, seed=42)
        path = generate_path(config)
        assert len(path) == 101

    def test_starts_at_configured_price(self) -> None:
        config = PathConfig(start_price=15000.0, seed=42)
        path = generate_path(config)
        assert path[0] == 15000.0

    def test_positive_drift_tends_up(self) -> None:
        config = PathConfig(drift=0.002, volatility=0.01, n_bars=500, seed=42)
        path = generate_path(config)
        assert path[-1] > path[0]

    def test_negative_drift_tends_down(self) -> None:
        config = PathConfig(drift=-0.002, volatility=0.01, n_bars=500, seed=42)
        path = generate_path(config)
        assert path[-1] < path[0]


class TestGARCH:
    def test_volatility_clustering(self) -> None:
        config = PathConfig(
            drift=0.0, volatility=0.02,
            garch_omega=0.00001, garch_alpha=0.1, garch_beta=0.85,
            n_bars=2000, seed=42,
        )
        path = generate_path(config)
        returns = np.diff(np.log(path))
        sq_returns = returns**2
        autocorr = np.corrcoef(sq_returns[:-1], sq_returns[1:])[0, 1]
        assert autocorr > 0


class TestStudentT:
    def test_fat_tails(self) -> None:
        config = PathConfig(
            drift=0.0, volatility=0.02, student_t_df=5.0,
            n_bars=5000, seed=42,
        )
        path = generate_path(config)
        returns = np.diff(np.log(path))
        from scipy.stats import kurtosis
        k = kurtosis(returns)
        assert k > 0


class TestPoissonJumps:
    def test_jumps_occur(self) -> None:
        config = PathConfig(
            drift=0.0, volatility=0.005,
            jump_intensity=0.05, jump_mean=-0.03, jump_std=0.01,
            n_bars=1000, seed=42,
        )
        path = generate_path(config)
        returns = np.diff(np.log(path))
        large_moves = np.sum(np.abs(returns) > 0.02)
        assert large_moves > 0


class TestOU:
    def test_mean_reversion(self) -> None:
        config = PathConfig(
            drift=0.0, volatility=0.005,
            ou_theta=0.5, ou_mu=0.0, ou_sigma=0.01,
            n_bars=2000, seed=42,
        )
        path = generate_path(config)
        log_prices = np.log(path)
        deviations = log_prices - np.mean(log_prices)
        autocorr = np.corrcoef(deviations[:-1], deviations[1:])[0, 1]
        # OU process: deviations from mean should be mean-reverting (positive but < 1)
        assert 0 < autocorr < 1.0


class TestPresets:
    @pytest.mark.parametrize("preset", list(PRESETS.keys()))
    def test_preset_generates_path(self, preset: str) -> None:
        path = generate_path(preset=preset)
        assert len(path) > 0
        assert path[0] > 0


class TestMultiplePaths:
    def test_shape(self) -> None:
        config = PathConfig(n_bars=50, seed=42)
        paths = generate_paths(10, config)
        assert paths.shape == (10, 51)

    def test_different_paths(self) -> None:
        config = PathConfig(n_bars=50, seed=42)
        paths = generate_paths(5, config)
        assert not np.allclose(paths[0], paths[1])
