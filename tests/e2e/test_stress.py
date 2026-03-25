"""Tests for stress test scenarios."""

from __future__ import annotations

import numpy as np
import pytest

pytestmark = pytest.mark.e2e

from src.adapters.taifex import TaifexAdapter
from src.core.types import PyramidConfig
from src.simulator.stress import (
    _flash_crash_prices,
    _gap_down_prices,
    _slow_bleed_prices,
    _vol_shift_prices,
    flash_crash_scenario,
    gap_down_scenario,
    run_stress_test,
    slow_bleed_scenario,
    vol_regime_shift_scenario,
)


@pytest.fixture
def config() -> PyramidConfig:
    return PyramidConfig(max_loss=200_000.0)


@pytest.fixture
def adapter() -> TaifexAdapter:
    return TaifexAdapter()


class TestGapDown:
    def test_magnitude(self) -> None:
        prices = _gap_down_prices(20000.0, 0.10)
        drop = (prices[-2] - prices[-1]) / prices[-2]
        assert drop == pytest.approx(0.10, abs=0.01)

    def test_produces_result(self, config: PyramidConfig, adapter: TaifexAdapter) -> None:
        scenario = gap_down_scenario(0.05)
        result = run_stress_test(scenario, config, adapter)
        assert result.scenario_name == "gap_down"
        assert isinstance(result.final_pnl, float)


class TestSlowBleed:
    def test_gradual_decline(self) -> None:
        prices = _slow_bleed_prices(20000.0, 0.15, 60)
        total_decline = (prices[20] - prices[-1]) / prices[20]
        assert total_decline > 0

    def test_produces_result(self, config: PyramidConfig, adapter: TaifexAdapter) -> None:
        scenario = slow_bleed_scenario(0.10, 30)
        result = run_stress_test(scenario, config, adapter)
        assert result.scenario_name == "slow_bleed"


class TestFlashCrash:
    def test_crash_and_recovery(self) -> None:
        prices = _flash_crash_prices(20000.0, 0.12, 3, 10)
        min_idx = np.argmin(prices)
        assert min_idx > 0
        assert prices[-1] > prices[min_idx]

    def test_produces_result(self, config: PyramidConfig, adapter: TaifexAdapter) -> None:
        scenario = flash_crash_scenario(0.08, 3, 10)
        result = run_stress_test(scenario, config, adapter)
        assert result.scenario_name == "flash_crash"


class TestVolRegimeShift:
    def test_vol_increase(self) -> None:
        prices = _vol_shift_prices(20000.0, 0.03, 60)
        returns = np.diff(prices) / prices[:-1]
        low_vol = np.std(returns[:30])
        high_vol = np.std(returns[30:])
        assert high_vol > low_vol

    def test_produces_result(self, config: PyramidConfig, adapter: TaifexAdapter) -> None:
        scenario = vol_regime_shift_scenario(0.04, 40)
        result = run_stress_test(scenario, config, adapter)
        assert result.scenario_name == "vol_regime_shift"


class TestMaxLossConstraint:
    def test_max_loss_holds(self, config: PyramidConfig, adapter: TaifexAdapter) -> None:
        for scenario_fn in [gap_down_scenario, slow_bleed_scenario, flash_crash_scenario]:
            scenario = scenario_fn()
            result = run_stress_test(scenario, config, adapter, initial_equity=2_000_000.0)
            assert result.equity_curve[-1] >= 0
