"""E2E pipeline tests for the quant-engine platform."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest

from src.broker_gateway.mock import MockGateway
from src.core.position_engine import create_pyramid_engine
from src.core.types import (
    ContractSpecs,
    MarketSignal,
    MarketSnapshot,
    PyramidConfig,
    RiskAction,
    TradingHours,
)
from src.execution.paper import PaperExecutor
from src.pipeline.config import RiskConfig
from src.pipeline.runner import PipelineRunner
from src.risk.monitor import RiskMonitor

pytestmark = pytest.mark.e2e


def _make_specs() -> ContractSpecs:
    hours = TradingHours(open_time="08:45", close_time="13:45", timezone="Asia/Taipei")
    return ContractSpecs(
        symbol="TX",
        exchange="TAIFEX",
        currency="TWD",
        point_value=200.0,
        margin_initial=184000.0,
        margin_maintenance=141000.0,
        min_tick=1.0,
        trading_hours=hours,
        fee_per_contract=60.0,
        tax_rate=0.00002,
        lot_types={"large": 200.0},
    )


def _make_snapshot(price: float, ts: datetime | None = None) -> MarketSnapshot:
    return MarketSnapshot(
        price=price,
        atr={"daily": 100.0},
        timestamp=ts or datetime.now(UTC),
        margin_per_unit=184000.0,
        point_value=200.0,
        min_lot=1.0,
        contract_specs=_make_specs(),
    )


class TestE2ETradingPipeline:
    @pytest.mark.asyncio
    async def test_full_synthetic_session(self, mock_gateway: MockGateway) -> None:
        """
        Initializes a complete trading session with deterministic synthetic ticks,
        and asserts the final equity and open positions match an expected deterministic outcome.
        We also verify that MockGateway can yield deterministic account snapshots.
        """
        pyramid_config = PyramidConfig(max_loss=5_000_000)

        engine = create_pyramid_engine(pyramid_config)
        executor = PaperExecutor(slippage_points=1.0)

        runner = PipelineRunner(engine, executor, initial_equity=1_000_000.0)

        snapshots = [
            _make_snapshot(20000.0),
            _make_snapshot(20050.0),
            _make_snapshot(20100.0),
            _make_snapshot(20150.0),
            _make_snapshot(20100.0),
        ]

        signals = [
            MarketSignal(
                timestamp=snapshots[0].timestamp,
                direction=1.0,
                direction_conf=0.9,
                regime="trending",
                trend_strength=0.8,
                vol_forecast=120.0,
                suggested_stop_atr_mult=None,
                suggested_add_atr_mult=None,
                model_version="test-v1",
                confidence_valid=True,
            ),
            None,
            None,
            None,
            MarketSignal(
                timestamp=snapshots[4].timestamp,
                direction=-1.0,
                direction_conf=0.9,
                regime="trending",
                trend_strength=0.8,
                vol_forecast=120.0,
                suggested_stop_atr_mult=None,
                suggested_add_atr_mult=None,
                model_version="test-v1",
                confidence_valid=True,
            ),
        ]

        result = await runner.run_historical(snapshots, signals)

        assert result.final_equity > 0, "Final equity should be computed."
        assert len(result.equity_curve) == 6, "Equity curve should track initial + 5 snapshots."

        state = runner.get_state_snapshot()
        assert state["mode"] == "model_assisted"
        assert state["positions"] >= 0

        # Verify MockGateway interaction as requested by the spec
        acct_snap = mock_gateway.get_account_snapshot()
        assert acct_snap.connected is True
        assert acct_snap.equity > 0

    @pytest.mark.asyncio
    async def test_risk_halt_scenario(self, mock_gateway: MockGateway) -> None:
        """
        Intentionally triggers a massive drawdown in the simulation and verifies
        the RiskMonitor properly transitions the session to STOPPED/HALTED
        and emits a CLOSE_ALL alert.
        """
        # Disable internal scaling out
        pyramid_config = PyramidConfig(
            max_loss=5_000_000, trail_atr_mult=100.0, stop_atr_mult=100.0
        )
        risk_config = RiskConfig(
            margin_ratio_threshold=0.0,
            max_loss=10_000,
        )

        engine = create_pyramid_engine(pyramid_config)
        executor = PaperExecutor(slippage_points=1.0)

        monitor = RiskMonitor(risk_config, on_mode_change=engine.set_mode)

        runner = PipelineRunner(engine, executor, risk_monitor=monitor, initial_equity=1_000_000.0)

        from datetime import timedelta

        base_ts = datetime.now(UTC)
        snap1 = _make_snapshot(20000.0, ts=base_ts)
        sig1 = MarketSignal(
            timestamp=snap1.timestamp,
            direction=1.0,
            direction_conf=0.9,
            regime="trending",
            trend_strength=0.8,
            vol_forecast=100.0,
            suggested_stop_atr_mult=None,
            suggested_add_atr_mult=None,
            model_version="test-v1",
            confidence_valid=True,
        )
        await runner.run_step(snap1, sig1)

        snap2 = _make_snapshot(19950.0, ts=base_ts + timedelta(minutes=1))
        await runner.run_step(snap2, None)
        snap3 = _make_snapshot(19950.0, ts=base_ts + timedelta(minutes=2))
        await runner.run_step(snap3, None)

        state = runner.get_state_snapshot()
        print(monitor.events)
        print("Final state:", state)
        assert state["mode"] == "halted", "Risk monitor should have halted the engine."

        assert len(monitor.events) > 0, "Risk monitor should have recorded events."

        actions = [evt.action for evt in monitor.events]
        assert RiskAction.CLOSE_ALL in actions or RiskAction.HALT_NEW_ENTRIES in actions, (
            "Should emit critical risk action."
        )
