"""End-to-end integration test: bar data -> PositionEngine (with pre-trade gate)
-> OMS -> MarketImpactFillModel -> verify fills have impact/spread/latency populated.
Exercises the entire Phase A institutional-grade-upgrade stack.
"""
from __future__ import annotations

from datetime import datetime

import pytest

from src.core.position_engine import create_pyramid_engine
from src.core.types import (
    AccountState,
    ContractSpecs,
    ImpactParams,
    MarketSignal,
    MarketSnapshot,
    OMSConfig,
    PreTradeRiskConfig,
    PyramidConfig,
    TradingHours,
)
from src.execution.paper import PaperExecutor
from src.oms.oms import OrderManagementSystem
from src.risk.pre_trade import PreTradeRiskCheck
from src.simulator.fill_model import ImpactCalibrator, MarketImpactFillModel


def _make_snapshot(price: float, atr: float = 200.0) -> MarketSnapshot:
    return MarketSnapshot(
        price=price,
        atr={"daily": atr},
        timestamp=datetime(2024, 6, 1),
        margin_per_unit=184_000.0,
        point_value=200.0,
        min_lot=1.0,
        contract_specs=ContractSpecs(
            symbol="TX", exchange="TAIFEX", currency="TWD",
            point_value=200.0, margin_initial=184_000.0,
            margin_maintenance=141_000.0, min_tick=1.0,
            trading_hours=TradingHours(
                open_time="08:45", close_time="13:45", timezone="Asia/Taipei",
            ),
            fee_per_contract=36.0, tax_rate=0.00002,
            lot_types={"large": 50000.0, "mini": 12500.0},
        ),
    )


def _make_signal(direction: float = 0.8) -> MarketSignal:
    return MarketSignal(
        timestamp=datetime(2024, 6, 1),
        direction=direction,
        direction_conf=0.85,
        regime="trending",
        trend_strength=0.7,
        vol_forecast=0.02,
        suggested_stop_atr_mult=1.5,
        suggested_add_atr_mult=4.0,
        model_version="v1",
        confidence_valid=True,
    )


def _make_account(equity: float = 2_000_000.0) -> AccountState:
    return AccountState(
        equity=equity, unrealized_pnl=0.0, realized_pnl=0.0,
        margin_used=0.0, margin_available=equity,
        margin_ratio=0.0, drawdown_pct=0.0,
        positions=[], timestamp=datetime(2024, 6, 1),
    )


class TestPhaseAEndToEnd:
    """Full pipeline: PositionEngine -> PreTradeRisk -> OMS -> MarketImpactFillModel."""

    def test_entry_flows_through_full_stack(self) -> None:
        config = PyramidConfig(max_loss=500_000)
        pre_trade = PreTradeRiskCheck(PreTradeRiskConfig(enabled=True))
        engine = create_pyramid_engine(config, pre_trade_check=pre_trade)
        impact_model = MarketImpactFillModel(ImpactParams(seed=42))
        oms = OrderManagementSystem(
            impact_model=impact_model,
            config=OMSConfig(enabled=True, passthrough_threshold_pct=0.01),
        )
        snapshot = _make_snapshot(20000.0)
        signal = _make_signal(direction=0.8)
        account = _make_account()
        orders = engine.on_snapshot(snapshot, signal, account)
        assert len(orders) > 0, "PositionEngine should generate entry orders"
        for o in orders:
            assert "urgency" in o.metadata
        market_data = {"adv": 50000.0, "volatility": 0.015, "volume": 10000.0}
        sliced = oms.schedule(orders, market_data)
        assert len(sliced) == len(orders)
        for s in sliced:
            assert s.algorithm in ("passthrough", "twap", "vwap", "pov")
            assert len(s.child_orders) >= 1
        for s in sliced:
            for child in s.child_orders:
                bar = {
                    "open": 20000.0, "high": 20100.0, "low": 19900.0,
                    "close": 20050.0, "volume": 10000.0, "spread": 2.0,
                }
                fill = impact_model.simulate(child.order, bar, snapshot.timestamp)
                assert fill.market_impact >= 0.0
                assert fill.spread_cost != 0.0
                assert fill.latency_ms > 0.0
                assert fill.fill_qty > 0.0

    def test_calibrator_receives_feedback_from_executor(self) -> None:
        calibrator = ImpactCalibrator(initial_k=1.0, alpha=0.1, min_samples=1)
        executor = PaperExecutor(slippage_points=2.0, current_price=20000.0)
        executor.set_calibrator(calibrator)
        config = PyramidConfig(max_loss=500_000)
        engine = create_pyramid_engine(config)
        impact_model = MarketImpactFillModel()
        oms = OrderManagementSystem(impact_model=impact_model, config=OMSConfig(enabled=True))
        snapshot = _make_snapshot(20000.0)
        signal = _make_signal(direction=0.8)
        account = _make_account()
        orders = engine.on_snapshot(snapshot, signal, account)
        if not orders:
            pytest.skip("No orders generated")
        market_data = {"adv": 50000.0, "volatility": 0.015, "volume": 10000.0}
        sliced = oms.schedule(orders, market_data)

        async def _run() -> None:
            await executor.execute_sliced(sliced, mid_price=20000.0)

        import asyncio
        asyncio.get_event_loop().run_until_complete(_run())
        assert len(executor.parent_summaries) > 0
        assert executor.parent_summaries[0].actual_vwap > 0

    def test_impact_report_in_backtest(self) -> None:
        from src.adapters.taifex import TaifexAdapter
        from src.simulator.backtester import BacktestRunner

        config = PyramidConfig(max_loss=500_000)
        adapter = TaifexAdapter()
        fill_model = MarketImpactFillModel(ImpactParams(seed=42))
        runner = BacktestRunner(config, adapter, fill_model=fill_model)
        bars = [
            {
                "symbol": "TX", "price": 20000.0 + i * 10,
                "open": 20000.0, "high": 20100.0 + i * 10,
                "low": 19900.0 + i * 10, "close": 20000.0 + i * 10,
                "daily_atr": 200.0, "volume": 50000.0, "spread": 2.0,
            }
            for i in range(50)
        ]
        from datetime import timedelta
        base = datetime(2024, 1, 1)
        timestamps = [base + timedelta(days=i) for i in range(50)]
        signals = [_make_signal(0.8 if i < 30 else -0.8) for i in range(50)]
        result = runner.run(bars, signals=signals, timestamps=timestamps)
        assert result.impact_report is not None
        assert result.impact_report.realistic_pnl == result.equity_curve[-1] - result.equity_curve[0]
        assert "total_market_impact" in result.metrics
        assert "total_spread_cost" in result.metrics
        assert "avg_latency_ms" in result.metrics
        assert "partial_fill_count" in result.metrics
