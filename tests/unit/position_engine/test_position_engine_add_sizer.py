"""Tests for the PositionEngine.add_sizer hook.

Mirrors the existing entry_sizer pattern: the hook runs at the top of
_execute_add before Position construction and may rewrite decision.lots or
abort by returning None.
"""
from __future__ import annotations

import pytest

from src.core.policies import (
    AddPolicy,
    ChandelierStopPolicy,
    EntryPolicy,
    PyramidEntryPolicy,
)
from src.core.position_engine import PositionEngine
from src.core.types import (
    AddDecision,
    ContractSpecs,
    EngineConfig,
    EntryDecision,
    MarketSnapshot,
    PyramidConfig,
    TradingHours,
)
from tests.conftest import make_account, make_signal, make_snapshot


@pytest.fixture
def specs() -> ContractSpecs:
    hours = TradingHours(open_time="08:45", close_time="13:45", timezone="Asia/Taipei")
    return ContractSpecs(
        symbol="TXF", exchange="TAIFEX", currency="TWD",
        point_value=200.0, margin_initial=184000.0, margin_maintenance=141000.0,
        min_tick=1.0, trading_hours=hours, fee_per_contract=60.0,
        tax_rate=0.00002, lot_types={"large": 200.0, "small": 50.0},
    )


class _FixedLotAddPolicy(AddPolicy):
    """AddPolicy that always emits the same fixed AddDecision."""

    def __init__(self, decision: AddDecision) -> None:
        self._decision = decision
        self._emitted = False

    def should_add(self, snapshot, signal, engine_state):
        if self._emitted or not engine_state.positions:
            return None
        self._emitted = True
        return self._decision


class _ConfigurableEntryPolicy(EntryPolicy):
    """Entry policy that emits a fixed EntryDecision on first call."""

    def __init__(self, decision: EntryDecision) -> None:
        self._decision = decision
        self._emitted = False

    def should_enter(self, snapshot, signal, engine_state, account=None):
        if self._emitted or engine_state.positions:
            return None
        self._emitted = True
        return self._decision


def _build_engine(entry_decision: EntryDecision, add_decision: AddDecision) -> PositionEngine:
    config = PyramidConfig(max_loss=500_000.0)
    return PositionEngine(
        entry_policy=_ConfigurableEntryPolicy(entry_decision),
        add_policy=_FixedLotAddPolicy(add_decision),
        stop_policy=ChandelierStopPolicy(config),
        config=EngineConfig(max_loss=config.max_loss, margin_limit=0.8),
    )


class TestAddSizerHook:
    def test_add_sizer_invoked_before_position_construction(
        self, specs: ContractSpecs
    ) -> None:
        """Hook receives original decision + snapshot + positions list;
        its return value's lots appears in positions[-1].lots."""
        entry = EntryDecision(
            lots=3.0, contract_type="large",
            initial_stop=19000.0, direction="long",
        )
        add = AddDecision(
            lots=1.5,  # raw multiplier
            contract_type="large",
            metadata={"exposure_multiplier": True},
        )
        engine = _build_engine(entry, add)

        captured: list[tuple[AddDecision, MarketSnapshot, list]] = []

        def _spy(decision: AddDecision, snapshot: MarketSnapshot, positions: list):
            captured.append((decision, snapshot, list(positions)))
            # Resolve multiplier ×5 and return as absolute contracts.
            return AddDecision(
                lots=7.0,
                contract_type=decision.contract_type,
                move_existing_to_breakeven=decision.move_existing_to_breakeven,
                metadata=decision.metadata,
            )

        engine.add_sizer = _spy

        # Both entry (priority 4) and add (priority 5) can fire on the same bar.
        snap1 = make_snapshot(20000.0, specs)
        sig = make_signal(direction=1.0, direction_conf=0.8)
        orders = engine.on_snapshot(snap1, sig, make_account())

        add_orders = [o for o in orders if o.reason.startswith("add_level")]
        assert len(add_orders) == 1
        assert add_orders[0].lots == 7.0

        state = engine.get_state()
        assert state.positions[-1].lots == 7.0

        # Spy saw the original (un-sized) decision + positions list with base entry
        # already appended (entry executed at priority 4 before add at priority 5).
        assert len(captured) == 1
        seen_decision, _, seen_positions = captured[0]
        assert seen_decision.lots == 1.5  # raw multiplier
        assert seen_decision.metadata["exposure_multiplier"] is True
        assert len(seen_positions) == 1
        assert seen_positions[0].lots == 3.0

    def test_add_sizer_none_return_aborts_add(self, specs: ContractSpecs) -> None:
        """A sizer returning None silently aborts the add."""
        entry = EntryDecision(
            lots=3.0, contract_type="large",
            initial_stop=19000.0, direction="long",
        )
        add = AddDecision(lots=1.5, contract_type="large")
        engine = _build_engine(entry, add)
        engine.add_sizer = lambda d, s, p: None

        sig = make_signal(direction=1.0, direction_conf=0.8)
        orders = engine.on_snapshot(make_snapshot(20000.0, specs), sig, make_account())

        assert not any(o.reason.startswith("add_level") for o in orders)
        # Only the base position (add aborted).
        assert engine.get_state().pyramid_level == 1

    def test_add_sizer_absent_passes_decision_through(
        self, specs: ContractSpecs
    ) -> None:
        """Without a sizer attached, strategy-emitted lots flow through."""
        entry = EntryDecision(
            lots=3.0, contract_type="large",
            initial_stop=19000.0, direction="long",
        )
        add = AddDecision(lots=2.0, contract_type="large")
        engine = _build_engine(entry, add)
        assert engine.add_sizer is None

        sig = make_signal(direction=1.0, direction_conf=0.8)
        engine.on_snapshot(make_snapshot(20000.0, specs), sig, make_account())
        state = engine.get_state()
        assert state.positions[-1].lots == 2.0

    def test_add_sizer_property_setter_roundtrip(self) -> None:
        """Setter/getter/unset roundtrip works."""
        config = PyramidConfig(max_loss=500_000.0)
        engine = PositionEngine(
            entry_policy=PyramidEntryPolicy(config),
            add_policy=_FixedLotAddPolicy(AddDecision(lots=1.0, contract_type="large")),
            stop_policy=ChandelierStopPolicy(config),
            config=EngineConfig(max_loss=config.max_loss),
        )
        assert engine.add_sizer is None

        def fn(d, s, p):
            return d

        engine.add_sizer = fn
        assert engine.add_sizer is fn
        engine.add_sizer = None
        assert engine.add_sizer is None
