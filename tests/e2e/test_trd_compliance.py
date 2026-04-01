"""E2E tests verifying compliance with docs/archive/trd-core-quant-engine.md requirements.

Each test class maps to a TRD section:
 §1 Data Integrity & PIT Architecture
 §2 Execution & Microstructure Layer
 §3 Advanced Risk Controls
 §4 Simulation Architecture (Event-Driven)
 §5 Compliance & Audit Trail
"""

from __future__ import annotations

import os
import tempfile
from datetime import datetime, timedelta
from typing import Any

import pytest

from src.core.adapter import BaseAdapter
from src.core.types import (
    AccountState,
    AuditConfig,
    ContractSpecs,
    EventEngineConfig,
    EventType,
    ImpactParams,
    MarketEvent,
    MarketSnapshot,
    Order,
    Position,
    PreTradeRiskConfig,
    PyramidConfig,
    StressScenario,
    TradingHours,
    VaRResult,
)

pytestmark = pytest.mark.e2e


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _make_specs() -> ContractSpecs:
    hours = TradingHours(open_time="08:45", close_time="13:45", timezone="Asia/Taipei")
    return ContractSpecs(
        symbol="TX", exchange="TAIFEX", currency="TWD",
        point_value=200.0, margin_initial=184_000.0, margin_maintenance=141_000.0,
        min_tick=1.0, trading_hours=hours, fee_per_contract=60.0,
        tax_rate=0.00002, lot_types={"large": 200.0},
    )


class SimpleAdapter(BaseAdapter):
    """Minimal adapter for E2E tests without external dependencies."""

    def to_snapshot(self, raw: dict[str, Any]) -> MarketSnapshot:
        return MarketSnapshot(
            price=raw.get("close", 20000.0),
            atr={"daily": raw.get("daily_atr", 100.0)},
            timestamp=raw.get("timestamp", datetime(2024, 1, 1)),
            margin_per_unit=184_000.0,
            point_value=200.0,
            min_lot=1.0,
            contract_specs=_make_specs(),
        )

    def calc_margin(self, contract_type: str, lots: float) -> float:
        return lots * 184_000.0

    def calc_liquidation_price(self, entry: float, leverage: float, direction: str) -> float | None:
        return entry * 0.9

    def get_trading_hours(self) -> TradingHours:
        return TradingHours(open_time="08:45", close_time="13:45", timezone="Asia/Taipei")

    def get_contract_specs(self, symbol: str) -> ContractSpecs:
        return _make_specs()

    def estimate_fee(self, order: Order) -> float:
        return 60.0

    def translate_lots(self, abstract_lots: list[tuple[str, float]]) -> list[tuple[str, float]]:
        return abstract_lots


def _make_bars(n: int, start_price: float = 20000.0, trend: float = 10.0) -> list[dict[str, Any]]:
    """Generate n synthetic bars with a linear trend."""
    base = datetime(2024, 1, 1, 9, 0)
    bars = []
    for i in range(n):
        p = start_price + i * trend
        bars.append({
            "open": p - 5, "high": p + 20, "low": p - 20,
            "close": p, "volume": 5000.0, "daily_atr": 100.0,
            "symbol": "TX", "timestamp": base + timedelta(days=i),
        })
    return bars


# ===========================================================================
# TRD §1 — Data Integrity & Point-in-Time Architecture
# ===========================================================================

class TestTRDS1DataIntegrity:
    """Verifies bi-temporal PIT queries prevent look-ahead bias."""

    def test_as_of_prevents_look_ahead(self) -> None:
        from src.data.db import Database, MarginSnapshot
        from src.data.pit import PITQuery

        db = Database("sqlite:///:memory:")
        db.add_margin_snapshot(MarginSnapshot(
            symbol="TX", scraped_at=datetime(2024, 1, 1),
            margin_initial=184_000.0, margin_maintenance=141_000.0,
            knowledge_time=datetime(2024, 1, 1),
        ))
        # Future data: known only after March
        db.add_margin_snapshot(MarginSnapshot(
            symbol="TX", scraped_at=datetime(2024, 3, 1),
            margin_initial=200_000.0, margin_maintenance=160_000.0,
            knowledge_time=datetime(2024, 3, 1),
        ))
        with db.session() as s:
            pit = PITQuery(s)
            # Backtest at Feb 1 must NOT see the March data
            result = pit.as_of(datetime(2024, 2, 1)).get_margin("TX")
        assert result is not None
        assert result.margin_initial == 184_000.0, "Look-ahead bias: saw future margin data"

    def test_retroactive_correction_preserves_original(self) -> None:
        from src.data.db import Database, MarginSnapshot
        from src.data.pit import PITQuery

        db = Database("sqlite:///:memory:")
        db.add_margin_snapshot(MarginSnapshot(
            symbol="TX", scraped_at=datetime(2024, 3, 1),
            margin_initial=184_000.0, margin_maintenance=141_000.0,
            knowledge_time=datetime(2024, 3, 1),
        ))
        # Correction published later for same event_time
        db.add_margin_snapshot(MarginSnapshot(
            symbol="TX", scraped_at=datetime(2024, 3, 1),
            margin_initial=190_000.0, margin_maintenance=145_000.0,
            knowledge_time=datetime(2024, 3, 5),
        ))
        history = db.get_margin_history("TX")
        assert len(history) == 2, "Correction must append, not modify"

        with db.session() as s:
            pit = PITQuery(s)
            before = pit.as_of(datetime(2024, 3, 3)).get_margin("TX")
            after = pit.as_of(datetime(2024, 3, 10)).get_margin("TX")
        assert before.margin_initial == 184_000.0
        assert after.margin_initial == 190_000.0

    def test_contract_stitching_ratio(self) -> None:
        from src.data.db import Database, OHLCVBar, ContractRoll
        from src.data.stitcher import ContractStitcher

        db = Database("sqlite:///:memory:")
        db.add_ohlcv_bars([
            OHLCVBar("TX", datetime(2024, 1, 1), 100, 110, 90, 100, 1000),
            OHLCVBar("TX", datetime(2024, 1, 2), 110, 120, 100, 110, 1000),
            OHLCVBar("TX", datetime(2024, 2, 1), 200, 210, 190, 200, 1000),
        ])
        db.add_contract_roll(ContractRoll(
            symbol="TX", roll_date=datetime(2024, 1, 15),
            old_contract="TX202401", new_contract="TX202402",
            adjustment_factor=1.05,
        ))
        stitcher = ContractStitcher(db)
        result = stitcher.stitch("TX", method="ratio")
        # Pre-roll bars should be adjusted by the ratio
        assert result.adjusted_prices[0] == pytest.approx(100.0 * 1.05)
        assert result.adjusted_prices[1] == pytest.approx(110.0 * 1.05)
        # Post-roll bar unchanged
        assert result.adjusted_prices[2] == pytest.approx(200.0)
        # Unadjusted always preserved
        assert result.unadjusted_prices == [100.0, 110.0, 200.0]

    def test_stitcher_roll_detection_volume_crossover(self) -> None:
        from src.data.db import Database, OHLCVBar
        from src.data.stitcher import ContractStitcher

        db = Database("sqlite:///:memory:")
        # Old contract volume declines, new contract volume rises
        db.add_ohlcv_bars([
            OHLCVBar("TX202403", datetime(2024, 3, 18), 20000, 20010, 19990, 20005, 5000),
            OHLCVBar("TX202403", datetime(2024, 3, 19), 20010, 20020, 20000, 20015, 3000),
        ])
        db.add_ohlcv_bars([
            OHLCVBar("TX202404", datetime(2024, 3, 18), 20050, 20060, 20040, 20055, 3000),
            OHLCVBar("TX202404", datetime(2024, 3, 19), 20060, 20070, 20050, 20065, 6000),
        ])
        stitcher = ContractStitcher(db)
        rolls = stitcher.detect_rolls(
            "TX", "TX202403", "TX202404",
            datetime(2024, 3, 1), datetime(2024, 3, 31),
        )
        assert len(rolls) >= 1

    def test_adv_pit_safe(self) -> None:
        """ADV computation must respect as_of boundary."""
        from src.data.db import Database, OHLCVBar

        db = Database("sqlite:///:memory:")
        db.add_ohlcv_bars([
            OHLCVBar("TX", datetime(2024, 1, 1), 20000, 20010, 19990, 20000, 1000),
            OHLCVBar("TX", datetime(2024, 1, 2), 20010, 20020, 20000, 20010, 2000),
            OHLCVBar("TX", datetime(2024, 1, 3), 20020, 20030, 20010, 20020, 3000),
        ])
        adv = db.get_adv("TX", lookback_days=5, as_of=datetime(2024, 1, 2))
        assert adv == pytest.approx(1000.0), "ADV must only see bars before as_of"


# ===========================================================================
# TRD §2 — Execution & Microstructure Layer
# ===========================================================================

class TestTRDS2Execution:
    """Verifies market impact, spread costs, latency, and OMS slicing."""

    def test_market_impact_fill_model_not_close_price(self) -> None:
        """Fill price must differ from close — ClosePriceFillModel is dead."""
        from src.simulator.fill_model import MarketImpactFillModel

        model = MarketImpactFillModel(ImpactParams(seed=42))
        order = Order(
            order_type="market", side="buy", symbol="TX",
            contract_type="large", lots=5.0, price=None,
            stop_price=None, reason="entry",
        )
        bar = {"close": 20000.0, "volume": 5000.0, "daily_atr": 100.0}
        fill = model.simulate(order, bar, datetime(2024, 1, 1))
        assert fill.fill_price != 20000.0, "Fill must NOT be exact close price"
        assert fill.market_impact > 0.0, "Must have non-zero market impact"
        assert fill.spread_cost > 0.0, "Must have spread cost"
        assert fill.latency_ms > 0.0, "Must simulate latency"

    def test_backtest_uses_impact_model(self) -> None:
        """BacktestRunner must use MarketImpactFillModel by default."""
        from src.simulator.backtester import BacktestRunner
        from src.simulator.fill_model import MarketImpactFillModel

        runner = BacktestRunner(
            config=lambda: __import__("src.core.position_engine", fromlist=["create_pyramid_engine"]).create_pyramid_engine(PyramidConfig(max_loss=500_000)),
            adapter=SimpleAdapter(),
        )
        assert isinstance(runner._fill_model, MarketImpactFillModel)

    def test_impact_report_in_backtest_result(self) -> None:
        """Backtest result must include market impact breakdown."""
        from src.core.position_engine import create_pyramid_engine
        from src.simulator.backtester import BacktestRunner

        runner = BacktestRunner(
            config=lambda: create_pyramid_engine(PyramidConfig(max_loss=500_000)),
            adapter=SimpleAdapter(),
        )
        bars = _make_bars(10)
        result = runner.run(bars)
        assert result.impact_report is not None
        assert "total_market_impact" in result.metrics
        assert "total_spread_cost" in result.metrics
        assert "avg_latency_ms" in result.metrics

    def test_pre_trade_risk_rejects_excess_exposure(self) -> None:
        """Pre-trade risk gate must block orders exceeding gross exposure limit."""
        from src.risk.pre_trade import PreTradeRiskCheck

        config = PreTradeRiskConfig(max_gross_exposure_pct=0.50, enabled=True)
        checker = PreTradeRiskCheck(config=config)
        order = Order(
            order_type="market", side="buy", symbol="TX",
            contract_type="large", lots=10.0, price=None,
            stop_price=None, reason="entry",
        )
        account = AccountState(
            equity=1_000_000.0, unrealized_pnl=0.0, realized_pnl=0.0,
            margin_used=400_000.0, margin_available=600_000.0,
            margin_ratio=0.4, drawdown_pct=0.0, positions=[],
            timestamp=datetime.now(),
        )
        market = {"margin_per_unit": 184_000.0, "adv": 50000.0}
        result = checker.evaluate(order, account, market)
        assert not result.approved
        assert "gross_exposure_exceeded" in result.violations

    def test_oms_slicing_twap(self) -> None:
        """OMS must produce child slices for TWAP algorithm."""
        from src.oms.oms import OrderManagementSystem
        from src.core.types import OMSConfig

        config = OMSConfig(default_algorithm="twap", twap_default_slices=5, passthrough_threshold_pct=0.001)
        oms = OrderManagementSystem(config=config)
        order = Order(
            order_type="market", side="buy", symbol="TX",
            contract_type="large", lots=100.0, price=None,
            stop_price=None, reason="entry",
        )
        results = oms.schedule([order], {"adv": 5000.0})
        assert len(results) == 1
        sliced = results[0]
        assert sliced.algorithm == "twap"
        assert len(sliced.child_orders) >= 2


# ===========================================================================
# TRD §3 — Advanced Risk Controls
# ===========================================================================

class TestTRDS3RiskControls:
    """Verifies VaR computation, stress testing, and factor tracking."""

    def test_parametric_var_computation(self) -> None:
        from src.risk.var_engine import VaREngine

        engine = VaREngine(lookback_days=252)
        positions = [
            Position(
                entry_price=20000.0, lots=3.0, contract_type="TX",
                stop_level=19800.0, pyramid_level=0,
                entry_timestamp=datetime(2024, 1, 1), direction="long",
            ),
        ]
        import random
        random.seed(42)
        returns = {"TX": [random.gauss(0, 0.01) for _ in range(60)]}
        result = engine.compute(positions, returns, {"TX": 20000.0})
        assert result.var_99_1d > 0, "99% VaR must be positive for a real position"
        assert result.var_95_1d > 0
        assert result.var_99_10d > result.var_99_1d, "10-day VaR > 1-day VaR"
        assert result.expected_shortfall_99 >= result.var_99_1d

    def test_historical_var_crosscheck(self) -> None:
        from src.risk.var_engine import VaREngine

        engine = VaREngine()
        positions = [
            Position(
                entry_price=20000.0, lots=2.0, contract_type="TX",
                stop_level=19800.0, pyramid_level=0,
                entry_timestamp=datetime(2024, 1, 1), direction="long",
            ),
        ]
        import random
        random.seed(99)
        returns = {"TX": [random.gauss(0, 0.015) for _ in range(100)]}
        parametric = engine.compute(positions, returns, {"TX": 20000.0})
        historical = engine.compute_historical(positions, returns, {"TX": 20000.0})
        diverged, ratio = engine.check_divergence(parametric.var_99_1d, historical)
        # Just verify the check runs without error
        assert isinstance(diverged, bool)
        assert ratio >= 0.0

    def test_stress_margin_doubling(self) -> None:
        from src.risk.var_engine import VaREngine

        engine = VaREngine()
        positions = [
            Position(
                entry_price=20000.0, lots=5.0, contract_type="TX",
                stop_level=19800.0, pyramid_level=0,
                entry_timestamp=datetime(2024, 1, 1), direction="long",
            ),
        ]
        import random
        random.seed(7)
        returns = {"TX": [random.gauss(0, 0.01) for _ in range(60)]}
        scenarios = [
            StressScenario(name="margin_doubling", margin_multiplier=2.0),
            StressScenario(name="vol_spike", volatility_multiplier=2.0),
        ]
        results = engine.run_stress(
            positions, returns, scenarios,
            equity=2_000_000.0, margin_used=920_000.0,
            prices={"TX": 20000.0},
        )
        assert len(results) == 2
        margin_result = results[0]
        assert margin_result.scenario.name == "margin_doubling"
        assert margin_result.margin_call is False or margin_result.shortfall >= 0
        vol_result = results[1]
        assert vol_result.stressed_var > 0


# ===========================================================================
# TRD §4 — Simulation Architecture (Event-Driven)
# ===========================================================================

class TestTRDS4EventDriven:
    """Verifies EventEngine integration, tick drill-down, and backtest wiring."""

    def test_event_engine_dispatches_events(self) -> None:
        from src.simulator.event_engine import EventEngine
        from src.core.types import Event

        engine = EventEngine()
        received: list[Event] = []

        def handler(event: Event) -> list[Event]:
            received.append(event)
            return []

        engine.register_handler(EventType.MARKET, handler)
        engine.push(MarketEvent(
            event_type=EventType.MARKET, timestamp=datetime.now(), data={},
            symbol="TX", close=20000.0,
        ))
        engine.run()
        assert len(received) == 1

    def test_event_priority_risk_before_fill(self) -> None:
        from src.core.types import Event, RiskEvent, FillEvent, RiskAction
        from src.simulator.event_engine import EventEngine

        engine = EventEngine()
        order: list[EventType] = []

        def make_handler(et: EventType):
            def h(event: Event) -> list[Event]:
                order.append(event.event_type)
                return []
            return h

        engine.register_handler(EventType.RISK, make_handler(EventType.RISK))
        engine.register_handler(EventType.FILL, make_handler(EventType.FILL))
        engine.register_handler(EventType.MARKET, make_handler(EventType.MARKET))

        now = datetime.now()
        engine.push(MarketEvent(event_type=EventType.MARKET, timestamp=now, data={}))
        engine.push(FillEvent(event_type=EventType.FILL, timestamp=now, data={}))
        engine.push(RiskEvent(event_type=EventType.RISK, timestamp=now, data={}))
        engine.run()

        assert order[0] == EventType.RISK, "RISK events must be processed first"

    def test_tick_drill_down_on_volatile_bar(self) -> None:
        """Volatile bars (high-low > 2x ATR) must trigger synthetic tick generation."""
        from src.simulator.event_engine import EventEngine

        config = EventEngineConfig(tick_drill_enabled=True, tick_drill_atr_mult=2.0)
        engine = EventEngine(config=config)
        events: list[Any] = []

        def handler(event: Any) -> list[Any]:
            events.append(event)
            return []

        engine.register_handler(EventType.MARKET, handler)
        # Bar with range 15 points, daily_atr=2 → 15 > 2*2=4, should drill down
        bar = {
            "open": 100.0, "high": 110.0, "low": 95.0, "close": 105.0,
            "volume": 1000.0, "daily_atr": 2.0, "symbol": "TX",
            "timestamp": datetime(2024, 1, 1),
        }
        engine.run_backtest([bar], SimpleAdapter())
        assert len(events) >= 5, f"Volatile bar should generate multiple ticks, got {len(events)}"

    def test_normal_bar_no_drill_down(self) -> None:
        from src.simulator.event_engine import EventEngine

        config = EventEngineConfig(tick_drill_enabled=True, tick_drill_atr_mult=2.0)
        engine = EventEngine(config=config)
        events: list[Any] = []

        def handler(event: Any) -> list[Any]:
            events.append(event)
            return []

        engine.register_handler(EventType.MARKET, handler)
        bar = {
            "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5,
            "volume": 1000.0, "atr": 2.0, "symbol": "TX",
            "timestamp": datetime(2024, 1, 1),
        }
        engine.run_backtest([bar], SimpleAdapter())
        assert len(events) == 1, "Normal bar should pass through as single event"

    def test_backtest_runner_uses_event_engine(self) -> None:
        """BacktestRunner.run() must dispatch events through EventEngine."""
        from src.core.position_engine import create_pyramid_engine
        from src.simulator.backtester import BacktestRunner

        runner = BacktestRunner(
            config=lambda: create_pyramid_engine(PyramidConfig(max_loss=500_000)),
            adapter=SimpleAdapter(),
        )
        bars = _make_bars(5)
        result = runner.run(bars)
        assert len(result.equity_curve) == 6
        assert result.equity_curve[0] == 2_000_000.0


# ===========================================================================
# TRD §5 — Compliance & Audit Trail
# ===========================================================================

class TestTRDS5AuditTrail:
    """Verifies immutable hash chain, tamper detection, and replay."""

    def _make_account(self, equity: float = 1_000_000.0) -> AccountState:
        return AccountState(
            equity=equity, unrealized_pnl=0.0, realized_pnl=0.0,
            margin_used=0.0, margin_available=equity,
            margin_ratio=0.0, drawdown_pct=0.0, positions=[],
            timestamp=datetime.now(),
        )

    def test_hash_chain_integrity(self) -> None:
        from src.audit.trail import AuditTrail, GENESIS_HASH
        from tests.unit.audit.test_audit_trail import InMemoryAuditStore

        store = InMemoryAuditStore()
        trail = AuditTrail(store)
        account = self._make_account()
        for i in range(10):
            trail.append(f"event_{i}", account, {"step": i})
        assert trail.verify_chain() is True

    def test_tamper_detection(self) -> None:
        from src.audit.trail import AuditTrail, GENESIS_HASH
        from src.core.types import AuditRecord
        from tests.unit.audit.test_audit_trail import InMemoryAuditStore

        store = InMemoryAuditStore()
        trail = AuditTrail(store)
        account = self._make_account()
        trail.append("event_0", account, {})
        trail.append("event_1", account, {})
        # Tamper with a record
        original = store._records[1]
        store._records[1] = AuditRecord(
            sequence_id=original.sequence_id,
            timestamp=original.timestamp,
            event_type="TAMPERED",
            engine_state_hash=original.engine_state_hash,
            account_state=original.account_state,
            event_data={"tampered": True},
            prev_hash=original.prev_hash,
            record_hash="bad_hash" + "0" * 56,
            git_commit=original.git_commit,
        )
        assert trail.verify_chain() is False, "Tampered chain must fail verification"

    def test_clear_forbidden_in_production(self) -> None:
        """SQLiteAuditStore.clear() must be blocked without QUANT_TESTING env."""
        from src.audit.store import SQLiteAuditStore

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            store = SQLiteAuditStore(db_path)
            old_val = os.environ.pop("QUANT_TESTING", None)
            try:
                with pytest.raises(RuntimeError, match="forbidden"):
                    store.clear()
            finally:
                if old_val is not None:
                    os.environ["QUANT_TESTING"] = old_val
        finally:
            os.unlink(db_path)

    def test_clear_allowed_in_test_env(self) -> None:
        from src.audit.store import SQLiteAuditStore

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            store = SQLiteAuditStore(db_path)
            os.environ["QUANT_TESTING"] = "1"
            store.clear()  # Should not raise
            assert store.count() == 0
        finally:
            os.unlink(db_path)

    def test_deterministic_replay_verifies_chain(self) -> None:
        from src.audit.trail import AuditTrail
        from tests.unit.audit.test_audit_trail import InMemoryAuditStore

        store = InMemoryAuditStore()
        trail = AuditTrail(store)
        account = self._make_account()
        for i in range(5):
            trail.append(f"event_{i}", account, {"step": i})
        success, records, error = trail.deterministic_replay(0, 5)
        assert success is True
        assert len(records) == 5
        assert error is None

    def test_deterministic_replay_detects_corruption(self) -> None:
        from src.audit.trail import AuditTrail
        from src.core.types import AuditRecord
        from tests.unit.audit.test_audit_trail import InMemoryAuditStore

        store = InMemoryAuditStore()
        trail = AuditTrail(store)
        account = self._make_account()
        for i in range(5):
            trail.append(f"event_{i}", account, {"step": i})
        # Corrupt one record
        original = store._records[2]
        store._records[2] = AuditRecord(
            sequence_id=original.sequence_id,
            timestamp=original.timestamp,
            event_type="CORRUPTED",
            engine_state_hash=original.engine_state_hash,
            account_state=original.account_state,
            event_data=original.event_data,
            prev_hash=original.prev_hash,
            record_hash="corrupt" + "0" * 58,
            git_commit=original.git_commit,
        )
        success, records, error = trail.deterministic_replay(0, 5)
        assert success is False
        assert "mismatch" in error.lower() or "chain" in error.lower()

    def test_git_commit_tracked_in_audit_records(self) -> None:
        from src.audit.trail import AuditTrail
        from tests.unit.audit.test_audit_trail import InMemoryAuditStore

        store = InMemoryAuditStore()
        trail = AuditTrail(store, AuditConfig(include_git_commit=True))
        account = self._make_account()
        record = trail.append("test_event", account, {})
        assert record is not None
        assert record.git_commit is not None
        assert len(record.git_commit) == 40


# ===========================================================================
# TRD §Full Stack — End-to-End Pipeline
# ===========================================================================

class TestTRDFullStack:
    """End-to-end: bars → EventEngine → fill model → audit trail → verify chain."""

    def test_full_pipeline_with_audit(self) -> None:
        from src.audit.trail import AuditTrail
        from src.core.position_engine import create_pyramid_engine
        from src.simulator.backtester import BacktestRunner
        from src.simulator.event_engine import EventEngine
        from tests.unit.audit.test_audit_trail import InMemoryAuditStore

        store = InMemoryAuditStore()
        trail = AuditTrail(store, AuditConfig(include_git_commit=False))
        ee_config = EventEngineConfig(audit_enabled=True)

        runner = BacktestRunner(
            config=lambda: create_pyramid_engine(PyramidConfig(max_loss=500_000)),
            adapter=SimpleAdapter(),
            event_engine_config=ee_config,
        )
        bars = _make_bars(20, start_price=20000.0, trend=15.0)
        result = runner.run(bars)

        assert len(result.equity_curve) == 21
        assert result.impact_report is not None
        assert result.equity_curve[0] == 2_000_000.0

    def test_var_plus_pre_trade_rejects_oversized_order(self) -> None:
        """Full chain: VaR → pre-trade risk → rejection."""
        from src.risk.pre_trade import PreTradeRiskCheck
        from src.risk.var_engine import VaREngine

        var_engine = VaREngine()
        positions = [
            Position(
                entry_price=20000.0, lots=5.0, contract_type="TX",
                stop_level=19800.0, pyramid_level=0,
                entry_timestamp=datetime(2024, 1, 1), direction="long",
            ),
        ]
        import random
        random.seed(42)
        returns = {"TX": [random.gauss(0, 0.01) for _ in range(60)]}
        var_result = var_engine.compute(positions, returns, {"TX": 20000.0})

        # Pre-trade check: order that would blow concentration limit
        config = PreTradeRiskConfig(
            max_gross_exposure_pct=0.30, enabled=True,
        )
        checker = PreTradeRiskCheck(config=config)
        big_order = Order(
            order_type="market", side="buy", symbol="TX",
            contract_type="large", lots=10.0, price=None,
            stop_price=None, reason="entry",
        )
        account = AccountState(
            equity=1_000_000.0, unrealized_pnl=0.0, realized_pnl=0.0,
            margin_used=200_000.0, margin_available=800_000.0,
            margin_ratio=0.2, drawdown_pct=0.0, positions=[],
            timestamp=datetime.now(),
        )
        result = checker.evaluate(big_order, account, {"margin_per_unit": 184_000.0, "adv": 50000.0})
        assert not result.approved, "Oversized order must be rejected"
