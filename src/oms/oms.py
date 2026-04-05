"""Order Management System: TWAP, VWAP, POV execution scheduling."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

_TAIPEI_TZ = timezone(timedelta(hours=8))

from src.core.types import ChildOrder, OMSConfig, Order, SlicedOrder
from src.oms.volume_profile import VolumeProfile
from src.simulator.fill_model import MarketImpactFillModel


class OrderManagementSystem:
    """Converts orders into optimally-sliced child orders to minimize market impact."""

    def __init__(
        self,
        impact_model: MarketImpactFillModel | None = None,
        volume_profile: VolumeProfile | None = None,
        config: OMSConfig | None = None,
    ) -> None:
        self._impact = impact_model or MarketImpactFillModel()
        self._profile = volume_profile
        self._config = config or OMSConfig()

    def schedule(self, orders: list[Order], market_data: dict[str, float]) -> list[SlicedOrder]:
        if not self._config.enabled:
            return [self._passthrough(o) for o in orders]
        return [self._schedule_one(o, market_data) for o in orders]

    def is_passthrough(self, order: Order, market_data: dict[str, float]) -> bool:
        if not self._config.enabled:
            return True
        adv = market_data.get("adv", 0.0)
        if adv <= 0:
            return True
        return order.lots < self._config.passthrough_threshold_pct * adv

    def _schedule_one(self, order: Order, market_data: dict[str, float]) -> SlicedOrder:
        if self.is_passthrough(order, market_data):
            return self._passthrough(order)
        algo = self._select_algorithm(order, market_data)
        if algo == "passthrough":
            return self._passthrough(order)
        if algo == "twap":
            return self._twap(order, market_data)
        if algo == "vwap":
            return self._vwap(order, market_data)
        if algo == "pov":
            return self._pov(order, market_data)
        return self._twap(order, market_data)

    def _select_algorithm(self, order: Order, market_data: dict[str, float]) -> str:
        override = order.metadata.get("oms_algorithm")
        if override:
            return str(override)
        if self._config.default_algorithm != "auto":
            return self._config.default_algorithm
        urgency = order.metadata.get("urgency", "normal")
        if urgency == "immediate":
            return "passthrough"
        adv = market_data.get("adv", 0.0)
        if adv > 0 and order.lots > 0.05 * adv:
            return "vwap"
        volatility = market_data.get("volatility", 0.0)
        if volatility > 0.03:
            return "pov"
        return "twap"

    def _twap(self, order: Order, market_data: dict[str, float]) -> SlicedOrder:
        n = self._config.twap_default_slices
        lot_per_slice = order.lots / n
        now = datetime.now(_TAIPEI_TZ)
        window = timedelta(minutes=self._config.max_execution_window_minutes)
        interval = window / n
        children: list[ChildOrder] = []
        schedule: list[datetime] = []
        for i in range(n):
            t = now + interval * i
            child_order = self._copy_order(order, lot_per_slice)
            children.append(ChildOrder(order=child_order, scheduled_time=t, slice_pct=1.0 / n))
            schedule.append(t)
        sigma = market_data.get("volatility", 0.01)
        adv = market_data.get("adv", 50000.0)
        impact = self._impact.estimate_impact(order.lots, sigma, adv)
        return SlicedOrder(
            parent_order=order, child_orders=children,
            algorithm="twap", estimated_impact=impact, schedule=schedule,
        )

    def _vwap(self, order: Order, market_data: dict[str, float]) -> SlicedOrder:
        profile = self._profile
        if profile is None or not profile.bucket_weights:
            return self._twap(order, market_data)
        now = datetime.now(_TAIPEI_TZ)
        window = timedelta(minutes=self._config.max_execution_window_minutes)
        n = len(profile.bucket_weights)
        interval = window / n
        children: list[ChildOrder] = []
        schedule: list[datetime] = []
        for i, weight in enumerate(profile.bucket_weights):
            t = now + interval * i
            child_lots = order.lots * weight
            if child_lots <= 0:
                continue
            child_order = self._copy_order(order, child_lots)
            children.append(ChildOrder(order=child_order, scheduled_time=t, slice_pct=weight))
            schedule.append(t)
        sigma = market_data.get("volatility", 0.01)
        adv = market_data.get("adv", 50000.0)
        impact = self._impact.estimate_impact(order.lots, sigma, adv)
        return SlicedOrder(
            parent_order=order, child_orders=children,
            algorithm="vwap", estimated_impact=impact, schedule=schedule,
        )

    def _pov(self, order: Order, market_data: dict[str, float]) -> SlicedOrder:
        rate = self._config.pov_participation_rate
        bar_volume = market_data.get("volume", 0.0)
        max_per_slice = rate * bar_volume if bar_volume > 0 else order.lots
        remaining = order.lots
        now = datetime.now(_TAIPEI_TZ)
        interval = timedelta(minutes=5)
        children: list[ChildOrder] = []
        schedule: list[datetime] = []
        i = 0
        while remaining > 0:
            child_lots = min(remaining, max_per_slice)
            t = now + interval * i
            child_order = self._copy_order(order, child_lots)
            pct = child_lots / order.lots
            children.append(ChildOrder(order=child_order, scheduled_time=t, slice_pct=pct))
            schedule.append(t)
            remaining -= child_lots
            i += 1
            if i > 1000:
                break
        sigma = market_data.get("volatility", 0.01)
        adv = market_data.get("adv", 50000.0)
        impact = self._impact.estimate_impact(order.lots, sigma, adv)
        return SlicedOrder(
            parent_order=order, child_orders=children,
            algorithm="pov", estimated_impact=impact, schedule=schedule,
        )

    def _passthrough(self, order: Order) -> SlicedOrder:
        now = datetime.now(_TAIPEI_TZ)
        child = ChildOrder(order=order, scheduled_time=now, slice_pct=1.0)
        return SlicedOrder(
            parent_order=order, child_orders=[child],
            algorithm="passthrough", estimated_impact=0.0, schedule=[now],
        )

    @staticmethod
    def _copy_order(order: Order, lots: float) -> Order:
        return Order(
            order_type=order.order_type,
            side=order.side,
            symbol=order.symbol,
            contract_type=order.contract_type,
            lots=lots,
            price=order.price,
            stop_price=order.stop_price,
            reason=order.reason,
            metadata=dict(order.metadata),
            parent_position_id=order.parent_position_id,
            order_class=order.order_class,
        )
