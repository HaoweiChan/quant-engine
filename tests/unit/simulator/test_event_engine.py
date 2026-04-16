"""Tests for EventEngine event-driven simulation."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from src.core.adapter import BaseAdapter
from src.core.types import (
    ContractSpecs,
    Event,
    EventEngineConfig,
    EventType,
    MarketEvent,
    Order,
    OrderEvent,
    TradingHours,
)
from src.simulator.event_engine import EventEngine, generate_synthetic_ticks


class DummyAdapter(BaseAdapter):
    def to_snapshot(self, bar: dict[str, Any]) -> Any:
        class Snapshot:
            def __init__(self):
                self.price = bar.get("close", 100.0)
                self.atr = {"daily": bar.get("atr", 1.0)}
                self.margin_per_unit = 100.0
                self.point_value = 50.0
                self.timestamp = bar.get("timestamp", datetime.now())

        return Snapshot()

    def calc_margin(self, contract_type: str, lots: float) -> float:
        return lots * 100.0

    def calc_liquidation_price(self, entry: float, leverage: float, direction: str) -> float | None:
        return entry * 0.9

    def get_trading_hours(self) -> TradingHours:
        return TradingHours(open_time="09:00", close_time="15:00", timezone="Asia/Taipei")

    def get_contract_specs(self, symbol: str) -> ContractSpecs:
        return ContractSpecs(
            symbol=symbol,
            exchange="TEST",
            currency="USD",
            point_value=50.0,
            margin_initial=1000.0,
            margin_maintenance=500.0,
            min_tick=0.1,
            trading_hours=TradingHours(
                open_time="09:00", close_time="15:00", timezone="Asia/Taipei"
            ),
            fee_per_contract=1.0,
            tax_rate=0.0,
            lot_types={"standard": 1.0},
        )

    def estimate_fee(self, order: Order) -> float:
        return 1.0

    def translate_lots(self, abstract_lots: list[tuple[str, float]]) -> list[tuple[str, float]]:
        return abstract_lots


class TestEventEngineCore:
    def test_register_handler(self):
        engine = EventEngine()
        calls: list[Event] = []

        def handler(event: Event) -> list[Event]:
            calls.append(event)
            return []

        engine.register_handler(EventType.MARKET, handler)
        engine.push(MarketEvent(event_type=EventType.MARKET, timestamp=datetime.now(), data={}))
        engine.run()

        assert len(calls) == 1

    def test_event_dispatched_to_correct_handler(self):
        engine = EventEngine()
        market_calls: list[Event] = []
        order_calls: list[Event] = []

        def market_handler(event: Event) -> list[Event]:
            market_calls.append(event)
            return []

        def order_handler(event: Event) -> list[Event]:
            order_calls.append(event)
            return []

        engine.register_handler(EventType.MARKET, market_handler)
        engine.register_handler(EventType.ORDER, order_handler)

        engine.push(MarketEvent(event_type=EventType.MARKET, timestamp=datetime.now(), data={}))
        engine.push(OrderEvent(event_type=EventType.ORDER, timestamp=datetime.now(), data={}))
        engine.run()

        assert len(market_calls) == 1
        assert len(order_calls) == 1

    def test_queue_drains_completely(self):
        engine = EventEngine()
        calls: list[Event] = []

        def handler(event: Event) -> list[Event]:
            calls.append(event)
            return []

        engine.register_handler(EventType.MARKET, handler)

        for i in range(5):
            engine.push(
                MarketEvent(event_type=EventType.MARKET, timestamp=datetime.now(), data={"i": i})
            )
        engine.run()

        assert len(calls) == 5
        assert len(engine._queue) == 0

    def test_empty_queue_termination(self):
        engine = EventEngine()
        engine.run()
        assert True


class TestEventChaining:
    def test_handler_returns_events_pushed_to_queue(self):
        engine = EventEngine()
        results: list[Event] = []
        call_count = 0

        def market_handler(event: Event) -> list[Event]:
            nonlocal call_count
            call_count += 1
            if call_count > 10:
                return []
            return [OrderEvent(event_type=EventType.ORDER, timestamp=event.timestamp, data={})]

        def result_handler(event: Event) -> list[Event]:
            results.append(event)
            return []

        engine.register_handler(EventType.MARKET, market_handler)
        engine.register_handler(EventType.ORDER, result_handler)

        engine.push(MarketEvent(event_type=EventType.MARKET, timestamp=datetime.now(), data={}))
        engine.run()

        assert len(results) == 1


class TestEventPriority:
    def test_priority_ordering_risk_first(self):
        engine = EventEngine()
        order: list[EventType] = []

        def make_handler(event_type: EventType) -> callable:
            def handler(event: Event) -> list[Event]:
                order.append(event.event_type)
                return []

            return handler

        engine.register_handler(EventType.RISK, make_handler(EventType.RISK))
        engine.register_handler(EventType.FILL, make_handler(EventType.FILL))
        engine.register_handler(EventType.MARKET, make_handler(EventType.MARKET))
        engine.register_handler(EventType.SIGNAL, make_handler(EventType.SIGNAL))
        engine.register_handler(EventType.ORDER, make_handler(EventType.ORDER))
        engine.register_handler(EventType.AUDIT, make_handler(EventType.AUDIT))

        for et in [
            EventType.AUDIT,
            EventType.ORDER,
            EventType.SIGNAL,
            EventType.MARKET,
            EventType.FILL,
            EventType.RISK,
        ]:
            engine.push(Event(event_type=et, timestamp=datetime.now(), data={}))

        engine.run()

        assert order[0] == EventType.RISK
        assert order[-1] == EventType.AUDIT


class TestTickDrillDown:
    def test_synthetic_ticks_generation(self):
        ticks = generate_synthetic_ticks(
            open_price=100.0,
            high=105.0,
            low=95.0,
            close=102.0,
            volume=1000.0,
            atr=2.0,
            n_ticks=5,
        )

        assert len(ticks) == 4
        assert all("open" in t and "high" in t and "low" in t and "close" in t for t in ticks)
        assert ticks[0]["open"] == 100.0
        assert ticks[-1]["close"] == 102.0

    def test_synthetic_ticks_constrained_to_ohlcrange(self):
        ticks = generate_synthetic_ticks(
            open_price=100.0,
            high=105.0,
            low=95.0,
            close=102.0,
            volume=1000.0,
            atr=2.0,
            n_ticks=10,
        )

        for tick in ticks:
            assert tick["low"] >= 95.0
            assert tick["high"] <= 105.0

    def test_volatile_bar_triggers_drill_down(self):
        engine = EventEngine(
            config=EventEngineConfig(tick_drill_enabled=True, tick_drill_atr_mult=2.0)
        )
        events: list[Event] = []

        def handler(event: Event) -> list[Event]:
            events.append(event)
            return []

        engine.register_handler(EventType.MARKET, handler)

        bars = [
            {
                "open": 100.0,
                "high": 110.0,
                "low": 95.0,
                "close": 105.0,
                "volume": 1000.0,
                "atr": 2.0,
                "symbol": "TEST",
            },
        ]

        result = engine.run_backtest(bars, DummyAdapter())

        assert len(events) >= 5

    def test_normal_bar_passthrough(self):
        engine = EventEngine(
            config=EventEngineConfig(tick_drill_enabled=True, tick_drill_atr_mult=2.0)
        )
        events: list[Event] = []

        def handler(event: Event) -> list[Event]:
            events.append(event)
            return []

        engine.register_handler(EventType.MARKET, handler)

        bars = [
            {
                "open": 100.0,
                "high": 101.0,
                "low": 99.0,
                "close": 100.5,
                "volume": 1000.0,
                "atr": 2.0,
                "symbol": "TEST",
            },
        ]

        result = engine.run_backtest(bars, DummyAdapter())

        assert len(events) == 1

    def test_disabled_drill_down(self):
        engine = EventEngine(
            config=EventEngineConfig(tick_drill_enabled=False, tick_drill_atr_mult=2.0)
        )
        events: list[Event] = []

        def handler(event: Event) -> list[Event]:
            events.append(event)
            return []

        engine.register_handler(EventType.MARKET, handler)

        bars = [
            {
                "open": 100.0,
                "high": 110.0,
                "low": 95.0,
                "close": 105.0,
                "volume": 1000.0,
                "atr": 2.0,
                "symbol": "TEST",
            },
        ]

        result = engine.run_backtest(bars, DummyAdapter())

        assert len(events) == 1


class TestEventEngineConfig:
    def test_default_config(self):
        engine = EventEngine()
        assert engine.config is not None
        assert engine.config.tick_drill_enabled is True
        assert engine.config.tick_drill_atr_mult == 2.0

    def test_custom_config(self):
        engine = EventEngine(
            config=EventEngineConfig(tick_drill_enabled=False, latency_delay_ms=50.0)
        )
        assert engine.config.tick_drill_enabled is False
        assert engine.config.latency_delay_ms == 50.0


class TestGenerateSyntheticTicks:
    def test_flat_bar_returns_single_tick(self):
        ticks = generate_synthetic_ticks(100.0, 100.0, 100.0, 100.0, 1000.0, 0.0, 5)
        assert len(ticks) == 1

    def test_n_ticks_parameter(self):
        ticks = generate_synthetic_ticks(100.0, 105.0, 95.0, 102.0, 1000.0, 2.0, n_ticks=20)
        assert len(ticks) == 19
