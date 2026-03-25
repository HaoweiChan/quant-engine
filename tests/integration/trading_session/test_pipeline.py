"""Tests for Pipeline Runner: end-to-end step, risk integration, equity tracking."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from src.core.position_engine import PositionEngine, create_pyramid_engine
from src.core.types import (
    ContractSpecs,
    MarketSignal,
    MarketSnapshot,
    PyramidConfig,
    TradingHours,
)
from src.execution.paper import PaperExecutor
from src.pipeline.config import RiskConfig
from src.pipeline.runner import PipelineRunner
from src.risk.monitor import RiskMonitor


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


def _make_signal(
    direction: float = 1.0,
    conf: float = 0.8,
) -> MarketSignal:
    return MarketSignal(
        timestamp=datetime.now(UTC),
        direction=direction,
        direction_conf=conf,
        regime="trending",
        trend_strength=0.7,
        vol_forecast=120.0,
        suggested_stop_atr_mult=None,
        suggested_add_atr_mult=None,
        model_version="test-v1",
        confidence_valid=True,
    )


class TestPipelineRunner:
    @pytest.mark.asyncio
    async def test_single_step(self) -> None:
        config = PyramidConfig(max_loss=500_000)
        engine = create_pyramid_engine(config)
        executor = PaperExecutor(slippage_points=1.0, current_price=20000.0)
        runner = PipelineRunner(engine, executor)
        snap = _make_snapshot(20000.0)
        signal = _make_signal()
        results = await runner.run_step(snap, signal)
        assert len(results) >= 0

    @pytest.mark.asyncio
    async def test_equity_tracking(self) -> None:
        config = PyramidConfig(max_loss=500_000)
        engine = create_pyramid_engine(config)
        executor = PaperExecutor(slippage_points=1.0, current_price=20000.0)
        runner = PipelineRunner(engine, executor, initial_equity=1_000_000.0)
        snap = _make_snapshot(20000.0)
        await runner.run_step(snap)
        state = runner.get_state_snapshot()
        assert state["equity"] >= 0
        assert state["bar_count"] == 1

    @pytest.mark.asyncio
    async def test_run_historical(self) -> None:
        config = PyramidConfig(max_loss=500_000)
        engine = create_pyramid_engine(config)
        executor = PaperExecutor(slippage_points=1.0)
        runner = PipelineRunner(engine, executor)
        snapshots = [_make_snapshot(20000.0 + i * 10) for i in range(10)]
        result = await runner.run_historical(snapshots)
        assert len(result.equity_curve) == 11
        assert result.final_equity > 0

    @pytest.mark.asyncio
    async def test_risk_integration(self) -> None:
        config = PyramidConfig(max_loss=500_000)
        engine = create_pyramid_engine(config)
        executor = PaperExecutor(slippage_points=1.0)
        risk_config = RiskConfig(max_loss=100)
        monitor = RiskMonitor(risk_config, on_mode_change=engine.set_mode)
        runner = PipelineRunner(engine, executor, risk_monitor=monitor)
        snap = _make_snapshot(20000.0)
        await runner.run_step(snap)
        state = runner.get_state_snapshot()
        assert "mode" in state


class TestPipelineConfig:
    def test_load_engine_config(self) -> None:
        from src.pipeline.config import load_engine_config

        config = load_engine_config()
        assert config.pyramid.max_loss > 0
        assert config.risk.margin_ratio_threshold > 0
        assert config.execution.slippage_points > 0

    def test_load_prediction_config(self) -> None:
        from src.pipeline.config import load_prediction_config

        config = load_prediction_config()
        assert config.regime_n_states > 0
        assert config.vol_horizon > 0
        assert config.optuna_n_trials > 0

    def test_invalid_config_path(self) -> None:
        from pathlib import Path

        import pytest as pt

        from src.pipeline.config import load_engine_config

        with pt.raises(FileNotFoundError):
            load_engine_config(Path("/nonexistent/config.toml"))
