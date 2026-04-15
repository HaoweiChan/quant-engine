"""Tests for automatic contract roller."""
from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from src.data.spread_monitor import SpreadMonitor
from src.execution.contract_roller import (
    ContractRoller,
    PositionToRoll,
    RollRecord,
    RollStatus,
    ensure_schema,
    load_roll_history,
    persist_roll,
)


@pytest.fixture
def monitor() -> SpreadMonitor:
    return SpreadMonitor(window_size=20)


@pytest.fixture
def roller(monitor: SpreadMonitor) -> ContractRoller:
    return ContractRoller(spread_monitor=monitor)


def _pos(
    symbol: str = "TX",
    holding_period: str = "swing",
    side: str = "long",
    lots: float = 1.0,
) -> PositionToRoll:
    return PositionToRoll(
        symbol=symbol,
        session_id="sess-001",
        strategy_slug="swing/trend_following/vol_managed_bnh",
        holding_period=holding_period,
        side=side,
        lots=lots,
        entry_price=20000.0,
        contract_code="TXFR1",
    )


class TestRollDecision:
    def test_short_term_never_rolls(self, roller: ContractRoller) -> None:
        pos = _pos(holding_period="short_term")
        decision = roller.check_position(pos, as_of=date(2024, 3, 19))
        assert decision.status == RollStatus.NOT_NEEDED

    def test_swing_not_in_window(self, roller: ContractRoller) -> None:
        # Settlement is Mar 20; T-15 => not in window
        pos = _pos(holding_period="swing")
        decision = roller.check_position(pos, as_of=date(2024, 3, 5))
        assert decision.status == RollStatus.NOT_NEEDED
        assert decision.days_to_settlement == 15

    def test_swing_in_window(self, roller: ContractRoller) -> None:
        # Settlement is Mar 20; T-8 => in window
        pos = _pos(holding_period="swing")
        decision = roller.check_position(pos, as_of=date(2024, 3, 12))
        assert decision.status == RollStatus.WINDOW_OPEN

    def test_medium_term_in_window(self, roller: ContractRoller) -> None:
        pos = _pos(holding_period="medium_term")
        # T-4 from Mar 20
        decision = roller.check_position(pos, as_of=date(2024, 3, 16))
        assert decision.status == RollStatus.WINDOW_OPEN

    def test_hard_deadline_forces_roll(self, roller: ContractRoller) -> None:
        pos = _pos(holding_period="medium_term")
        # T-1 from Mar 20
        decision = roller.check_position(pos, as_of=date(2024, 3, 19))
        assert decision.status == RollStatus.FORCED

    def test_settlement_day_forces_roll(self, roller: ContractRoller) -> None:
        pos = _pos(holding_period="swing")
        decision = roller.check_position(pos, as_of=date(2024, 3, 20))
        assert decision.status == RollStatus.FORCED


class TestFavorableSpread:
    def test_favorable_triggers_roll(
        self, roller: ContractRoller, monitor: SpreadMonitor,
    ) -> None:
        ts = datetime(2024, 3, 14, 10, 0, tzinfo=timezone.utc)
        # Build a window of high spreads
        for i in range(15):
            monitor.record("TX", r1_price=20000, r2_price=20100, timestamp=ts)
        # Now a low spread
        monitor.record("TX", r1_price=20000, r2_price=20010, timestamp=ts)

        pos = _pos(holding_period="swing")
        decision = roller.check_position(pos, as_of=date(2024, 3, 14))
        assert decision.status == RollStatus.FAVORABLE

    def test_unfavorable_waits(
        self, roller: ContractRoller, monitor: SpreadMonitor,
    ) -> None:
        ts = datetime(2024, 3, 14, 10, 0, tzinfo=timezone.utc)
        # Build a window of low spreads, then a high one
        for i in range(15):
            monitor.record("TX", r1_price=20000, r2_price=20010, timestamp=ts)
        monitor.record("TX", r1_price=20000, r2_price=20200, timestamp=ts)

        pos = _pos(holding_period="swing")
        decision = roller.check_position(pos, as_of=date(2024, 3, 14))
        assert decision.status == RollStatus.WINDOW_OPEN


class TestShouldRoll:
    def test_favorable_yes(self, roller: ContractRoller, monitor: SpreadMonitor) -> None:
        ts = datetime(2024, 3, 14, 10, 0, tzinfo=timezone.utc)
        for i in range(15):
            monitor.record("TX", r1_price=20000, r2_price=20100, timestamp=ts)
        monitor.record("TX", r1_price=20000, r2_price=20010, timestamp=ts)
        pos = _pos(holding_period="swing")
        decision = roller.check_position(pos, as_of=date(2024, 3, 14))
        assert roller.should_roll(decision) is True

    def test_window_open_no(self, roller: ContractRoller) -> None:
        pos = _pos(holding_period="swing")
        decision = roller.check_position(pos, as_of=date(2024, 3, 12))
        assert roller.should_roll(decision) is False


class TestBuildOrders:
    def test_long_roll_orders(self, roller: ContractRoller) -> None:
        pos = _pos(side="long")
        close_ord, open_ord = roller.build_roll_orders(pos)
        assert close_ord["side"] == "sell"
        assert close_ord["reason"] == "roll_close_r1"
        assert open_ord["side"] == "buy"
        assert open_ord["reason"] == "roll_open_r2"
        assert open_ord["contract"] == "TXFR2"

    def test_short_roll_orders(self, roller: ContractRoller) -> None:
        pos = _pos(side="short")
        close_ord, open_ord = roller.build_roll_orders(pos)
        assert close_ord["side"] == "buy"
        assert open_ord["side"] == "sell"


class TestRecordRoll:
    def test_spread_cost_long(self, roller: ContractRoller) -> None:
        pos = _pos(side="long", lots=2.0)
        record = roller.record_roll(pos, close_price=20000, open_price=20050)
        # Long: spread_cost = (20050 - 20000) * 2 * 200 * 1 = 20000
        assert record.spread_cost == 20000.0
        assert record.trigger == "favorable_spread"

    def test_spread_cost_short(self, roller: ContractRoller) -> None:
        pos = _pos(side="short", lots=1.0)
        record = roller.record_roll(pos, close_price=20000, open_price=20050)
        # Short: spread_cost = (20050 - 20000) * 1 * 200 * -1 = -10000
        assert record.spread_cost == -10000.0

    def test_completed_rolls_tracked(self, roller: ContractRoller) -> None:
        pos = _pos()
        roller.record_roll(pos, close_price=20000, open_price=20050)
        assert len(roller.completed_rolls) == 1


class TestCheckAllPositions:
    def test_batch_check(self, roller: ContractRoller) -> None:
        positions = [
            _pos(holding_period="short_term"),
            _pos(holding_period="swing"),
        ]
        decisions = roller.check_all_positions(positions, as_of=date(2024, 3, 14))
        assert len(decisions) == 2
        assert decisions[0].status == RollStatus.NOT_NEEDED
        assert decisions[1].status == RollStatus.WINDOW_OPEN


class TestPersistence:
    def test_persist_and_load(self, tmp_path) -> None:
        db = tmp_path / "test.db"
        record = RollRecord(
            timestamp=datetime(2024, 3, 19, 10, 0, tzinfo=timezone.utc),
            symbol="TX",
            session_id="sess-001",
            strategy_slug="swing/trend_following/vol_managed_bnh",
            old_contract="TXFR1",
            new_contract="TXFR2",
            side="long",
            lots=2.0,
            close_price=20000.0,
            open_price=20050.0,
            spread_cost=20000.0,
            spread_pct=0.25,
            trigger="favorable_spread",
        )
        persist_roll(record, db)
        loaded = load_roll_history("TX", db)
        assert len(loaded) == 1
        assert loaded[0].spread_cost == 20000.0

    def test_load_empty(self, tmp_path) -> None:
        loaded = load_roll_history("TX", tmp_path / "nonexistent.db")
        assert loaded == []
