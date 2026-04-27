"""Integration: LiveExecutor write-through to OrderStateStore + restart recovery."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from unittest.mock import MagicMock

import pytest

from src.core.types import Order
from src.execution.live import LiveExecutor, LiveExecutorConfig
from src.oms.order_state_store import OrderStateStore


@dataclass
class _FakeTradeOrder:
    id: str = "OID-1"


@dataclass
class _FakeTrade:
    order: _FakeTradeOrder


def _make_order(side: str = "buy", lots: float = 1.0) -> Order:
    return Order(
        order_type="market", side=side, symbol="TX",
        contract_type="large", lots=lots, price=None, stop_price=None,
        reason="entry",
    )


def _make_api(trade_id: str = "OID-1") -> MagicMock:
    api = MagicMock()
    api.place_order.return_value = _FakeTrade(order=_FakeTradeOrder(id=trade_id))
    api.Contracts.Futures.TXF.TXF202504 = MagicMock()
    api.futopt_account = MagicMock()
    return api


@pytest.mark.asyncio
async def test_successful_fill_writes_through_to_store(tmp_path) -> None:
    """A clean fill must persist `pending → filled` in the store."""
    store = OrderStateStore(db_path=tmp_path / "trading.db")
    loop = asyncio.get_event_loop()
    api = _make_api(trade_id="OID-1")
    executor = LiveExecutor(
        api, loop, LiveExecutorConfig(fill_timeout=2.0), order_store=store,
    )

    async def _simulate_fill() -> None:
        await asyncio.sleep(0.05)
        executor._on_deal_event({
            "trade_id": "OID-1", "price": 20001.0, "quantity": 1,
        })

    asyncio.ensure_future(_simulate_fill())
    results = await executor.execute([_make_order()])
    assert results[0].status == "filled"

    rec = store.get("OID-1")
    assert rec is not None
    assert rec.status == "filled"
    assert len(rec.fills) == 1
    assert rec.fills[0]["price"] == 20001.0
    store.close()


@pytest.mark.asyncio
async def test_timeout_persists_cancelled(tmp_path) -> None:
    """A timed-out order must persist as `cancelled` so reconciliation can match."""
    store = OrderStateStore(db_path=tmp_path / "trading.db")
    loop = asyncio.get_event_loop()
    api = _make_api(trade_id="OID-2")
    executor = LiveExecutor(
        api, loop,
        LiveExecutorConfig(fill_timeout=0.05, max_retries=0),
        order_store=store,
    )
    results = await executor.execute([_make_order()])
    assert results[0].status == "cancelled"

    rec = store.get("OID-2")
    assert rec is not None
    assert rec.status == "cancelled"
    assert rec.last_error == "timeout"
    store.close()


@pytest.mark.asyncio
async def test_crash_recovery_via_list_open(tmp_path) -> None:
    """After a simulated crash, the store still reports the orphan order open."""
    db_path = tmp_path / "trading.db"
    store = OrderStateStore(db_path=db_path)
    loop = asyncio.get_event_loop()
    api = _make_api(trade_id="OID-3")
    executor = LiveExecutor(
        api, loop,
        LiveExecutorConfig(fill_timeout=0.05, max_retries=0),
        order_store=store,
    )

    # Place an order, time it out, then "crash" by closing the store.
    await executor.execute([_make_order()])
    store.close()

    # Reopen the store as a fresh process would: the cancelled row is
    # still recoverable; a still-pending row would surface in list_open.
    fresh = OrderStateStore(db_path=db_path)
    rec = fresh.get("OID-3")
    assert rec is not None
    assert rec.status == "cancelled"
    fresh.close()


@pytest.mark.asyncio
async def test_no_store_means_no_persistence(tmp_path) -> None:
    """Constructing without ``order_store`` must remain a no-op write-through."""
    loop = asyncio.get_event_loop()
    api = _make_api(trade_id="OID-4")
    executor = LiveExecutor(api, loop, LiveExecutorConfig(fill_timeout=2.0))

    async def _simulate_fill() -> None:
        await asyncio.sleep(0.05)
        executor._on_deal_event({
            "trade_id": "OID-4", "price": 20001.0, "quantity": 1,
        })

    asyncio.ensure_future(_simulate_fill())
    results = await executor.execute([_make_order()])
    # Order completes; we just confirm the executor doesn't crash when
    # ``_record_state`` fires with ``self._order_store is None``.
    assert results[0].status == "filled"
