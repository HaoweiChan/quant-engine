"""Tests for PreTradeRiskCheck and Position Engine pre-trade gating."""
from __future__ import annotations

from datetime import datetime

from src.core.position_engine import create_pyramid_engine
from src.core.types import (
    AccountState,
    ContractSpecs,
    MarketSignal,
    MarketSnapshot,
    Order,
    PreTradeRiskConfig,
    PyramidConfig,
    TradingHours,
)
from src.risk.pre_trade import PreTradeRiskCheck

TS = datetime(2026, 1, 15, 9, 0, 0)
HOURS = TradingHours(open_time="08:45", close_time="13:45", timezone="Asia/Taipei")
SPECS = ContractSpecs(
    symbol="TX", exchange="TAIFEX", currency="TWD",
    point_value=200.0, margin_initial=184000.0, margin_maintenance=141000.0,
    min_tick=1.0, trading_hours=HOURS, fee_per_contract=20.0, tax_rate=0.00002,
    lot_types={"large": 200.0, "small": 50.0},
)


def _make_order(lots: float = 10.0) -> Order:
    return Order(
        order_type="market", side="buy", symbol="TX", contract_type="large",
        lots=lots, price=None, stop_price=None, reason="entry",
    )


def _make_account(equity: float = 10_000_000.0, margin_used: float = 1_000_000.0) -> AccountState:
    return AccountState(
        equity=equity, unrealized_pnl=0.0, realized_pnl=0.0,
        margin_used=margin_used, margin_available=equity - margin_used,
        margin_ratio=margin_used / equity if equity > 0 else 0.0,
        drawdown_pct=0.0, positions=[], timestamp=TS,
    )


class TestPreTradeRiskCheck:
    def test_within_limits_approved(self) -> None:
        check = PreTradeRiskCheck(PreTradeRiskConfig(max_gross_exposure_pct=0.80))
        order = _make_order(lots=1)
        account = _make_account(equity=10_000_000, margin_used=1_000_000)
        market = {"margin_per_unit": 184000.0, "adv": 50000.0}
        result = check.evaluate(order, account, market)
        assert result.approved is True
        assert len(result.violations) == 0

    def test_gross_exposure_breach(self) -> None:
        check = PreTradeRiskCheck(PreTradeRiskConfig(max_gross_exposure_pct=0.50))
        order = _make_order(lots=100)
        account = _make_account(equity=10_000_000, margin_used=4_000_000)
        market = {"margin_per_unit": 184000.0, "adv": 50000.0}
        result = check.evaluate(order, account, market)
        assert result.approved is False
        assert "gross_exposure_exceeded" in result.violations

    def test_adv_participation_breach(self) -> None:
        check = PreTradeRiskCheck(PreTradeRiskConfig(max_adv_participation_pct=0.05))
        order = _make_order(lots=5000)
        account = _make_account()
        market = {"margin_per_unit": 184000.0, "adv": 50000.0}
        result = check.evaluate(order, account, market)
        assert result.approved is False
        assert "adv_participation_exceeded" in result.violations

    def test_disabled_always_approves(self) -> None:
        check = PreTradeRiskCheck(PreTradeRiskConfig(enabled=False))
        order = _make_order(lots=999999)
        account = _make_account(equity=1)
        market = {"margin_per_unit": 184000.0, "adv": 1.0}
        result = check.evaluate(order, account, market)
        assert result.approved is True


class TestPositionEngineGating:
    def _make_snapshot(self, price: float = 20000.0) -> MarketSnapshot:
        return MarketSnapshot(
            price=price, atr={"daily": 300.0}, timestamp=TS,
            margin_per_unit=184000.0, point_value=200.0, min_lot=1.0,
            contract_specs=SPECS,
        )

    def _make_signal(self) -> MarketSignal:
        return MarketSignal(
            timestamp=TS, direction=0.8, direction_conf=0.9,
            regime="trending", trend_strength=0.7, vol_forecast=300.0,
            suggested_stop_atr_mult=None, suggested_add_atr_mult=None,
            model_version="v1", confidence_valid=True,
        )

    def test_none_check_backward_compatible(self) -> None:
        config = PyramidConfig(max_loss=500000)
        engine = create_pyramid_engine(config, pre_trade_check=None)
        snapshot = self._make_snapshot()
        signal = self._make_signal()
        account = _make_account()
        orders = engine.on_snapshot(snapshot, signal, account)
        assert any(o.reason == "entry" for o in orders)

    def test_factory_accepts_pre_trade_check(self) -> None:
        config = PyramidConfig(max_loss=500000)
        check = PreTradeRiskCheck(PreTradeRiskConfig(enabled=False))
        engine = create_pyramid_engine(config, pre_trade_check=check)
        assert engine._pre_trade_check is check

    def test_stop_orders_have_immediate_urgency(self) -> None:
        config = PyramidConfig(max_loss=500000)
        engine = create_pyramid_engine(config)
        snapshot = self._make_snapshot()
        signal = self._make_signal()
        account = _make_account()
        engine.on_snapshot(snapshot, signal, account)
        low_snap = self._make_snapshot(price=19000.0)
        orders = engine.on_snapshot(low_snap, None, account)
        stop_orders = [o for o in orders if "stop" in o.reason]
        for o in stop_orders:
            assert o.metadata.get("urgency") == "immediate"

    def test_entry_orders_have_normal_urgency(self) -> None:
        config = PyramidConfig(max_loss=500000)
        engine = create_pyramid_engine(config)
        snapshot = self._make_snapshot()
        signal = self._make_signal()
        account = _make_account()
        orders = engine.on_snapshot(snapshot, signal, account)
        entry_orders = [o for o in orders if o.reason == "entry"]
        for o in entry_orders:
            assert o.metadata.get("urgency") == "normal"
