"""Tests for Execution Engine: paper fills, slippage, stats, validation."""
from __future__ import annotations

import pytest

from src.core.types import Order
from src.execution.paper import PaperExecutor


def _make_order(
    side: str = "buy",
    lots: float = 2.0,
    reason: str = "entry",
) -> Order:
    return Order(
        order_type="market", side=side, symbol="TX",
        contract_type="large", lots=lots, price=None,
        stop_price=None, reason=reason,
    )


class TestPaperExecutor:
    @pytest.mark.asyncio
    async def test_buy_fill_with_slippage(self) -> None:
        executor = PaperExecutor(slippage_points=2.0, current_price=20000.0)
        results = await executor.execute([_make_order("buy")])
        assert len(results) == 1
        assert results[0].status == "filled"
        assert results[0].fill_price == 20002.0
        assert results[0].slippage == 2.0

    @pytest.mark.asyncio
    async def test_sell_fill_with_slippage(self) -> None:
        executor = PaperExecutor(slippage_points=2.0, current_price=20000.0)
        results = await executor.execute([_make_order("sell")])
        assert results[0].fill_price == 19998.0
        assert results[0].slippage == -2.0

    @pytest.mark.asyncio
    async def test_empty_orders(self) -> None:
        executor = PaperExecutor(current_price=20000.0)
        results = await executor.execute([])
        assert results == []

    @pytest.mark.asyncio
    async def test_margin_rejection(self) -> None:
        executor = PaperExecutor(
            current_price=20000.0, available_margin=100_000.0,
            margin_per_lot=184_000.0,
        )
        results = await executor.execute([_make_order("buy", lots=2.0)])
        assert results[0].status == "rejected"
        assert results[0].rejection_reason == "insufficient_margin"
        assert results[0].fill_qty == 0.0

    @pytest.mark.asyncio
    async def test_fill_stats(self) -> None:
        executor = PaperExecutor(slippage_points=1.5, current_price=20000.0)
        await executor.execute([_make_order("buy")])
        await executor.execute([_make_order("sell")])
        await executor.execute([_make_order("buy")])
        stats = executor.get_fill_stats()
        assert stats["count"] == 3.0
        assert stats["mean"] == 1.5
        assert stats["max"] == 1.5

    @pytest.mark.asyncio
    async def test_fill_history(self) -> None:
        executor = PaperExecutor(current_price=20000.0)
        await executor.execute([_make_order("buy")])
        await executor.execute([_make_order("sell")])
        assert len(executor.fill_history) == 2

    @pytest.mark.asyncio
    async def test_set_market_state(self) -> None:
        executor = PaperExecutor(current_price=20000.0)
        executor.set_market_state(21000.0)
        results = await executor.execute([_make_order("buy")])
        assert results[0].expected_price == 21000.0
