"""Tests for PositionEngine disaster stop integration."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock

from src.core.policies import ChandelierStopPolicy, PyramidAddPolicy, PyramidEntryPolicy
from src.core.position_engine import PositionEngine
from src.core.types import (
    ContractSpecs,
    EngineConfig,
    MarketSignal,
    MarketSnapshot,
    PyramidConfig,
    TradingHours,
)


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


def _make_config() -> PyramidConfig:
    return PyramidConfig(max_loss=50000.0, entry_conf_threshold=0.5)


def _engine(config: PyramidConfig | None = None) -> PositionEngine:
    cfg = config or _make_config()
    return PositionEngine(
        entry_policy=PyramidEntryPolicy(cfg),
        add_policy=PyramidAddPolicy(cfg),
        stop_policy=ChandelierStopPolicy(cfg),
        config=EngineConfig(max_loss=cfg.max_loss),
    )


class TestPositionEngineDisaster:
    def test_entry_orders_carry_parent_position_id(self) -> None:
        engine = _engine()
        snapshot = _make_snapshot(20000.0, 100.0)
        signal = _make_signal()
        orders = engine.on_snapshot(snapshot, signal=signal, account=None)
        entry_orders = [o for o in orders if o.reason == "entry"]
        assert len(entry_orders) == 1
        assert entry_orders[0].parent_position_id is not None

    def test_algo_exit_orders_carry_order_class_algo_exit(self) -> None:
        engine = _engine()
        snapshot = _make_snapshot(20000.0, 100.0)
        signal = _make_signal()
        account = MagicMock()
        account.margin_ratio = 0.1
        account.drawdown_pct = 0.0
        account.equity = 2_000_000.0
        account.margin_available = 2_000_000.0
        account.positions = []
        engine.on_snapshot(snapshot, signal=signal, account=account)
        state = engine.get_state()
        assert len(state.positions) == 1
        snapshot2 = _make_snapshot(19500.0, 100.0)
        orders = engine.on_snapshot(snapshot2, signal=None, account=account)
        exit_orders = [o for o in orders if o.order_class == "algo_exit"]
        assert len(exit_orders) >= 1
        for order in exit_orders:
            assert order.order_class == "algo_exit"
            assert order.parent_position_id is not None

    def test_close_position_by_disaster_stop_removes_position(self) -> None:
        engine = _engine()
        snapshot = _make_snapshot(20000.0, 100.0)
        signal = _make_signal()
        account = MagicMock()
        account.margin_ratio = 0.1
        account.drawdown_pct = 0.0
        account.equity = 2_000_000.0
        account.margin_available = 2_000_000.0
        account.positions = []
        engine.on_snapshot(snapshot, signal=signal, account=account)
        state_before = engine.get_state()
        assert len(state_before.positions) == 1
        position_id = state_before.positions[0].position_id
        closed_pos = engine.close_position_by_disaster_stop(
            position_id=position_id,
            fill_price=19000.0,
            fill_timestamp=datetime.now(),
        )
        assert closed_pos is not None
        state_after = engine.get_state()
        assert len(state_after.positions) == 0

    def test_close_position_by_disaster_stop_unknown_id_returns_none(self) -> None:
        engine = _engine()
        result = engine.close_position_by_disaster_stop(
            position_id="unknown-id",
            fill_price=19000.0,
            fill_timestamp=datetime.now(),
        )
        assert result is None
