"""Tests for TaifexAdapter: config loading, snapshot, lots, fees, margin resolution."""
from __future__ import annotations

from datetime import UTC, datetime

import pytest

from src.adapters.taifex import TaifexAdapter
from src.core.types import Order
from src.data.db import Database, MarginSnapshot
from src.data.feature_store import FeatureStore


@pytest.fixture
def adapter() -> TaifexAdapter:
    return TaifexAdapter()


class TestConfigLoading:
    def test_constructs_successfully(self, adapter: TaifexAdapter) -> None:
        assert adapter is not None

    def test_get_contract_specs_tx(self, adapter: TaifexAdapter) -> None:
        specs = adapter.get_contract_specs("TX")
        assert specs.symbol == "TX"
        assert specs.exchange == "TAIFEX"
        assert specs.point_value == 200.0
        assert specs.margin_initial == 184000.0

    def test_get_contract_specs_mtx(self, adapter: TaifexAdapter) -> None:
        specs = adapter.get_contract_specs("MTX")
        assert specs.symbol == "MTX"
        assert specs.point_value == 50.0

    def test_get_contract_specs_tmf(self, adapter: TaifexAdapter) -> None:
        specs = adapter.get_contract_specs("TMF")
        assert specs.symbol == "TMF"
        assert specs.point_value == 2000.0


class TestSnapshot:
    def test_to_snapshot_valid(self, adapter: TaifexAdapter) -> None:
        raw = {
            "price": 20000.0,
            "symbol": "TX",
            "daily_atr": 150.0,
            "timestamp": datetime(2024, 1, 2, 9, 0, tzinfo=UTC),
        }
        snap = adapter.to_snapshot(raw)
        assert snap.price == 20000.0
        assert snap.atr["daily"] == 150.0
        assert snap.contract_specs.symbol == "TX"


class TestLotTranslation:
    def test_translate_large(self, adapter: TaifexAdapter) -> None:
        result = adapter.translate_lots([("large", 3.0)])
        assert result == [("TX", 3.0)]

    def test_translate_small(self, adapter: TaifexAdapter) -> None:
        result = adapter.translate_lots([("small", 4.0)])
        assert result == [("MTX", 4.0)]


class TestTradingHours:
    def test_day_session(self, adapter: TaifexAdapter) -> None:
        hours = adapter.get_trading_hours()
        assert hours.open_time == "08:45"
        assert hours.close_time == "13:45"
        assert hours.timezone == "Asia/Taipei"


class TestFeeEstimation:
    def test_market_order_fee(self, adapter: TaifexAdapter) -> None:
        order = Order(
            order_type="market", side="buy", symbol="TX",
            contract_type="large", lots=1.0, price=None,
            stop_price=None, reason="entry",
        )
        fee = adapter.estimate_fee(order)
        assert fee == 60.0

    def test_limit_order_fee_with_tax(self, adapter: TaifexAdapter) -> None:
        order = Order(
            order_type="limit", side="sell", symbol="TX",
            contract_type="large", lots=2.0, price=20000.0,
            stop_price=None, reason="exit",
        )
        fee = adapter.estimate_fee(order)
        commission = 60.0 * 2
        tax = 20000.0 * 200.0 * 2.0 * 0.00002
        assert fee == pytest.approx(commission + tax)


class TestMargin:
    def test_calc_margin(self, adapter: TaifexAdapter) -> None:
        margin = adapter.calc_margin("large", 2.0)
        assert margin == 184000.0 * 2

    def test_liquidation_price_none(self, adapter: TaifexAdapter) -> None:
        result = adapter.calc_liquidation_price(20000.0, 10.0, "long")
        assert result is None


class TestMarginResolution:
    """Test DB → config fallback chain for margin values."""

    def test_no_db_uses_config(self) -> None:
        adapter = TaifexAdapter(db=None)
        specs = adapter.get_contract_specs("TX")
        assert specs.margin_initial == 184000.0

    def test_db_with_no_data_uses_config(self) -> None:
        db = Database(url="sqlite:///:memory:")
        adapter = TaifexAdapter(db=db)
        specs = adapter.get_contract_specs("TX")
        assert specs.margin_initial == 184000.0

    def test_db_margin_overrides_config(self) -> None:
        db = Database(url="sqlite:///:memory:")
        db.add_margin_snapshot(MarginSnapshot(
            symbol="TX",
            scraped_at=datetime(2024, 6, 1, tzinfo=UTC),
            margin_initial=454000.0,
            margin_maintenance=348000.0,
            source="taifex_web",
        ))
        adapter = TaifexAdapter(db=db)
        specs = adapter.get_contract_specs("TX")
        assert specs.margin_initial == 454000.0
        assert specs.margin_maintenance == 348000.0

    def test_latest_db_margin_wins(self) -> None:
        db = Database(url="sqlite:///:memory:")
        db.add_margin_snapshot(MarginSnapshot(
            symbol="TX",
            scraped_at=datetime(2024, 1, 1, tzinfo=UTC),
            margin_initial=300000.0,
            margin_maintenance=250000.0,
            source="taifex_web",
        ))
        db.add_margin_snapshot(MarginSnapshot(
            symbol="TX",
            scraped_at=datetime(2024, 6, 1, tzinfo=UTC),
            margin_initial=454000.0,
            margin_maintenance=348000.0,
            source="taifex_web",
        ))
        adapter = TaifexAdapter(db=db)
        specs = adapter.get_contract_specs("TX")
        assert specs.margin_initial == 454000.0


class TestPluginRegistration:
    def test_registers_plugin(self) -> None:
        store = FeatureStore()
        TaifexAdapter(feature_store=store)
        assert len(store._plugins) == 1
