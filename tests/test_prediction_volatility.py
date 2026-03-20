"""Tests for volatility forecaster: GARCH training, forecast, validation."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from src.prediction.volatility import VolatilityForecaster


def _synthetic_returns(n: int = 500, seed: int = 42) -> np.ndarray:
    """Generate returns with GARCH-like volatility clustering."""
    rng = np.random.default_rng(seed)
    returns = np.zeros(n)
    sigma = np.zeros(n)
    sigma[0] = 0.01
    omega, alpha, beta = 0.00001, 0.1, 0.85
    for t in range(1, n):
        sigma[t] = np.sqrt(omega + alpha * returns[t - 1] ** 2 + beta * sigma[t - 1] ** 2)
        returns[t] = sigma[t] * rng.standard_normal()
    return returns


class TestVolatilityForecaster:
    def test_train_returns_params(self) -> None:
        returns = _synthetic_returns()
        vf = VolatilityForecaster(horizon=5)
        params = vf.train(returns)
        assert "omega" in params
        assert len(params) > 0

    def test_forecast_positive(self) -> None:
        returns = _synthetic_returns()
        vf = VolatilityForecaster(horizon=5)
        vf.train(returns)
        fcast = vf.forecast(current_price=20000.0)
        assert fcast.price_point_vol > 0
        assert fcast.annualized_vol > 0
        assert fcast.n_day_vol > 0
        assert fcast.is_valid

    def test_forecast_with_atr(self) -> None:
        returns = _synthetic_returns()
        vf = VolatilityForecaster(horizon=5)
        vf.train(returns)
        fcast_no_atr = vf.forecast(current_price=20000.0)
        fcast_with_atr = vf.forecast(current_price=20000.0, atr_daily=150.0)
        # With ATR blending, result should differ
        assert fcast_with_atr.price_point_vol != fcast_no_atr.price_point_vol

    def test_forecast_without_training_raises(self) -> None:
        vf = VolatilityForecaster()
        with pytest.raises(RuntimeError, match="not trained"):
            vf.forecast(current_price=20000.0)

    def test_save_load_roundtrip(self, tmp_path: Path) -> None:
        returns = _synthetic_returns()
        vf = VolatilityForecaster(horizon=5)
        vf.train(returns)
        fcast_before = vf.forecast(current_price=20000.0)

        path = tmp_path / "vol.pkl"
        vf.save(path)
        loaded = VolatilityForecaster.load(path)
        fcast_after = loaded.forecast(current_price=20000.0)

        assert abs(fcast_before.price_point_vol - fcast_after.price_point_vol) < 1e-6

    def test_different_horizons(self) -> None:
        returns = _synthetic_returns()
        vf5 = VolatilityForecaster(horizon=5)
        vf5.train(returns)
        vf20 = VolatilityForecaster(horizon=20)
        vf20.train(returns)
        f5 = vf5.forecast(current_price=20000.0)
        f20 = vf20.forecast(current_price=20000.0)
        # Longer horizon should have higher n_day_vol
        assert f20.n_day_vol > f5.n_day_vol
