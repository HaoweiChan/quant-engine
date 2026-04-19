"""Unit tests for PaperExecutor commission accounting (Phase B1).

The paper-trade fill model historically applied slippage only, producing
PnL that overstated the backtester's MarketImpactFillModel by NT$50/leg
on MTX (NT$100 RT) and equivalent amounts on TX/TMF. This test pins the
new contract: every fill carries `metadata['commission']` equal to
`lots * commission_per_contract_per_side`, and slippage continues to act
as a price adjustment.
"""
from __future__ import annotations

import asyncio

import pytest

from src.core.types import Order
from src.execution.paper import PaperExecutor


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _make_order(side: str, lots: float = 1.0, symbol: str = "MTX") -> Order:
    return Order(
        order_type="market",
        side=side,
        symbol=symbol,
        contract_type="small",
        lots=lots,
        price=None,
        stop_price=None,
        reason="entry",
    )


def test_paper_executor_records_per_side_commission_in_metadata() -> None:
    # MTX round-trip = NT$40, so per-side = NT$20.
    executor = PaperExecutor(
        slippage_points=0.05,
        current_price=20_000.0,
        commission_per_contract_per_side=20.0,
        margin_per_lot=46_000.0,
        available_margin=1_000_000.0,
    )
    results = _run(executor.execute([_make_order("buy", lots=3)]))
    assert len(results) == 1
    res = results[0]
    assert res.status == "filled"
    # 3 contracts × NT$20/side = NT$60 commission for this single fill.
    assert res.metadata.get("commission") == pytest.approx(60.0)
    # Slippage acts on price (adverse for buys).
    assert res.fill_price == pytest.approx(20_000.05)


def test_paper_executor_round_trip_total_commission_matches_round_trip_config() -> None:
    """Two fills (entry + exit) must aggregate to the round-trip commission
    declared in InstrumentCostConfig. This is the contract that keeps
    paper PnL aligned with the backtester's cost model.
    """
    executor = PaperExecutor(
        slippage_points=0.0,  # isolate commission
        current_price=20_000.0,
        commission_per_contract_per_side=20.0,
        margin_per_lot=46_000.0,
        available_margin=1_000_000.0,
    )
    entry = _run(executor.execute([_make_order("buy", lots=2)]))[0]
    exit_ = _run(executor.execute([_make_order("sell", lots=2)]))[0]
    total = entry.metadata.get("commission", 0.0) + exit_.metadata.get("commission", 0.0)
    # 2 contracts × NT$20/side × 2 sides = NT$80 == 2 × MTX RT commission.
    assert total == pytest.approx(80.0)


def test_paper_executor_default_commission_is_zero() -> None:
    """Backwards-compat: if a caller doesn't pass commission, fills
    record commission=0 rather than crashing or applying surprise costs.
    """
    executor = PaperExecutor(
        slippage_points=0.0,
        current_price=20_000.0,
        margin_per_lot=46_000.0,
        available_margin=1_000_000.0,
    )
    res = _run(executor.execute([_make_order("buy", lots=1)]))[0]
    assert res.metadata.get("commission") == pytest.approx(0.0)
