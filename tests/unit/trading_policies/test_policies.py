from collections import deque
from datetime import UTC, datetime

import pytest

from src.core.policies import (
    ChandelierStopPolicy,
    NoAddPolicy,
    PyramidAddPolicy,
    PyramidEntryPolicy,
)
from src.core.types import ContractSpecs, Position, PyramidConfig, TradingHours
from tests.conftest import make_engine_state, make_signal, make_snapshot


@pytest.fixture
def specs() -> ContractSpecs:
    hours = TradingHours(open_time="08:45", close_time="13:45", timezone="Asia/Taipei")
    return ContractSpecs(
        symbol="TXF", exchange="TAIFEX", currency="TWD",
        point_value=200.0, margin_initial=184000.0, margin_maintenance=141000.0,
        min_tick=1.0, trading_hours=hours, fee_per_contract=60.0,
        tax_rate=0.00002, lot_types={"large": 200.0, "small": 50.0},
    )


@pytest.fixture
def config() -> PyramidConfig:
    return PyramidConfig(max_loss=500_000.0)


# -- PyramidEntryPolicy --

class TestPyramidEntryPolicy:
    def test_strong_signal_returns_decision(self, config: PyramidConfig, specs: ContractSpecs) -> None:
        policy = PyramidEntryPolicy(config)
        snap = make_snapshot(20000.0, specs, daily_atr=100.0)
        signal = make_signal(direction=1.0, direction_conf=0.8)
        state = make_engine_state()
        decision = policy.should_enter(snap, signal, state)
        assert decision is not None
        assert decision.direction == "long"
        assert decision.lots == 7.0
        assert decision.initial_stop == pytest.approx(20000.0 - 1.5 * 100.0)

    def test_weak_signal_returns_none(self, config: PyramidConfig, specs: ContractSpecs) -> None:
        policy = PyramidEntryPolicy(config)
        snap = make_snapshot(20000.0, specs)
        signal = make_signal(direction=1.0, direction_conf=0.5)
        state = make_engine_state()
        assert policy.should_enter(snap, signal, state) is None

    def test_bearish_signal_returns_none(self, config: PyramidConfig, specs: ContractSpecs) -> None:
        policy = PyramidEntryPolicy(config)
        snap = make_snapshot(20000.0, specs)
        signal = make_signal(direction=-0.5, direction_conf=0.8)
        state = make_engine_state()
        assert policy.should_enter(snap, signal, state) is None

    def test_no_signal_returns_none(self, config: PyramidConfig, specs: ContractSpecs) -> None:
        policy = PyramidEntryPolicy(config)
        snap = make_snapshot(20000.0, specs)
        state = make_engine_state()
        assert policy.should_enter(snap, None, state) is None

    def test_halted_mode_returns_none(self, config: PyramidConfig, specs: ContractSpecs) -> None:
        policy = PyramidEntryPolicy(config)
        snap = make_snapshot(20000.0, specs)
        signal = make_signal(direction=1.0, direction_conf=0.8)
        state = make_engine_state(mode="halted")
        assert policy.should_enter(snap, signal, state) is None

    def test_rule_only_mode_returns_none(self, config: PyramidConfig, specs: ContractSpecs) -> None:
        policy = PyramidEntryPolicy(config)
        snap = make_snapshot(20000.0, specs)
        signal = make_signal(direction=1.0, direction_conf=0.8)
        state = make_engine_state(mode="rule_only")
        assert policy.should_enter(snap, signal, state) is None

    def test_risk_scaling(self, specs: ContractSpecs) -> None:
        config = PyramidConfig(max_loss=100_000.0)
        policy = PyramidEntryPolicy(config)
        snap = make_snapshot(20000.0, specs, daily_atr=100.0)
        signal = make_signal(direction=1.0, direction_conf=0.8)
        state = make_engine_state()
        decision = policy.should_enter(snap, signal, state)
        assert decision is not None
        assert decision.lots < 7.0

    def test_skip_when_min_lot_exceeds_limit(self, specs: ContractSpecs) -> None:
        config = PyramidConfig(max_loss=1.0)
        policy = PyramidEntryPolicy(config)
        snap = make_snapshot(20000.0, specs, daily_atr=100.0)
        signal = make_signal(direction=1.0, direction_conf=0.8)
        state = make_engine_state()
        assert policy.should_enter(snap, signal, state) is None


# -- PyramidAddPolicy --

class TestPyramidAddPolicy:
    def _make_position(self, entry_price: float = 20000.0) -> Position:
        return Position(
            entry_price=entry_price, lots=7.0, contract_type="large",
            stop_level=entry_price - 150.0, pyramid_level=0,
            entry_timestamp=datetime.now(UTC),
        )

    def test_add_at_threshold(self, config: PyramidConfig, specs: ContractSpecs) -> None:
        policy = PyramidAddPolicy(config)
        pos = self._make_position(20000.0)
        state = make_engine_state(positions=(pos,), pyramid_level=1)
        snap = make_snapshot(20400.0, specs, daily_atr=100.0)
        decision = policy.should_add(snap, None, state)
        assert decision is not None
        assert decision.lots == 2.0
        assert decision.move_existing_to_breakeven is True

    def test_below_threshold_returns_none(self, config: PyramidConfig, specs: ContractSpecs) -> None:
        policy = PyramidAddPolicy(config)
        pos = self._make_position(20000.0)
        state = make_engine_state(positions=(pos,), pyramid_level=1)
        snap = make_snapshot(20300.0, specs, daily_atr=100.0)
        assert policy.should_add(snap, None, state) is None

    def test_max_level_returns_none(self, config: PyramidConfig, specs: ContractSpecs) -> None:
        policy = PyramidAddPolicy(config)
        pos = self._make_position(20000.0)
        state = make_engine_state(positions=(pos,), pyramid_level=4)
        snap = make_snapshot(22000.0, specs, daily_atr=100.0)
        assert policy.should_add(snap, None, state) is None

    def test_halted_returns_none(self, config: PyramidConfig, specs: ContractSpecs) -> None:
        policy = PyramidAddPolicy(config)
        pos = self._make_position(20000.0)
        state = make_engine_state(positions=(pos,), pyramid_level=1, mode="halted")
        snap = make_snapshot(20400.0, specs, daily_atr=100.0)
        assert policy.should_add(snap, None, state) is None


# -- ChandelierStopPolicy --

class TestChandelierStopPolicy:
    def test_initial_stop_long(self, config: PyramidConfig, specs: ContractSpecs) -> None:
        policy = ChandelierStopPolicy(config)
        snap = make_snapshot(20000.0, specs, daily_atr=100.0)
        stop = policy.initial_stop(20000.0, "long", snap)
        assert stop == pytest.approx(20000.0 - 1.5 * 100.0)

    def test_initial_stop_short(self, config: PyramidConfig, specs: ContractSpecs) -> None:
        policy = ChandelierStopPolicy(config)
        snap = make_snapshot(20000.0, specs, daily_atr=100.0)
        stop = policy.initial_stop(20000.0, "short", snap)
        assert stop == pytest.approx(20000.0 + 1.5 * 100.0)

    def test_breakeven_long(self, config: PyramidConfig, specs: ContractSpecs) -> None:
        policy = ChandelierStopPolicy(config)
        pos = Position(
            entry_price=20000.0, lots=7.0, contract_type="large",
            stop_level=19850.0, pyramid_level=0,
            entry_timestamp=datetime.now(UTC), direction="long",
        )
        snap = make_snapshot(20101.0, specs, daily_atr=100.0)
        history: deque[float] = deque([20000.0, 20050.0, 20101.0])
        new_stop = policy.update_stop(pos, snap, history)
        assert new_stop >= 20000.0

    def test_chandelier_long(self, config: PyramidConfig, specs: ContractSpecs) -> None:
        policy = ChandelierStopPolicy(config)
        pos = Position(
            entry_price=20000.0, lots=7.0, contract_type="large",
            stop_level=20000.0, pyramid_level=0,
            entry_timestamp=datetime.now(UTC), direction="long",
        )
        snap = make_snapshot(20600.0, specs, daily_atr=100.0)
        history: deque[float] = deque([20000.0, 20200.0, 20400.0, 20600.0])
        new_stop = policy.update_stop(pos, snap, history)
        expected = 20600.0 - 3.0 * 100.0
        assert new_stop == pytest.approx(expected)

    def test_breakeven_short(self, config: PyramidConfig, specs: ContractSpecs) -> None:
        policy = ChandelierStopPolicy(config)
        pos = Position(
            entry_price=20000.0, lots=7.0, contract_type="large",
            stop_level=20150.0, pyramid_level=0,
            entry_timestamp=datetime.now(UTC), direction="short",
        )
        snap = make_snapshot(19899.0, specs, daily_atr=100.0)
        history: deque[float] = deque([20000.0, 19950.0, 19899.0])
        new_stop = policy.update_stop(pos, snap, history)
        assert new_stop <= 20000.0

    def test_chandelier_short(self, config: PyramidConfig, specs: ContractSpecs) -> None:
        policy = ChandelierStopPolicy(config)
        pos = Position(
            entry_price=20000.0, lots=7.0, contract_type="large",
            stop_level=20000.0, pyramid_level=0,
            entry_timestamp=datetime.now(UTC), direction="short",
        )
        snap = make_snapshot(19400.0, specs, daily_atr=100.0)
        history: deque[float] = deque([20000.0, 19800.0, 19600.0, 19400.0])
        new_stop = policy.update_stop(pos, snap, history)
        expected = 19400.0 + 3.0 * 100.0
        assert new_stop == pytest.approx(expected)


# -- NoAddPolicy --

class TestNoAddPolicy:
    def test_always_returns_none(self, specs: ContractSpecs) -> None:
        policy = NoAddPolicy()
        snap = make_snapshot(20000.0, specs)
        state = make_engine_state()
        assert policy.should_add(snap, None, state) is None
