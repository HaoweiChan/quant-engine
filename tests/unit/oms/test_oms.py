"""Tests for OrderManagementSystem: TWAP, VWAP, POV, passthrough, auto-selection."""
from __future__ import annotations

import pytest

from src.core.types import OMSConfig, Order
from src.oms.oms import OrderManagementSystem
from src.oms.volume_profile import VolumeProfile


def _make_order(lots: float = 10.0, side: str = "buy", metadata: dict | None = None) -> Order:
    return Order(
        order_type="market",
        side=side,
        symbol="TX",
        contract_type="large",
        lots=lots,
        price=None,
        stop_price=None,
        reason="entry",
        metadata=metadata or {},
    )


MARKET = {"adv": 50000.0, "volatility": 0.015, "volume": 10000.0}


class TestPassthrough:
    def test_small_order_passthrough(self) -> None:
        oms = OrderManagementSystem(config=OMSConfig(passthrough_threshold_pct=0.01))
        order = _make_order(lots=10)
        assert oms.is_passthrough(order, MARKET) is True
        result = oms.schedule([order], MARKET)
        assert len(result) == 1
        assert result[0].algorithm == "passthrough"
        assert len(result[0].child_orders) == 1

    def test_large_order_not_passthrough(self) -> None:
        oms = OrderManagementSystem(config=OMSConfig(passthrough_threshold_pct=0.01))
        order = _make_order(lots=1000)
        assert oms.is_passthrough(order, MARKET) is False

    def test_disabled_oms_always_passthrough(self) -> None:
        oms = OrderManagementSystem(config=OMSConfig(enabled=False))
        order = _make_order(lots=10000)
        result = oms.schedule([order], MARKET)
        assert result[0].algorithm == "passthrough"


class TestTWAP:
    def test_even_distribution(self) -> None:
        config = OMSConfig(passthrough_threshold_pct=0.0, default_algorithm="twap", twap_default_slices=10)
        oms = OrderManagementSystem(config=config)
        order = _make_order(lots=100)
        result = oms.schedule([order], MARKET)
        assert result[0].algorithm == "twap"
        assert len(result[0].child_orders) == 10
        for child in result[0].child_orders:
            assert child.order.lots == pytest.approx(10.0)
            assert child.slice_pct == pytest.approx(0.1)


class TestVWAP:
    def test_volume_proportional_distribution(self) -> None:
        profile = VolumeProfile(bucket_weights=[40, 60], n_buckets=2)
        config = OMSConfig(passthrough_threshold_pct=0.0, default_algorithm="vwap")
        oms = OrderManagementSystem(volume_profile=profile, config=config)
        order = _make_order(lots=100)
        result = oms.schedule([order], MARKET)
        assert result[0].algorithm == "vwap"
        assert len(result[0].child_orders) == 2
        assert result[0].child_orders[0].order.lots == pytest.approx(40.0)
        assert result[0].child_orders[1].order.lots == pytest.approx(60.0)

    def test_missing_profile_fallback_to_twap(self) -> None:
        config = OMSConfig(passthrough_threshold_pct=0.0, default_algorithm="vwap")
        oms = OrderManagementSystem(volume_profile=None, config=config)
        order = _make_order(lots=100)
        result = oms.schedule([order], MARKET)
        assert result[0].algorithm == "twap"


class TestPOV:
    def test_participation_rate_cap(self) -> None:
        config = OMSConfig(passthrough_threshold_pct=0.0, default_algorithm="pov", pov_participation_rate=0.05)
        oms = OrderManagementSystem(config=config)
        order = _make_order(lots=1000)
        market = {"adv": 50000.0, "volatility": 0.015, "volume": 10000.0}
        result = oms.schedule([order], market)
        assert result[0].algorithm == "pov"
        for child in result[0].child_orders:
            assert child.order.lots <= 0.05 * 10000.0


class TestAutoSelection:
    def test_urgent_passthrough(self) -> None:
        config = OMSConfig(passthrough_threshold_pct=0.0)
        oms = OrderManagementSystem(config=config)
        order = _make_order(lots=1000, metadata={"urgency": "immediate"})
        result = oms.schedule([order], MARKET)
        assert result[0].algorithm == "passthrough"

    def test_large_size_selects_vwap(self) -> None:
        profile = VolumeProfile(n_buckets=5)
        config = OMSConfig(passthrough_threshold_pct=0.0)
        oms = OrderManagementSystem(volume_profile=profile, config=config)
        order = _make_order(lots=5000)
        result = oms.schedule([order], MARKET)
        assert result[0].algorithm == "vwap"

    def test_high_vol_selects_pov(self) -> None:
        config = OMSConfig(passthrough_threshold_pct=0.0)
        oms = OrderManagementSystem(config=config)
        order = _make_order(lots=100)
        high_vol_market = {"adv": 50000.0, "volatility": 0.05, "volume": 10000.0}
        result = oms.schedule([order], high_vol_market)
        assert result[0].algorithm == "pov"


class TestVolumeProfile:
    def test_from_ohlcv(self) -> None:
        volumes = [100.0] * 100
        profile = VolumeProfile.from_ohlcv(volumes, n_buckets=10)
        assert len(profile.bucket_weights) == 10
        assert sum(profile.bucket_weights) == pytest.approx(1.0)

    def test_empty_volumes(self) -> None:
        profile = VolumeProfile.from_ohlcv([], n_buckets=5)
        assert len(profile.bucket_weights) == 5
        assert sum(profile.bucket_weights) == pytest.approx(1.0)
