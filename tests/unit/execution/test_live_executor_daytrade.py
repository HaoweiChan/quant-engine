"""LiveExecutor must translate Order.daytrade -> shioaji FuturesOCType.DayTrade.

This is the only place an Order's daytrade flag becomes the actual broker
flag, so a regression here would silently downgrade 當沖 orders to
``FuturesOCType.Auto`` (full overnight margin) without any visible error.
"""
from __future__ import annotations

import asyncio

import pytest

from src.core.types import Order
from src.execution.live import LiveExecutor


sj = pytest.importorskip("shioaji")


class _StubApi:
    """Minimal shioaji API stand-in: provides ``Order`` and ``futopt_account``."""

    def __init__(self) -> None:
        from shioaji.account import FutureAccount

        self.Order = sj.Order
        self.futopt_account = FutureAccount(
            account_id="00000000",
            account_type="F",
            broker_id="9A95",
            person_id="X000000000",
            signed=True,
            username="test",
        )

    def set_order_callback(self, _cb) -> None:  # noqa: D401
        return None


@pytest.fixture
def executor():
    """Yield a LiveExecutor and tear down its event loop so subsequent
    tests in the same process don't trip ``asyncio.get_event_loop()``
    on a closed/orphan loop."""
    api = _StubApi()
    loop = asyncio.new_event_loop()
    try:
        yield LiveExecutor(api=api, loop=loop)
    finally:
        loop.close()


def _order(order_type: str, side: str = "buy", daytrade: bool = False, **kwargs) -> Order:
    return Order(
        order_type=order_type, side=side, symbol="TX", contract_type="large",
        lots=1, price=kwargs.get("price"), stop_price=kwargs.get("stop_price"),
        reason=kwargs.get("reason", "entry"), daytrade=daytrade,
    )


def test_market_buy_daytrade_uses_daytrade_octype(executor: LiveExecutor):
    sj_order = executor._build_sj_order(_order("market", daytrade=True))
    assert sj_order.octype == sj.constant.FuturesOCType.DayTrade
    assert sj_order.price_type == sj.constant.FuturesPriceType.MKT
    assert sj_order.order_type == sj.constant.OrderType.IOC
    assert sj_order.action == sj.constant.Action.Buy


def test_market_buy_default_uses_auto_octype(executor: LiveExecutor):
    """The default path (no daytrade flag) must remain ``Auto`` so every
    other strategy in the repo keeps its existing live behaviour."""
    sj_order = executor._build_sj_order(_order("market"))
    assert sj_order.octype == sj.constant.FuturesOCType.Auto


def test_limit_sell_daytrade_uses_daytrade_octype(executor: LiveExecutor):
    sj_order = executor._build_sj_order(
        _order("limit", side="sell", price=20_000.0, daytrade=True, reason="partial_exit"),
    )
    assert sj_order.octype == sj.constant.FuturesOCType.DayTrade
    assert sj_order.price_type == sj.constant.FuturesPriceType.LMT
    assert sj_order.order_type == sj.constant.OrderType.ROD
    assert sj_order.action == sj.constant.Action.Sell


def test_stop_order_daytrade_uses_daytrade_octype(executor: LiveExecutor):
    sj_order = executor._build_sj_order(
        _order("stop", side="sell", stop_price=19_500.0, daytrade=True, reason="stop_loss"),
    )
    assert sj_order.octype == sj.constant.FuturesOCType.DayTrade
