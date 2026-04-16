"""Tests for DisasterStopMonitor: register/deregister, tick breach, idempotent fire guard, symbol filtering."""

from __future__ import annotations

import pytest

from src.core.types import Order
from src.execution.disaster_stop_monitor import DisasterStopEntry, DisasterStopMonitor


class TestDisasterStopMonitor:
    @pytest.mark.asyncio
    async def test_register_increments_active_count(self) -> None:
        monitor = DisasterStopMonitor(lambda x: None)
        entry = DisasterStopEntry(
            position_id="pos-1",
            direction="long",
            disaster_level=19000.0,
            lots=2.0,
            contract_type="large",
            symbol="TXF",
        )
        monitor.register(entry)
        assert monitor.active_count() == 1

    @pytest.mark.asyncio
    async def test_deregister_decrements_active_count(self) -> None:
        monitor = DisasterStopMonitor(lambda x: None)
        entry = DisasterStopEntry(
            position_id="pos-1",
            direction="long",
            disaster_level=19000.0,
            lots=2.0,
            contract_type="large",
            symbol="TXF",
        )
        monitor.register(entry)
        monitor.deregister("pos-1")
        assert monitor.active_count() == 0

    @pytest.mark.asyncio
    async def test_deregister_unknown_id_is_noop(self) -> None:
        monitor = DisasterStopMonitor(lambda x: None)
        monitor.deregister("unknown-id")
        assert monitor.active_count() == 0

    @pytest.mark.asyncio
    async def test_long_breach_triggers_fire(self) -> None:
        orders_fired: list[list[Order]] = []

        async def capture_orders(orders: list[Order]) -> None:
            orders_fired.append(orders)

        monitor = DisasterStopMonitor(capture_orders)
        entry = DisasterStopEntry(
            position_id="pos-1",
            direction="long",
            disaster_level=19000.0,
            lots=2.0,
            contract_type="large",
            symbol="TXF",
        )
        monitor.register(entry)
        await monitor.on_tick(18900.0, "TXF")
        assert len(orders_fired) == 1
        assert orders_fired[0][0].order_class == "disaster_stop"
        assert orders_fired[0][0].parent_position_id == "pos-1"
        assert orders_fired[0][0].reason == "disaster_stop"

    @pytest.mark.asyncio
    async def test_short_breach_triggers_fire(self) -> None:
        orders_fired: list[list[Order]] = []

        async def capture_orders(orders: list[Order]) -> None:
            orders_fired.append(orders)

        monitor = DisasterStopMonitor(capture_orders)
        entry = DisasterStopEntry(
            position_id="pos-1",
            direction="short",
            disaster_level=19000.0,
            lots=2.0,
            contract_type="large",
            symbol="TXF",
        )
        monitor.register(entry)
        await monitor.on_tick(19100.0, "TXF")
        assert len(orders_fired) == 1
        assert orders_fired[0][0].order_class == "disaster_stop"

    @pytest.mark.asyncio
    async def test_price_within_range_does_not_fire(self) -> None:
        orders_fired: list[list[Order]] = []

        async def capture_orders(orders: list[Order]) -> None:
            orders_fired.append(orders)

        monitor = DisasterStopMonitor(capture_orders)
        entry = DisasterStopEntry(
            position_id="pos-1",
            direction="long",
            disaster_level=19000.0,
            lots=2.0,
            contract_type="large",
            symbol="TXF",
        )
        monitor.register(entry)
        await monitor.on_tick(19500.0, "TXF")
        assert len(orders_fired) == 0

    @pytest.mark.asyncio
    async def test_idempotent_fire_guard(self) -> None:
        orders_fired: list[list[Order]] = []

        async def capture_orders(orders: list[Order]) -> None:
            orders_fired.append(orders)

        monitor = DisasterStopMonitor(capture_orders)
        entry = DisasterStopEntry(
            position_id="pos-1",
            direction="long",
            disaster_level=19000.0,
            lots=2.0,
            contract_type="large",
            symbol="TXF",
        )
        monitor.register(entry)
        await monitor.on_tick(18900.0, "TXF")
        await monitor.on_tick(18800.0, "TXF")
        assert len(orders_fired) == 1

    @pytest.mark.asyncio
    async def test_symbol_filtering(self) -> None:
        orders_fired: list[list[Order]] = []

        async def capture_orders(orders: list[Order]) -> None:
            orders_fired.append(orders)

        monitor = DisasterStopMonitor(capture_orders)
        entry = DisasterStopEntry(
            position_id="pos-1",
            direction="long",
            disaster_level=19000.0,
            lots=2.0,
            contract_type="large",
            symbol="TXF",
        )
        monitor.register(entry)
        await monitor.on_tick(18900.0, "不同的符号")
        assert len(orders_fired) == 0
