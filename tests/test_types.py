from datetime import UTC, datetime

import pytest

from src.core.types import (
    AccountState,
    ContractSpecs,
    MarketSignal,
    MarketSnapshot,
    Order,
    Position,
    PyramidConfig,
    RiskAction,
    TradingHours,
)

# -- ContractSpecs --

class TestContractSpecs:
    def _hours(self) -> TradingHours:
        return TradingHours(open_time="09:00", close_time="16:00", timezone="UTC")

    def test_valid_construction(self) -> None:
        cs = ContractSpecs(
            symbol="TXF", exchange="TAIFEX", currency="TWD",
            point_value=200.0, margin_initial=184000.0, margin_maintenance=141000.0,
            min_tick=1.0, trading_hours=self._hours(), fee_per_contract=60.0,
            tax_rate=0.00002, lot_types={"large": 200.0},
        )
        assert cs.symbol == "TXF"

    def test_zero_margin_initial(self) -> None:
        with pytest.raises(ValueError, match="margin_initial"):
            ContractSpecs(
                symbol="TXF", exchange="TAIFEX", currency="TWD",
                point_value=200.0, margin_initial=0.0, margin_maintenance=141000.0,
                min_tick=1.0, trading_hours=self._hours(), fee_per_contract=60.0,
                tax_rate=0.00002, lot_types={"large": 200.0},
            )

    def test_negative_margin_maintenance(self) -> None:
        with pytest.raises(ValueError, match="margin_maintenance"):
            ContractSpecs(
                symbol="TXF", exchange="TAIFEX", currency="TWD",
                point_value=200.0, margin_initial=184000.0, margin_maintenance=-1.0,
                min_tick=1.0, trading_hours=self._hours(), fee_per_contract=60.0,
                tax_rate=0.00002, lot_types={"large": 200.0},
            )

    def test_empty_lot_types(self) -> None:
        with pytest.raises(ValueError, match="lot_types"):
            ContractSpecs(
                symbol="TXF", exchange="TAIFEX", currency="TWD",
                point_value=200.0, margin_initial=184000.0, margin_maintenance=141000.0,
                min_tick=1.0, trading_hours=self._hours(), fee_per_contract=60.0,
                tax_rate=0.00002, lot_types={},
            )


# -- MarketSnapshot --

class TestMarketSnapshot:
    def _specs(self) -> ContractSpecs:
        hours = TradingHours(open_time="09:00", close_time="16:00", timezone="UTC")
        return ContractSpecs(
            symbol="TXF", exchange="TAIFEX", currency="TWD",
            point_value=200.0, margin_initial=184000.0, margin_maintenance=141000.0,
            min_tick=1.0, trading_hours=hours, fee_per_contract=60.0,
            tax_rate=0.00002, lot_types={"large": 200.0},
        )

    def test_valid_construction(self) -> None:
        snap = MarketSnapshot(
            price=20000.0, atr={"daily": 100.0},
            timestamp=datetime.now(UTC), margin_per_unit=184000.0,
            point_value=200.0, min_lot=1.0, contract_specs=self._specs(),
        )
        assert snap.price == 20000.0

    def test_zero_price(self) -> None:
        with pytest.raises(ValueError, match="price"):
            MarketSnapshot(
                price=0.0, atr={"daily": 100.0},
                timestamp=datetime.now(UTC), margin_per_unit=184000.0,
                point_value=200.0, min_lot=1.0, contract_specs=self._specs(),
            )

    def test_negative_price(self) -> None:
        with pytest.raises(ValueError, match="price"):
            MarketSnapshot(
                price=-5.0, atr={"daily": 100.0},
                timestamp=datetime.now(UTC), margin_per_unit=184000.0,
                point_value=200.0, min_lot=1.0, contract_specs=self._specs(),
            )

    def test_missing_daily_atr(self) -> None:
        with pytest.raises(ValueError, match="daily"):
            MarketSnapshot(
                price=20000.0, atr={"hourly": 50.0},
                timestamp=datetime.now(UTC), margin_per_unit=184000.0,
                point_value=200.0, min_lot=1.0, contract_specs=self._specs(),
            )


# -- MarketSignal --

class TestMarketSignal:
    def _base_kwargs(self) -> dict:
        return dict(
            timestamp=datetime.now(UTC), direction=0.5, direction_conf=0.7,
            regime="trending", trend_strength=0.6, vol_forecast=120.0,
            suggested_stop_atr_mult=None, suggested_add_atr_mult=None,
            model_version="v1", confidence_valid=True,
        )

    def test_valid_construction(self) -> None:
        sig = MarketSignal(**self._base_kwargs())
        assert sig.direction == 0.5

    def test_direction_too_high(self) -> None:
        kw = self._base_kwargs()
        kw["direction"] = 1.5
        with pytest.raises(ValueError, match="direction"):
            MarketSignal(**kw)

    def test_direction_too_low(self) -> None:
        kw = self._base_kwargs()
        kw["direction"] = -1.5
        with pytest.raises(ValueError, match="direction"):
            MarketSignal(**kw)

    def test_direction_conf_too_high(self) -> None:
        kw = self._base_kwargs()
        kw["direction_conf"] = 1.1
        with pytest.raises(ValueError, match="direction_conf"):
            MarketSignal(**kw)

    def test_direction_conf_negative(self) -> None:
        kw = self._base_kwargs()
        kw["direction_conf"] = -0.1
        with pytest.raises(ValueError, match="direction_conf"):
            MarketSignal(**kw)

    def test_invalid_regime(self) -> None:
        kw = self._base_kwargs()
        kw["regime"] = "unknown_regime"
        with pytest.raises(ValueError, match="regime"):
            MarketSignal(**kw)


# -- Order --

class TestOrder:
    def test_valid_market_order(self) -> None:
        order = Order(
            order_type="market", side="buy", symbol="TXF", contract_type="large",
            lots=3.0, price=None, stop_price=None, reason="entry",
        )
        assert order.lots == 3.0

    def test_zero_lots(self) -> None:
        with pytest.raises(ValueError, match="lots"):
            Order(
                order_type="market", side="buy", symbol="TXF", contract_type="large",
                lots=0.0, price=None, stop_price=None, reason="entry",
            )

    def test_negative_lots(self) -> None:
        with pytest.raises(ValueError, match="lots"):
            Order(
                order_type="market", side="buy", symbol="TXF", contract_type="large",
                lots=-1.0, price=None, stop_price=None, reason="entry",
            )

    def test_stop_order_missing_stop_price(self) -> None:
        with pytest.raises(ValueError, match="stop_price"):
            Order(
                order_type="stop", side="sell", symbol="TXF", contract_type="large",
                lots=1.0, price=None, stop_price=None, reason="stop_loss",
            )

    def test_market_order_with_price(self) -> None:
        with pytest.raises(ValueError, match="price must be None"):
            Order(
                order_type="market", side="buy", symbol="TXF", contract_type="large",
                lots=1.0, price=20000.0, stop_price=None, reason="entry",
            )


# -- Position --

class TestPosition:
    def test_valid_position(self) -> None:
        pos = Position(
            entry_price=20000.0, lots=3.0, contract_type="large",
            stop_level=19850.0, pyramid_level=0,
            entry_timestamp=datetime.now(UTC),
        )
        assert pos.entry_price == 20000.0


# -- AccountState --

class TestAccountState:
    def test_valid_account(self) -> None:
        acc = AccountState(
            equity=2_000_000.0, unrealized_pnl=50000.0, realized_pnl=10000.0,
            margin_used=400000.0, margin_available=1600000.0, margin_ratio=0.2,
            drawdown_pct=0.05, positions=[], timestamp=datetime.now(UTC),
        )
        assert acc.drawdown_pct == 0.05

    def test_drawdown_too_high(self) -> None:
        with pytest.raises(ValueError, match="drawdown_pct"):
            AccountState(
                equity=2_000_000.0, unrealized_pnl=0.0, realized_pnl=0.0,
                margin_used=0.0, margin_available=2_000_000.0, margin_ratio=0.0,
                drawdown_pct=1.5, positions=[], timestamp=datetime.now(UTC),
            )

    def test_drawdown_negative(self) -> None:
        with pytest.raises(ValueError, match="drawdown_pct"):
            AccountState(
                equity=2_000_000.0, unrealized_pnl=0.0, realized_pnl=0.0,
                margin_used=0.0, margin_available=2_000_000.0, margin_ratio=0.0,
                drawdown_pct=-0.1, positions=[], timestamp=datetime.now(UTC),
            )


# -- PyramidConfig --

class TestPyramidConfig:
    def test_valid_default_config(self) -> None:
        cfg = PyramidConfig(max_loss=500_000.0)
        assert cfg.max_levels == 4
        assert len(cfg.lot_schedule) == cfg.max_levels
        assert len(cfg.add_trigger_atr) == cfg.max_levels - 1

    def test_zero_max_loss(self) -> None:
        with pytest.raises(ValueError, match="max_loss"):
            PyramidConfig(max_loss=0.0)

    def test_negative_max_loss(self) -> None:
        with pytest.raises(ValueError, match="max_loss"):
            PyramidConfig(max_loss=-100.0)

    def test_lot_schedule_too_short(self) -> None:
        with pytest.raises(ValueError, match="lot_schedule"):
            PyramidConfig(max_loss=500_000.0, lot_schedule=[[3, 4], [2, 0]])

    def test_add_trigger_atr_wrong_length(self) -> None:
        with pytest.raises(ValueError, match="add_trigger_atr"):
            PyramidConfig(max_loss=500_000.0, add_trigger_atr=[4.0, 8.0])


# -- RiskAction --

class TestRiskAction:
    def test_member_count(self) -> None:
        assert len(RiskAction) == 4

    def test_members_exist(self) -> None:
        assert RiskAction.NORMAL.value == "normal"
        assert RiskAction.REDUCE_HALF.value == "reduce_half"
        assert RiskAction.HALT_NEW_ENTRIES.value == "halt_new_entries"
        assert RiskAction.CLOSE_ALL.value == "close_all"
