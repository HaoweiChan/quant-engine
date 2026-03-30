"""Tests for position reconciler with mocked shioaji responses."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.reconciliation.reconciler import (
    PositionReconciler,
    ReconciliationConfig,
)


@dataclass
class FakePosition:
    symbol: str = "TX"
    direction: str = "long"
    lots: float = 2.0


@dataclass
class FakeBrokerPosition:
    code: str = "TXFC5"
    direction: str = "Buy"
    quantity: int = 2


@dataclass
class FakeBrokerMargin:
    equity: float = 2_000_000.0
    margin_ratio: float = 0.35


def _make_api(
    broker_positions: list | None = None,
    broker_margin: FakeBrokerMargin | None = None,
    broker_fills: list | None = None,
    open_orders: list | None = None,
) -> MagicMock:
    api = MagicMock()
    api.futopt_account = MagicMock()
    api.list_positions.return_value = broker_positions or []
    api.margin.return_value = broker_margin or FakeBrokerMargin()
    api.list_recent_fills.return_value = broker_fills or []
    api.list_open_orders.return_value = open_orders or []
    api.cancel_order = MagicMock()
    return api


class TestReconcilerMatch:
    @pytest.mark.asyncio
    async def test_no_mismatches_when_matching(self) -> None:
        api = _make_api(
            broker_positions=[FakeBrokerPosition(code="TX", direction="Buy", quantity=2)],
        )
        engine_positions = [FakePosition(symbol="TX", direction="long", lots=2.0)]
        reconciler = PositionReconciler(
            api=api,
            get_engine_positions=lambda: engine_positions,
            get_engine_equity=lambda: 2_000_000.0,
        )
        await reconciler._reconcile()
        assert len(reconciler.mismatches) == 0


class TestReconcilerQuantityMismatch:
    @pytest.mark.asyncio
    async def test_quantity_mismatch_detected(self) -> None:
        api = _make_api(
            broker_positions=[FakeBrokerPosition(code="TX", direction="Buy", quantity=3)],
        )
        engine_positions = [FakePosition(symbol="TX", direction="long", lots=2.0)]
        reconciler = PositionReconciler(
            api=api,
            get_engine_positions=lambda: engine_positions,
            get_engine_equity=lambda: 2_000_000.0,
        )
        await reconciler._reconcile()
        assert len(reconciler.mismatches) == 1
        assert reconciler.mismatches[0].kind == "quantity"


class TestReconcilerOrphan:
    @pytest.mark.asyncio
    async def test_orphan_detected(self) -> None:
        api = _make_api(
            broker_positions=[FakeBrokerPosition(code="MX", direction="Buy", quantity=1)],
        )
        reconciler = PositionReconciler(
            api=api,
            get_engine_positions=lambda: [],
            get_engine_equity=lambda: 2_000_000.0,
        )
        await reconciler._reconcile()
        orphans = [m for m in reconciler.mismatches if m.kind == "orphan"]
        assert len(orphans) == 1


class TestReconcilerEquity:
    @pytest.mark.asyncio
    async def test_equity_deviation_detected(self) -> None:
        api = _make_api(broker_margin=FakeBrokerMargin(equity=2_000_000.0))
        reconciler = PositionReconciler(
            api=api,
            get_engine_positions=lambda: [],
            get_engine_equity=lambda: 1_800_000.0,
            config=ReconciliationConfig(equity_threshold_pct=0.02),
        )
        await reconciler._reconcile()
        equity_mismatches = [m for m in reconciler.mismatches if m.kind == "equity"]
        assert len(equity_mismatches) == 1


class TestReconcilerHalt:
    @pytest.mark.asyncio
    async def test_halt_on_mismatch_policy(self) -> None:
        api = _make_api(
            broker_positions=[FakeBrokerPosition(code="MX", direction="Buy", quantity=1)],
        )
        halt_called = []
        config = ReconciliationConfig(policy="halt_on_mismatch")
        reconciler = PositionReconciler(
            api=api,
            get_engine_positions=lambda: [],
            get_engine_equity=lambda: 2_000_000.0,
            config=config,
            on_halt=lambda: halt_called.append(True),
        )
        await reconciler._reconcile()
        assert len(halt_called) == 1


class TestReconcilerDispatch:
    @pytest.mark.asyncio
    async def test_alerts_dispatched_on_mismatch(self) -> None:
        api = _make_api(
            broker_positions=[FakeBrokerPosition(code="MX", direction="Buy", quantity=1)],
        )
        mock_dispatcher = AsyncMock()
        mock_dispatcher.dispatch = AsyncMock(return_value=True)
        reconciler = PositionReconciler(
            api=api,
            get_engine_positions=lambda: [],
            get_engine_equity=lambda: 2_000_000.0,
            dispatcher=mock_dispatcher,
        )
        await reconciler._reconcile()
        mock_dispatcher.dispatch.assert_called_once()


class TestReconcilerLoop:
    @pytest.mark.asyncio
    async def test_start_and_stop(self) -> None:
        api = _make_api()
        reconciler = PositionReconciler(
            api=api,
            get_engine_positions=lambda: [],
            get_engine_equity=lambda: 2_000_000.0,
        )
        task = reconciler.start(interval=0.05)
        await asyncio.sleep(0.15)
        reconciler.stop()
        await asyncio.sleep(0.05)
        assert task.cancelled() or task.done()


class TestStartupReconciliation:
    @pytest.mark.asyncio
    async def test_startup_freeze_and_manual_resume_gate(self) -> None:
        api = _make_api(
            broker_positions=[FakeBrokerPosition(code="TX", direction="Buy", quantity=2)],
        )
        engine_positions = [FakePosition(symbol="TX", direction="long", lots=2.0)]
        reconciler = PositionReconciler(
            api=api,
            get_engine_positions=lambda: engine_positions,
            get_engine_equity=lambda: 2_000_000.0,
        )
        startup_safe = await reconciler.run_startup_reconciliation()
        assert startup_safe
        assert reconciler.startup_frozen
        assert not reconciler.can_emit_orders()
        assert reconciler.confirm_resume("operator-1")
        assert reconciler.can_emit_orders()
        assert len(reconciler.resume_audit) == 1

    @pytest.mark.asyncio
    async def test_startup_open_order_cleanup(self) -> None:
        open_order = MagicMock()
        api = _make_api(open_orders=[open_order])
        reconciler = PositionReconciler(
            api=api,
            get_engine_positions=lambda: [],
            get_engine_equity=lambda: 2_000_000.0,
        )
        await reconciler.run_startup_reconciliation()
        api.cancel_order.assert_called_once_with(open_order)

    @pytest.mark.asyncio
    async def test_critical_mismatch_blocks_resume(self) -> None:
        api = _make_api(
            broker_positions=[FakeBrokerPosition(code="MX", direction="Buy", quantity=1)],
        )
        reconciler = PositionReconciler(
            api=api,
            get_engine_positions=lambda: [],
            get_engine_equity=lambda: 2_000_000.0,
        )
        startup_safe = await reconciler.run_startup_reconciliation()
        assert not startup_safe
        assert not reconciler.confirm_resume("operator-1")
        assert not reconciler.can_emit_orders()

    @pytest.mark.asyncio
    async def test_continuity_unavailable_blocks_resume(self) -> None:
        api = _make_api()
        del api.list_recent_fills
        reconciler = PositionReconciler(
            api=api,
            get_engine_positions=lambda: [],
            get_engine_equity=lambda: 2_000_000.0,
        )
        startup_safe = await reconciler.run_startup_reconciliation()
        assert not startup_safe
