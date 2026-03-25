"""Integration test for paper disaster gap: bar gap-through triggers paper disaster fill before algo stop."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.core.position_engine import PositionEngine
from src.core.policies import ChandelierStopPolicy, PyramidAddPolicy, PyramidEntryPolicy
from src.core.types import (
    ContractSpecs,
    EngineConfig,
    MarketSignal,
    MarketSnapshot,
    Order,
    PyramidConfig,
    TradingHours,
)
from src.execution.paper_execution_engine import PaperExecutionEngine
from src.execution.engine import ExecutionResult


def _make_specs() -> ContractSpecs:
    return ContractSpecs(
        symbol="TXF",
        exchange="TAIFEX",
        currency="TWD",
        point_value=1.0,
        margin_initial=80000.0,
        margin_maintenance=64000.0,
        min_tick=1.0,
        trading_hours=TradingHours(open_time="08:45", close_time="13:45", timezone="Asia/Taipei"),
        fee_per_contract=50.0,
        tax_rate=0.001,
        lot_types={"large": 1.0},
    )


def _make_snapshot(price: float = 20000.0, atr: float = 100.0) -> MarketSnapshot:
    return MarketSnapshot(
        price=price,
        atr={"daily": atr},
        timestamp=datetime.now(),
        margin_per_unit=80000.0,
        point_value=1.0,
        min_lot=1.0,
        contract_specs=_make_specs(),
    )


def _make_signal(direction: float = 0.8, direction_conf: float = 0.9) -> MarketSignal:
    return MarketSignal(
        timestamp=datetime.now(),
        direction=direction,
        direction_conf=direction_conf,
        regime="trending",
        trend_strength=0.7,
        vol_forecast=0.5,
        suggested_stop_atr_mult=None,
        suggested_add_atr_mult=None,
        model_version="test",
        confidence_valid=True,
    )


class TestPaperDisasterGap:
    @pytest.mark.asyncio
    async def test_gap_through_triggers_paper_disaster_fill(self) -> None:
        mock_executor = MagicMock()
        mock_executor.execute = AsyncMock(return_value=[])
        mock_executor.get_fill_stats = MagicMock(return_value={})

        pyramid_config = PyramidConfig(
            max_loss=50000.0, stop_atr_mult=1.5, entry_conf_threshold=0.5
        )
        engine_config = EngineConfig(
            max_loss=pyramid_config.max_loss,
            disaster_atr_mult=4.5,
            disaster_stop_enabled=True,
        )
        position_engine = PositionEngine(
            entry_policy=PyramidEntryPolicy(pyramid_config),
            add_policy=PyramidAddPolicy(pyramid_config),
            stop_policy=ChandelierStopPolicy(pyramid_config),
            config=engine_config,
        )

        paper_engine = PaperExecutionEngine(
            executor=mock_executor,
            position_engine=position_engine,
            config=engine_config,
        )

        snapshot = _make_snapshot(20000.0, 100.0)
        signal = _make_signal()
        account = MagicMock()
        account.margin_ratio = 0.1
        account.drawdown_pct = 0.0
        account.equity = 2_000_000.0
        account.positions = []

        entry_orders = position_engine.on_snapshot(snapshot, signal=signal, account=account)
        entry_order = entry_orders[0]
        entry_result = ExecutionResult(
            order=entry_order,
            status="filled",
            fill_price=20000.0,
            expected_price=20000.0,
            slippage=0.0,
            fill_qty=2.0,
            remaining_qty=0.0,
        )

        mock_executor.execute = AsyncMock(return_value=[entry_result])
        await paper_engine.execute(entry_orders, snapshot)

        disaster_level = 20000.0 - 4.5 * 100.0
        gap_open_price = disaster_level - 50.0
        await paper_engine.on_bar_open("TXF", gap_open_price)
        assert paper_engine._active_disaster_stops == 0
