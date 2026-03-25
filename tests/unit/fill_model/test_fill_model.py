"""Tests for MarketImpactFillModel and ImpactCalibrator."""
from datetime import datetime

import pytest

from src.core.types import ImpactParams, Order
from src.simulator.fill_model import ImpactCalibrator, MarketImpactFillModel


def _make_order(lots: float = 10.0, side: str = "buy") -> Order:
    return Order(
        order_type="market",
        side=side,
        symbol="TX",
        contract_type="large",
        lots=lots,
        price=None,
        stop_price=None,
        reason="entry",
    )


def _make_bar(
    close: float = 20000.0,
    volume: float = 50000.0,
    daily_atr: float = 300.0,
    spread: float | None = None,
    open_price: float | None = None,
) -> dict[str, float]:
    bar: dict[str, float] = {"close": close, "volume": volume, "daily_atr": daily_atr}
    if spread is not None:
        bar["spread"] = spread
    bar["open"] = open_price if open_price is not None else close
    return bar


TS = datetime(2026, 1, 15, 9, 0, 0)


class TestImpactScaling:
    def test_impact_scales_with_order_size(self) -> None:
        model = MarketImpactFillModel(ImpactParams(seed=42))
        small = model.estimate_impact(10, 0.015, 50000)
        large = model.estimate_impact(100, 0.015, 50000)
        assert large > small
        assert large / small == pytest.approx(10**0.5, rel=0.01)

    def test_impact_scales_with_volatility(self) -> None:
        model = MarketImpactFillModel(ImpactParams(seed=42))
        low_vol = model.estimate_impact(10, 0.01, 50000)
        high_vol = model.estimate_impact(10, 0.02, 50000)
        assert high_vol == pytest.approx(2 * low_vol, rel=0.01)

    def test_zero_size_zero_impact(self) -> None:
        model = MarketImpactFillModel(ImpactParams(seed=42))
        assert model.estimate_impact(0, 0.015, 50000) == 0.0

    def test_zero_adv_zero_impact(self) -> None:
        model = MarketImpactFillModel(ImpactParams(seed=42))
        assert model.estimate_impact(10, 0.015, 0) == 0.0


class TestSpreadCost:
    def test_buy_fill_higher_than_mid(self) -> None:
        model = MarketImpactFillModel(ImpactParams(seed=42, k=0))
        bar = _make_bar(spread=2.0)
        fill = model.simulate(_make_order(side="buy"), bar, TS)
        assert fill.fill_price > bar["close"]
        assert fill.spread_cost == 1.0

    def test_sell_fill_lower_than_mid(self) -> None:
        model = MarketImpactFillModel(ImpactParams(seed=42, k=0))
        bar = _make_bar(spread=2.0)
        fill = model.simulate(_make_order(side="sell"), bar, TS)
        assert fill.fill_price < bar["close"]

    def test_spread_fallback_from_bps(self) -> None:
        model = MarketImpactFillModel(ImpactParams(seed=42, k=0, spread_bps=1.0))
        bar = _make_bar()
        fill = model.simulate(_make_order(side="buy"), bar, TS)
        expected_half_spread = 1.0 * 20000.0 / 10000.0
        assert fill.spread_cost == pytest.approx(expected_half_spread, rel=0.01)


class TestLatencyDeterminism:
    def test_same_seed_same_fills(self) -> None:
        params = ImpactParams(seed=123)
        m1 = MarketImpactFillModel(params)
        m2 = MarketImpactFillModel(ImpactParams(seed=123))
        bar = _make_bar()
        order = _make_order()
        f1 = m1.simulate(order, bar, TS)
        f2 = m2.simulate(order, bar, TS)
        assert f1.fill_price == f2.fill_price
        assert f1.latency_ms == f2.latency_ms

    def test_different_seed_different_fills(self) -> None:
        m1 = MarketImpactFillModel(ImpactParams(seed=1))
        m2 = MarketImpactFillModel(ImpactParams(seed=2))
        bar = _make_bar()
        order = _make_order()
        f1 = m1.simulate(order, bar, TS)
        f2 = m2.simulate(order, bar, TS)
        assert f1.latency_ms != f2.latency_ms


class TestPartialFills:
    def test_zero_volume_rejected(self) -> None:
        model = MarketImpactFillModel(ImpactParams(seed=42))
        bar = _make_bar(volume=0)
        fill = model.simulate(_make_order(), bar, TS)
        assert fill.fill_qty == 0.0
        assert fill.remaining_qty == 10.0
        assert fill.reason == "no_liquidity"
        assert fill.is_partial is True

    def test_oversized_order_partial(self) -> None:
        model = MarketImpactFillModel(ImpactParams(seed=42, max_adv_participation=0.10))
        bar = _make_bar(volume=50.0)
        order = _make_order(lots=100)
        fill = model.simulate(order, bar, TS)
        assert fill.fill_qty == pytest.approx(5.0)
        assert fill.remaining_qty == pytest.approx(95.0)
        assert fill.is_partial is True

    def test_normal_order_full_fill(self) -> None:
        model = MarketImpactFillModel(ImpactParams(seed=42))
        bar = _make_bar(volume=50000)
        fill = model.simulate(_make_order(lots=10), bar, TS)
        assert fill.fill_qty == 10.0
        assert fill.remaining_qty == 0.0
        assert fill.is_partial is False


class TestImpactCalibrator:
    def test_k_converges_when_accurate(self) -> None:
        cal = ImpactCalibrator(initial_k=1.0, alpha=0.1, min_samples=5)
        for _ in range(100):
            cal.record(1.0, 1.0)
        assert cal.k == pytest.approx(1.0, rel=0.01)

    def test_k_adjusts_when_underpredicting(self) -> None:
        cal = ImpactCalibrator(initial_k=1.0, alpha=0.1, min_samples=5)
        for _ in range(200):
            cal.record(1.0, 2.0)
        assert cal.k > 1.5

    def test_no_update_below_min_samples(self) -> None:
        cal = ImpactCalibrator(initial_k=1.0, alpha=0.1, min_samples=50)
        for _ in range(49):
            cal.record(1.0, 5.0)
        assert cal.k == 1.0

    def test_stats(self) -> None:
        cal = ImpactCalibrator()
        cal.record(1.0, 1.5)
        stats = cal.get_stats()
        assert stats["samples"] == 1.0
        assert stats["mae"] == 0.5
