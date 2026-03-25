"""Tests for LiveExecutor with mocked shioaji API."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from unittest.mock import MagicMock

import pytest

from src.core.types import Order
from src.execution.live import LiveExecutor, LiveExecutorConfig


@dataclass
class _FakeTradeOrder:
    id: str = "abc123"


@dataclass
class _FakeTrade:
    order: _FakeTradeOrder


def _make_order(
    side: str = "buy", lots: float = 1.0, order_type: str = "market",
    stop_price: float | None = None, reason: str = "entry",
) -> Order:
    return Order(
        order_type=order_type, side=side, symbol="TX",
        contract_type="large", lots=lots, price=None,
        stop_price=stop_price, reason=reason,
    )


def _make_api(trade_id: str = "abc123") -> MagicMock:
    api = MagicMock()
    api.place_order.return_value = _FakeTrade(order=_FakeTradeOrder(id=trade_id))
    api.Contracts.Futures.TXF.TXF202504 = MagicMock()
    api.futopt_account = MagicMock()
    return api


class TestLiveExecutorFill:
    @pytest.mark.asyncio
    async def test_successful_fill(self) -> None:
        loop = asyncio.get_event_loop()
        api = _make_api()
        executor = LiveExecutor(api, loop, LiveExecutorConfig(fill_timeout=2.0))

        order = _make_order()

        async def _simulate_fill() -> None:
            await asyncio.sleep(0.05)
            executor._on_deal_event({
                "trade_id": "abc123", "price": 20001.0, "quantity": 1,
            })

        asyncio.ensure_future(_simulate_fill())
        results = await executor.execute([order])

        assert len(results) == 1
        assert results[0].status == "filled"
        assert results[0].fill_price == 20001.0
        assert results[0].fill_qty == 1.0
        api.place_order.assert_called_once()

    @pytest.mark.asyncio
    async def test_empty_orders(self) -> None:
        loop = asyncio.get_event_loop()
        api = _make_api()
        executor = LiveExecutor(api, loop)
        results = await executor.execute([])
        assert results == []
        api.place_order.assert_not_called()


class TestLiveExecutorTimeout:
    @pytest.mark.asyncio
    async def test_timeout_cancels_order(self) -> None:
        loop = asyncio.get_event_loop()
        api = _make_api()
        config = LiveExecutorConfig(fill_timeout=0.1, max_retries=1)
        executor = LiveExecutor(api, loop, config)

        order = _make_order()
        results = await executor.execute([order])

        assert len(results) == 1
        assert results[0].status == "cancelled"
        assert results[0].rejection_reason == "timeout"
        api.cancel_order.assert_called_once()


class TestLiveExecutorStopOrder:
    @pytest.mark.asyncio
    async def test_stop_order_uses_ioc(self) -> None:
        loop = asyncio.get_event_loop()
        api = _make_api()
        executor = LiveExecutor(api, loop, LiveExecutorConfig(fill_timeout=2.0))

        order = _make_order(order_type="stop", stop_price=19800.0, reason="stop_loss")

        async def _simulate_fill() -> None:
            await asyncio.sleep(0.05)
            executor._on_deal_event({
                "trade_id": "abc123", "price": 19800.0, "quantity": 1,
            })

        asyncio.ensure_future(_simulate_fill())
        results = await executor.execute([order])

        assert results[0].status == "filled"
        assert results[0].fill_price == 19800.0
        call_args = api.place_order.call_args
        sj_order = call_args[0][1] if len(call_args[0]) > 1 else call_args[1].get("order")
        assert sj_order is not None


class TestLiveExecutorOrderEvent:
    @pytest.mark.asyncio
    async def test_order_rejection_via_callback(self) -> None:
        loop = asyncio.get_event_loop()
        api = _make_api()
        config = LiveExecutorConfig(fill_timeout=2.0, max_retries=1)
        executor = LiveExecutor(api, loop, config)

        order = _make_order()

        async def _simulate_rejection() -> None:
            await asyncio.sleep(0.05)
            executor._on_order_event({
                "operation": {"op_type": "New", "op_code": "99", "op_msg": "insufficient_margin"},
                "order": {"id": "abc123"},
            })

        asyncio.ensure_future(_simulate_rejection())
        results = await executor.execute([order])

        assert len(results) == 1
        assert results[0].status == "rejected"


class TestLiveExecutorRollout:
    @pytest.mark.asyncio
    async def test_per_order_limit(self) -> None:
        loop = asyncio.get_event_loop()
        api = _make_api()

        @dataclass
        class FakeRollout:
            enabled: bool = True
            max_contracts_per_order: float = 2.0
            max_total_contracts: float = 10.0

        executor = LiveExecutor(api, loop, rollout_config=FakeRollout())

        order = _make_order(lots=5.0)
        results = await executor.execute([order])
        assert results[0].status == "rejected"
        assert results[0].rejection_reason == "exceeds_rollout_limit"
        api.place_order.assert_not_called()

    @pytest.mark.asyncio
    async def test_rollout_disabled_bypasses(self) -> None:
        loop = asyncio.get_event_loop()
        api = _make_api()

        @dataclass
        class FakeRollout:
            enabled: bool = False
            max_contracts_per_order: float = 1.0
            max_total_contracts: float = 1.0

        config = LiveExecutorConfig(fill_timeout=2.0)
        executor = LiveExecutor(api, loop, config, rollout_config=FakeRollout())

        order = _make_order(lots=5.0)

        async def _simulate_fill() -> None:
            await asyncio.sleep(0.05)
            executor._on_deal_event({
                "trade_id": "abc123", "price": 20000.0, "quantity": 5,
            })

        asyncio.ensure_future(_simulate_fill())
        results = await executor.execute([order])
        assert results[0].status == "filled"

    @pytest.mark.asyncio
    async def test_within_limit_passes(self) -> None:
        loop = asyncio.get_event_loop()
        api = _make_api()

        @dataclass
        class FakeRollout:
            enabled: bool = True
            max_contracts_per_order: float = 5.0
            max_total_contracts: float = 10.0

        config = LiveExecutorConfig(fill_timeout=2.0)
        executor = LiveExecutor(api, loop, config, rollout_config=FakeRollout())

        order = _make_order(lots=2.0)

        async def _simulate_fill() -> None:
            await asyncio.sleep(0.05)
            executor._on_deal_event({
                "trade_id": "abc123", "price": 20000.0, "quantity": 2,
            })

        asyncio.ensure_future(_simulate_fill())
        results = await executor.execute([order])
        assert results[0].status == "filled"


class TestLiveExecutorStats:
    @pytest.mark.asyncio
    async def test_fill_stats_empty(self) -> None:
        loop = asyncio.get_event_loop()
        api = _make_api()
        executor = LiveExecutor(api, loop)
        stats = executor.get_fill_stats()
        assert stats["count"] == 0.0
        assert stats["mean"] == 0.0
        assert stats["deviation_mean"] == 0.0

    @pytest.mark.asyncio
    async def test_fill_stats_with_deviation(self) -> None:
        loop = asyncio.get_event_loop()
        api = _make_api()
        config = LiveExecutorConfig(fill_timeout=2.0)
        executor = LiveExecutor(api, loop, config)

        order = _make_order()
        order.metadata["backtest_expected_price"] = 20000.0

        async def _simulate_fill() -> None:
            await asyncio.sleep(0.05)
            executor._on_deal_event({
                "trade_id": "abc123", "price": 20005.0, "quantity": 1,
            })

        asyncio.ensure_future(_simulate_fill())
        await executor.execute([order])

        stats = executor.get_fill_stats()
        assert stats["count"] == 1.0
        assert stats["deviation_mean"] == 5.0
        assert stats["double_slippage_count"] == 0.0
