"""E2E readiness checks for shadow and micro-live execution modes."""

from __future__ import annotations

import asyncio
from time import monotonic_ns
from types import SimpleNamespace
from typing import Any

import pytest

from src.core.types import Order
from src.execution.live import LiveExecutor
from src.execution.live import LiveExecutorConfig


class _E2EFakeAPI:
    def __init__(self, loop: asyncio.AbstractEventLoop, fill_price: float) -> None:
        self._loop = loop
        self._fill_price = fill_price
        self._callback: Any = None
        self.futopt_account = object()
        self.place_count = 0
        self.Contracts = SimpleNamespace(
            Futures=SimpleNamespace(TXF=SimpleNamespace(TXF202504=object())),
        )

    def set_order_callback(self, callback: Any) -> None:
        self._callback = callback

    def Order(self, **kwargs: Any) -> Any:
        return SimpleNamespace(**kwargs)

    def place_order(self, _contract: Any, order: Any) -> Any:
        self.place_count += 1
        order_id = f"e2e-order-{self.place_count}"
        trade = SimpleNamespace(order=SimpleNamespace(id=order_id))
        self._loop.call_soon(
            lambda: self._callback(
                "Deal",
                {"trade_id": order_id, "price": self._fill_price, "quantity": float(order.quantity)},
            )
        )
        return trade

    def cancel_order(self, _trade: Any) -> None:
        return None


def _order(price: float = 100.0) -> Order:
    now = monotonic_ns()
    return Order(
        order_type="limit",
        side="buy",
        symbol="TX",
        contract_type="large",
        lots=1.0,
        price=price,
        stop_price=None,
        reason="entry",
        metadata={
            "volatility": 0.5,
            "quote_ingest_ns": now - 100_000_000,
            "signal_emit_ns": now - 20_000_000,
        },
    )


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_shadow_and_micro_live_readiness_path() -> None:
    loop = asyncio.get_running_loop()

    shadow_api = _E2EFakeAPI(loop, fill_price=100.0)
    shadow_executor = LiveExecutor(
        api=shadow_api,
        loop=loop,
        config=LiveExecutorConfig(run_mode="shadow"),
    )
    await shadow_executor.execute([_order() for _ in range(10)])
    assert shadow_api.place_count == 0

    micro_api = _E2EFakeAPI(loop, fill_price=100.01)
    micro_executor = LiveExecutor(
        api=micro_api,
        loop=loop,
        config=LiveExecutorConfig(run_mode="micro_live"),
    )
    await micro_executor.execute([_order() for _ in range(30)])
    stats = micro_executor.get_fill_stats()
    assert stats["tick_to_order_p99_ms"] <= 200.0
    assert "pct_over_2bps" in stats
