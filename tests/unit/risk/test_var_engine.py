"""Tests for the parametric and historical VaR engine."""
from __future__ import annotations

from datetime import datetime

import pytest

from src.core.types import Order, Position, StressScenario
from src.risk.var_engine import SQRT_10, Z_99, VaREngine


def _pos(
    symbol: str = "TX",
    lots: float = 1.0,
    price: float = 20000.0,
    direction: str = "long",
) -> Position:
    return Position(
        entry_price=price,
        lots=lots,
        contract_type=symbol,
        stop_level=price - 100,
        pyramid_level=1,
        entry_timestamp=datetime(2024, 1, 1),
        direction=direction,
    )


def _order(symbol: str = "TX", lots: float = 1.0, side: str = "buy") -> Order:
    return Order(
        symbol=symbol,
        lots=lots,
        side=side,
        order_type="market",
        contract_type=symbol,
        price=None,
        stop_price=None,
        reason="test",
    )


def _daily_returns(n: int = 60, vol: float = 0.01) -> list[float]:
    """Synthetic returns with known volatility pattern."""
    import random
    random.seed(42)
    return [random.gauss(0, vol) for _ in range(n)]


class TestParametricVaR:
    """Tasks 2.1 / 2.2: single-instrument and 10-day scaling."""

    def test_single_instrument_var(self):
        """VaR for single instrument = pos_value * daily_vol * z_score."""
        engine = VaREngine(lookback_days=252)
        returns = _daily_returns(60, vol=0.015)
        pos = _pos(lots=2.0, price=20000.0)
        result = engine.compute([pos], {"TX": returns}, {"TX": 20000.0})
        pos_value = 2.0 * 20000.0
        realized_vol = engine._std_of_returns(returns[-252:])
        expected_99 = pos_value * realized_vol * Z_99
        assert result.var_99_1d == pytest.approx(expected_99, rel=0.01)

    def test_ten_day_scaling(self):
        """10-day VaR = 1-day VaR * sqrt(10)."""
        engine = VaREngine()
        returns = _daily_returns(60)
        pos = _pos()
        result = engine.compute([pos], {"TX": returns}, {"TX": 20000.0})
        assert result.var_99_10d == pytest.approx(
            result.var_99_1d * SQRT_10, rel=0.001,
        )
        assert result.var_95_10d == pytest.approx(
            result.var_95_1d * SQRT_10, rel=0.001,
        )

    def test_var_95_less_than_99(self):
        engine = VaREngine()
        returns = _daily_returns(60)
        result = engine.compute([_pos()], {"TX": returns}, {"TX": 20000.0})
        assert result.var_95_1d < result.var_99_1d

    def test_empty_portfolio(self):
        engine = VaREngine()
        result = engine.compute([], {})
        assert result.var_99_1d == 0.0
        assert result.var_95_1d == 0.0

    def test_position_var_breakdown(self):
        engine = VaREngine()
        returns = _daily_returns(60)
        result = engine.compute([_pos()], {"TX": returns}, {"TX": 20000.0})
        assert "TX" in result.position_var
        assert result.position_var["TX"] > 0

    def test_expected_shortfall_exceeds_var(self):
        engine = VaREngine()
        returns = _daily_returns(60)
        result = engine.compute([_pos()], {"TX": returns}, {"TX": 20000.0})
        assert result.expected_shortfall_99 > result.var_99_1d

    def test_multi_instrument(self):
        engine = VaREngine()
        r_tx = _daily_returns(60, vol=0.015)
        r_mx = _daily_returns(60, vol=0.012)
        positions = [_pos("TX", 1, 20000), _pos("MX", 2, 10000)]
        returns = {"TX": r_tx, "MX": r_mx}
        prices = {"TX": 20000, "MX": 10000}
        result = engine.compute(positions, returns, prices)
        # Portfolio VaR should be less than sum of individual VaRs (diversification)
        individual_sum = result.position_var.get("TX", 0) + result.position_var.get("MX", 0)
        assert result.var_99_1d <= individual_sum * 1.01  # allow small numerical tolerance

    def test_short_position(self):
        engine = VaREngine()
        returns = _daily_returns(60)
        long_result = engine.compute(
            [_pos(direction="long")], {"TX": returns}, {"TX": 20000.0},
        )
        short_result = engine.compute(
            [_pos(direction="short")], {"TX": returns}, {"TX": 20000.0},
        )
        assert long_result.var_99_1d == pytest.approx(short_result.var_99_1d, rel=0.01)


class TestFallback:
    """Task 2.4: conservative fallback when <30 returns."""

    def test_fallback_triggers_on_short_history(self):
        engine = VaREngine()
        short_returns = _daily_returns(10)
        result = engine.compute([_pos()], {"TX": short_returns}, {"TX": 20000.0})
        assert result.is_fallback is True

    def test_fallback_uses_2x_atr(self):
        engine = VaREngine()
        short_returns = [0.01, -0.01, 0.005, -0.005]
        vol = engine._atr_fallback_vol(short_returns)
        avg_abs = sum(abs(r) for r in short_returns) / len(short_returns)
        assert vol == pytest.approx(2.0 * avg_abs)

    def test_no_fallback_with_enough_history(self):
        engine = VaREngine()
        returns = _daily_returns(60)
        result = engine.compute([_pos()], {"TX": returns}, {"TX": 20000.0})
        assert result.is_fallback is False

    def test_empty_returns_fallback(self):
        engine = VaREngine()
        vol = engine._atr_fallback_vol([])
        assert vol == 0.02  # default


class TestIncrementalVaR:
    """Task 2.3: marginal VaR without full matrix recomputation."""

    def test_incremental_positive(self):
        engine = VaREngine()
        returns = _daily_returns(60)
        pos = _pos()
        base_var = engine.compute([pos], {"TX": returns}, {"TX": 20000.0})
        order = _order(lots=1.0)
        incr = engine.compute_incremental(
            order, base_var, [pos], {"TX": returns}, {"TX": 20000.0},
        )
        assert incr > 0

    def test_incremental_from_empty(self):
        engine = VaREngine()
        returns = _daily_returns(60)
        empty_var = engine._empty_result()
        order = _order(lots=1.0)
        incr = engine.compute_incremental(
            order, empty_var, [], {"TX": returns}, {"TX": 20000.0},
        )
        assert incr > 0


class TestHistoricalVaR:
    """Task 2.5: HVaR from actual return distribution."""

    def test_historical_var_positive(self):
        engine = VaREngine()
        returns = _daily_returns(100)
        pos = _pos()
        hvar = engine.compute_historical([pos], {"TX": returns}, {"TX": 20000.0})
        assert hvar > 0

    def test_historical_var_empty(self):
        engine = VaREngine()
        assert engine.compute_historical([], {}) == 0.0


class TestDivergenceAlert:
    """Task 2.6: alert when HVaR vs parametric diverge >30%."""

    def test_no_divergence(self):
        engine = VaREngine()
        diverged, ratio = engine.check_divergence(100.0, 110.0)
        assert diverged is False
        assert ratio < 0.30

    def test_divergence_detected(self):
        engine = VaREngine()
        diverged, ratio = engine.check_divergence(100.0, 200.0)
        assert diverged is True
        assert ratio > 0.30

    def test_zero_parametric(self):
        engine = VaREngine()
        diverged, ratio = engine.check_divergence(0.0, 50.0)
        assert diverged is False


class TestStressScenarios:
    """Task 3.4: margin doubling, vol spike, correlation breakdown."""

    def test_margin_doubling(self):
        engine = VaREngine()
        returns = _daily_returns(60)
        scenario = StressScenario(name="margin_double", margin_multiplier=2.0)
        results = engine.run_stress(
            [_pos()], {"TX": returns}, [scenario],
            equity=1_000_000, margin_used=600_000, prices={"TX": 20000.0},
        )
        assert len(results) == 1
        assert results[0].margin_call is True
        assert results[0].shortfall > 0

    def test_volatility_spike(self):
        engine = VaREngine()
        returns = _daily_returns(60)
        normal_var = engine.compute([_pos()], {"TX": returns}, {"TX": 20000.0})
        scenario = StressScenario(name="vol_3x", volatility_multiplier=3.0)
        results = engine.run_stress(
            [_pos()], {"TX": returns}, [scenario],
            equity=1_000_000, margin_used=200_000, prices={"TX": 20000.0},
        )
        assert results[0].stressed_var > normal_var.var_99_1d

    def test_no_margin_call_when_healthy(self):
        engine = VaREngine()
        returns = _daily_returns(60)
        scenario = StressScenario(name="baseline")
        results = engine.run_stress(
            [_pos()], {"TX": returns}, [scenario],
            equity=1_000_000, margin_used=100_000, prices={"TX": 20000.0},
        )
        assert results[0].margin_call is False
        assert results[0].shortfall == 0.0
