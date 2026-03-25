"""Tests for Execution Engine OMS integration: parent-child tracking, impact feedback, extended stats."""
from __future__ import annotations

from datetime import datetime

import pytest

from src.core.types import ChildOrder, Order, SlicedOrder
from src.execution.engine import ParentFillSummary
from src.execution.paper import PaperExecutor
from src.simulator.fill_model import ImpactCalibrator


def _make_order(
    side: str = "buy",
    lots: float = 10.0,
    reason: str = "entry",
    metadata: dict | None = None,
) -> Order:
    return Order(
        order_type="market", side=side, symbol="TX",
        contract_type="large", lots=lots, price=None,
        stop_price=None, reason=reason,
        metadata=metadata or {},
    )


def _make_sliced(
    parent: Order,
    child_lots: list[float],
    algorithm: str = "twap",
    estimated_impact: float = 5.0,
) -> SlicedOrder:
    now = datetime.now()
    children = [
        ChildOrder(
            order=Order(
                order_type=parent.order_type, side=parent.side,
                symbol=parent.symbol, contract_type=parent.contract_type,
                lots=lots, price=parent.price, stop_price=parent.stop_price,
                reason=parent.reason, metadata=dict(parent.metadata),
            ),
            scheduled_time=now,
            slice_pct=lots / parent.lots,
        )
        for lots in child_lots
    ]
    return SlicedOrder(
        parent_order=parent, child_orders=children,
        algorithm=algorithm, estimated_impact=estimated_impact,
        schedule=[now] * len(children),
    )


class TestParentChildTracking:
    @pytest.mark.asyncio
    async def test_child_orders_aggregated_to_parent(self) -> None:
        executor = PaperExecutor(slippage_points=1.0, current_price=20000.0)
        parent = _make_order(lots=30.0)
        sliced = _make_sliced(parent, [10.0, 10.0, 10.0])
        results = await executor.execute_sliced([sliced], mid_price=20000.0)
        assert len(results) == 3
        summaries = executor.parent_summaries
        assert len(summaries) == 1
        assert summaries[0].total_fill_qty == 30.0
        assert summaries[0].total_remaining == 0.0

    @pytest.mark.asyncio
    async def test_parent_vwap_from_child_fills(self) -> None:
        executor = PaperExecutor(slippage_points=2.0, current_price=20000.0)
        parent = _make_order(lots=20.0)
        sliced = _make_sliced(parent, [10.0, 10.0])
        await executor.execute_sliced([sliced], mid_price=20000.0)
        summary = executor.parent_summaries[0]
        assert summary.actual_vwap == pytest.approx(20002.0, abs=0.01)

    @pytest.mark.asyncio
    async def test_passthrough_order_standalone(self) -> None:
        executor = PaperExecutor(slippage_points=1.0, current_price=20000.0)
        parent = _make_order(lots=5.0)
        sliced = _make_sliced(parent, [5.0], algorithm="passthrough", estimated_impact=0.0)
        await executor.execute_sliced([sliced], mid_price=20000.0)
        summary = executor.parent_summaries[0]
        assert summary.algorithm == "passthrough"
        assert summary.status == "filled"

    @pytest.mark.asyncio
    async def test_multiple_parent_orders(self) -> None:
        executor = PaperExecutor(slippage_points=1.0, current_price=20000.0)
        p1 = _make_order(lots=20.0)
        p2 = _make_order(side="sell", lots=10.0)
        s1 = _make_sliced(p1, [10.0, 10.0], algorithm="twap")
        s2 = _make_sliced(p2, [5.0, 5.0], algorithm="vwap")
        await executor.execute_sliced([s1, s2], mid_price=20000.0)
        assert len(executor.parent_summaries) == 2
        assert executor.parent_summaries[0].algorithm == "twap"
        assert executor.parent_summaries[1].algorithm == "vwap"


class TestImpactFeedback:
    @pytest.mark.asyncio
    async def test_calibrator_receives_actual_impact(self) -> None:
        calibrator = ImpactCalibrator(initial_k=1.0, alpha=0.1, min_samples=1)
        executor = PaperExecutor(slippage_points=3.0, current_price=20000.0)
        executor.set_calibrator(calibrator)
        parent = _make_order(lots=20.0)
        sliced = _make_sliced(parent, [10.0, 10.0], estimated_impact=5.0)
        await executor.execute_sliced([sliced], mid_price=20000.0)
        assert len(calibrator._samples) == 1
        assert calibrator._samples[0] == (5.0, pytest.approx(3.0, abs=0.01))

    @pytest.mark.asyncio
    async def test_no_calibrator_no_error(self) -> None:
        executor = PaperExecutor(slippage_points=1.0, current_price=20000.0)
        parent = _make_order(lots=10.0)
        sliced = _make_sliced(parent, [10.0])
        results = await executor.execute_sliced([sliced], mid_price=20000.0)
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_zero_mid_price_skips_calibration(self) -> None:
        calibrator = ImpactCalibrator(initial_k=1.0, min_samples=1)
        executor = PaperExecutor(slippage_points=1.0, current_price=20000.0)
        executor.set_calibrator(calibrator)
        parent = _make_order(lots=10.0)
        sliced = _make_sliced(parent, [10.0])
        await executor.execute_sliced([sliced], mid_price=0.0)
        assert len(calibrator._samples) == 0


class TestExtendedStats:
    @pytest.mark.asyncio
    async def test_predicted_impact_accuracy(self) -> None:
        executor = PaperExecutor(slippage_points=2.0, current_price=20000.0)
        for i in range(5):
            parent = _make_order(lots=10.0 + i * 5)
            sliced = _make_sliced(parent, [parent.lots], estimated_impact=2.0 + i * 0.5)
            await executor.execute_sliced([sliced], mid_price=20000.0)
        stats = executor.get_extended_stats()
        assert "predicted_impact_accuracy" in stats
        assert isinstance(stats["predicted_impact_accuracy"], float)

    @pytest.mark.asyncio
    async def test_oms_algorithm_performance(self) -> None:
        executor = PaperExecutor(slippage_points=1.0, current_price=20000.0)
        p1 = _make_order(lots=10.0)
        p2 = _make_order(lots=20.0)
        s1 = _make_sliced(p1, [10.0], algorithm="twap", estimated_impact=3.0)
        s2 = _make_sliced(p2, [10.0, 10.0], algorithm="vwap", estimated_impact=5.0)
        await executor.execute_sliced([s1, s2], mid_price=20000.0)
        stats = executor.get_extended_stats()
        algo_perf = stats["oms_algorithm_performance"]
        assert "twap" in algo_perf
        assert "vwap" in algo_perf
        assert algo_perf["twap"]["count"] == 1.0
        assert algo_perf["vwap"]["count"] == 1.0
        assert algo_perf["twap"]["fill_rate"] == 1.0

    @pytest.mark.asyncio
    async def test_empty_stats(self) -> None:
        executor = PaperExecutor(current_price=20000.0)
        stats = executor.get_extended_stats()
        assert stats["predicted_impact_accuracy"] == 0.0
        assert stats["oms_algorithm_performance"] == {}


class TestParentFillSummary:
    def test_status_filled(self) -> None:
        summary = ParentFillSummary(
            parent_order=_make_order(),
            algorithm="twap", estimated_impact=5.0,
            actual_vwap=20001.0, total_fill_qty=10.0,
            total_remaining=0.0, child_results=[],
        )
        assert summary.status == "filled"

    def test_status_partial(self) -> None:
        summary = ParentFillSummary(
            parent_order=_make_order(),
            algorithm="twap", estimated_impact=5.0,
            actual_vwap=20001.0, total_fill_qty=5.0,
            total_remaining=5.0, child_results=[],
        )
        assert summary.status == "partial"

    def test_status_rejected(self) -> None:
        summary = ParentFillSummary(
            parent_order=_make_order(),
            algorithm="twap", estimated_impact=5.0,
            actual_vwap=0.0, total_fill_qty=0.0,
            total_remaining=10.0, child_results=[],
        )
        assert summary.status == "rejected"
