"""Integration tests for adaptive live executor routing and telemetry."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from time import monotonic_ns
from types import SimpleNamespace
from typing import Any

import pytest

from src.core.types import Order
from src.execution.live import LiveExecutor
from src.execution.live import LiveExecutorConfig


@dataclass
class FakeOutcome:
    kind: str
    price: float = 20000.0
    quantity: float = 1.0
    delay: float = 0.0


class FakeAPI:
    def __init__(self, loop: asyncio.AbstractEventLoop, outcomes: list[FakeOutcome]) -> None:
        self._loop = loop
        self._outcomes = outcomes
        self._callback: Any = None
        self.futopt_account = object()
        self.place_calls: list[dict[str, Any]] = []
        self.cancel_calls: list[str] = []
        self.Contracts = SimpleNamespace(
            Futures=SimpleNamespace(TXF=SimpleNamespace(TXF202504=object())),
        )

    def set_order_callback(self, callback: Any) -> None:
        self._callback = callback

    def Order(self, **kwargs: Any) -> Any:
        return SimpleNamespace(**kwargs)

    def place_order(self, contract: Any, order: Any) -> Any:
        order_id = f"order-{len(self.place_calls) + 1}"
        self.place_calls.append({"id": order_id, "contract": contract, "order": order})
        trade = SimpleNamespace(order=SimpleNamespace(id=order_id))
        outcome = self._outcomes.pop(0) if self._outcomes else FakeOutcome("fill")
        if outcome.kind == "fill":
            self._loop.call_later(
                outcome.delay,
                lambda: self._callback(
                    "Deal",
                    {
                        "trade_id": order_id,
                        "price": outcome.price,
                        "quantity": outcome.quantity,
                    },
                ),
            )
        if outcome.kind == "reject":
            self._loop.call_later(
                outcome.delay,
                lambda: self._callback(
                    "Order",
                    {
                        "order": {"id": order_id},
                        "operation": {"op_code": "9999", "op_msg": "reject"},
                    },
                ),
            )
        return trade

    def cancel_order(self, trade: Any) -> None:
        self.cancel_calls.append(trade.order.id)


def _make_order(
    lots: float = 1.0,
    price: float = 20000.0,
    order_type: str = "limit",
    volatility: float = 0.5,
) -> Order:
    return Order(
        order_type=order_type,
        side="buy",
        symbol="TX",
        contract_type="large",
        lots=lots,
        price=price if order_type != "market" else None,
        stop_price=None,
        reason="entry",
        metadata={"volatility": volatility},
    )


@pytest.mark.asyncio
async def test_volatility_policy_selection() -> None:
    loop = asyncio.get_running_loop()
    api = FakeAPI(loop, outcomes=[FakeOutcome("fill")])
    executor = LiveExecutor(api=api, loop=loop, config=LiveExecutorConfig())
    assert executor._classify_volatility(_make_order(volatility=0.1)) == "calm"
    assert executor._classify_volatility(_make_order(volatility=0.5)) == "normal"
    assert executor._classify_volatility(_make_order(volatility=0.9)) == "high"


@pytest.mark.asyncio
async def test_cancel_replace_and_partial_remaining_quantity() -> None:
    loop = asyncio.get_running_loop()
    outcomes = [
        FakeOutcome("timeout"),
        FakeOutcome("fill", price=20001.0, quantity=1.0),
        FakeOutcome("fill", price=20002.0, quantity=1.0),
    ]
    config = LiveExecutorConfig(fill_timeout=0.01, max_retries=3, normal_wait_ms=10.0)
    api = FakeAPI(loop, outcomes=outcomes)
    executor = LiveExecutor(api=api, loop=loop, config=config)
    result = (await executor.execute([_make_order(lots=2.0)]))[0]
    assert len(api.place_calls) >= 3
    assert len(api.cancel_calls) >= 1
    assert int(api.place_calls[2]["order"].quantity) == 1
    assert result.status in {"filled", "partial"}


@pytest.mark.asyncio
async def test_stats_include_latency_and_quality_metrics() -> None:
    loop = asyncio.get_running_loop()
    outcomes = [FakeOutcome("fill", price=100.05, quantity=1.0) for _ in range(20)]
    config = LiveExecutorConfig(
        quality_slippage_bps=2.0,
        quality_breach_ratio=0.2,
        p99_alert_threshold_ms=200.0,
    )
    api = FakeAPI(loop, outcomes=outcomes)
    executor = LiveExecutor(api=api, loop=loop, config=config)
    orders: list[Order] = []
    for _ in range(20):
        order = _make_order(lots=1.0, price=100.0)
        now = monotonic_ns()
        order.metadata["quote_ingest_ns"] = now - 100_000_000
        order.metadata["signal_emit_ns"] = now - 20_000_000
        orders.append(order)
    await executor.execute(orders)
    stats = executor.get_fill_stats()
    assert stats["tick_to_order_p99_ms"] <= 200.0
    assert stats["pct_over_2bps"] > 0.0
    assert stats["quality_degraded"] == 1.0


@pytest.mark.asyncio
async def test_shadow_mode_submits_no_orders() -> None:
    loop = asyncio.get_running_loop()
    api = FakeAPI(loop, outcomes=[])
    config = LiveExecutorConfig(run_mode="shadow")
    executor = LiveExecutor(api=api, loop=loop, config=config)
    result = (await executor.execute([_make_order()]))[0]
    assert api.place_calls == []
    assert result.status == "cancelled"
    assert result.rejection_reason == "shadow_mode"


@pytest.mark.asyncio
async def test_rollout_limits_reject_large_order() -> None:
    loop = asyncio.get_running_loop()
    api = FakeAPI(loop, outcomes=[FakeOutcome("fill")])
    rollout = SimpleNamespace(enabled=True, max_contracts_per_order=1.0, max_total_contracts=5.0)
    executor = LiveExecutor(api=api, loop=loop, config=LiveExecutorConfig(), rollout_config=rollout)
    result = (await executor.execute([_make_order(lots=2.0)]))[0]
    assert result.status == "rejected"
    assert result.rejection_reason == "exceeds_rollout_limit"
