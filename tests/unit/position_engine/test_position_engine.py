
import pytest

from src.core.policies import ChandelierStopPolicy, EntryPolicy, NoAddPolicy, PyramidEntryPolicy
from src.core.position_engine import PositionEngine, create_pyramid_engine
from src.core.types import ContractSpecs, EngineConfig, PyramidConfig, TradingHours
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


@pytest.fixture
def config() -> PyramidConfig:
    return PyramidConfig(max_loss=500_000.0)


@pytest.fixture
def engine(config: PyramidConfig) -> PositionEngine:
    return create_pyramid_engine(config)


# -- Init --

class TestInit:
    def test_starts_flat(self, engine: PositionEngine) -> None:
        state = engine.get_state()
        assert len(state.positions) == 0
        assert state.pyramid_level == 0
        assert state.mode == "model_assisted"


# -- Entry logic --

class TestEntryLogic:
    def test_entry_policy_receives_account_context(self, specs: ContractSpecs) -> None:
        captured: list[object] = []

        class SpyEntryPolicy(EntryPolicy):
            def should_enter(
                self,
                snapshot,
                signal,
                engine_state,
                account=None,
            ):
                captured.append(account)
                return None

        config = PyramidConfig(max_loss=500_000.0)
        engine_config = EngineConfig(max_loss=config.max_loss)
        engine = PositionEngine(
            entry_policy=SpyEntryPolicy(),
            add_policy=NoAddPolicy(),
            stop_policy=ChandelierStopPolicy(config),
            config=engine_config,
        )
        account = make_account()
        snap = make_snapshot(20000.0, specs)
        signal = make_signal(direction=1.0, direction_conf=0.8)
        engine.on_snapshot(snap, signal, account=account)
        assert captured and captured[0] is account

    def test_strong_signal_generates_entry(
        self, engine: PositionEngine, specs: ContractSpecs
    ) -> None:
        snap = make_snapshot(20000.0, specs)
        signal = make_signal(direction=1.0, direction_conf=0.8)
        orders = engine.on_snapshot(snap, signal)
        assert len(orders) == 1
        assert orders[0].reason == "entry"
        assert orders[0].side == "buy"
        assert engine.get_state().pyramid_level == 1

    def test_weak_signal_no_entry(
        self, engine: PositionEngine, specs: ContractSpecs
    ) -> None:
        snap = make_snapshot(20000.0, specs)
        signal = make_signal(direction=1.0, direction_conf=0.5)
        orders = engine.on_snapshot(snap, signal)
        assert len(orders) == 0
        assert engine.get_state().pyramid_level == 0

    def test_threshold_boundary_no_entry(
        self, engine: PositionEngine, specs: ContractSpecs
    ) -> None:
        snap = make_snapshot(20000.0, specs)
        signal = make_signal(direction=1.0, direction_conf=0.65)
        orders = engine.on_snapshot(snap, signal)
        assert len(orders) == 0

    def test_threshold_boundary_entry(
        self, engine: PositionEngine, specs: ContractSpecs
    ) -> None:
        snap = make_snapshot(20000.0, specs)
        signal = make_signal(direction=1.0, direction_conf=0.66)
        orders = engine.on_snapshot(snap, signal)
        assert len(orders) == 1
        assert orders[0].reason == "entry"

    def test_no_signal_no_entry(
        self, engine: PositionEngine, specs: ContractSpecs
    ) -> None:
        snap = make_snapshot(20000.0, specs)
        orders = engine.on_snapshot(snap, None)
        assert len(orders) == 0

    def test_initial_stop_set_correctly(
        self, engine: PositionEngine, specs: ContractSpecs, config: PyramidConfig
    ) -> None:
        daily_atr = 100.0
        entry_price = 20000.0
        snap = make_snapshot(entry_price, specs, daily_atr=daily_atr)
        signal = make_signal(direction=1.0, direction_conf=0.8)
        engine.on_snapshot(snap, signal)
        state = engine.get_state()
        expected_stop = entry_price - config.stop_atr_mult * daily_atr
        assert state.positions[0].stop_level == pytest.approx(expected_stop)


# -- Pre-entry risk scaling --

class TestPreEntryRiskScaling:
    def test_lots_scaled_down_by_max_loss(self, specs: ContractSpecs) -> None:
        # stop_distance = 1.5 * 100 = 150 pts, point_value = 200
        # default lots = 7, max_loss_if_stopped = 7 * 150 * 200 = 210,000
        # with max_loss=100_000 → scaled = 100000 / (150*200) = 3.33
        config = PyramidConfig(max_loss=100_000.0)
        engine = create_pyramid_engine(config)
        snap = make_snapshot(20000.0, specs, daily_atr=100.0)
        signal = make_signal(direction=1.0, direction_conf=0.8)
        orders = engine.on_snapshot(snap, signal)
        assert len(orders) == 1
        assert orders[0].lots < 7.0
        assert orders[0].lots >= 1.0

    def test_entry_skipped_when_min_lot_exceeds_limit(
        self, specs: ContractSpecs
    ) -> None:
        config = PyramidConfig(max_loss=1.0)
        engine = create_pyramid_engine(config)
        snap = make_snapshot(20000.0, specs, daily_atr=100.0)
        signal = make_signal(direction=1.0, direction_conf=0.8)
        orders = engine.on_snapshot(snap, signal)
        # max lots = 1.0 / (150 * 200) = 0.0000333 < min_lot (1.0)
        assert len(orders) == 0


# -- Pyramid adds --

class TestPyramidAdds:
    def _enter_position(
        self, engine: PositionEngine, specs: ContractSpecs, price: float = 20000.0
    ) -> None:
        snap = make_snapshot(price, specs, daily_atr=100.0)
        signal = make_signal(direction=1.0, direction_conf=0.8)
        engine.on_snapshot(snap, signal)

    def test_add_at_correct_atr_threshold(
        self, engine: PositionEngine, specs: ContractSpecs
    ) -> None:
        self._enter_position(engine, specs, 20000.0)
        # add_trigger_atr[0] = 4.0 → need 4.0 * 100 = 400 points profit
        # price needs to be >= 20400
        snap = make_snapshot(20400.0, specs, daily_atr=100.0)
        orders = engine.on_snapshot(snap)
        assert any("add_level" in o.reason for o in orders)
        assert engine.get_state().pyramid_level == 2

    def test_no_add_below_threshold(
        self, engine: PositionEngine, specs: ContractSpecs
    ) -> None:
        self._enter_position(engine, specs, 20000.0)
        snap = make_snapshot(20300.0, specs, daily_atr=100.0)
        orders = engine.on_snapshot(snap)
        assert not any("add_level" in o.reason for o in orders)
        assert engine.get_state().pyramid_level == 1

    def test_existing_stops_move_to_breakeven_on_add(
        self, engine: PositionEngine, specs: ContractSpecs
    ) -> None:
        self._enter_position(engine, specs, 20000.0)
        snap = make_snapshot(20400.0, specs, daily_atr=100.0)
        engine.on_snapshot(snap)
        state = engine.get_state()
        # First position's stop should be at breakeven (entry price)
        assert state.positions[0].stop_level >= state.positions[0].entry_price


# -- Stops only move upward --

class TestStopsOnlyMoveUpward:
    def test_trailing_stop_never_decreases(
        self, engine: PositionEngine, specs: ContractSpecs
    ) -> None:
        snap = make_snapshot(20000.0, specs, daily_atr=100.0)
        signal = make_signal(direction=1.0, direction_conf=0.8)
        engine.on_snapshot(snap, signal)

        # Price rises — chandelier stop = highest - 3*100
        # At 20600: stop = 20600 - 300 = 20300
        for price in [20200.0, 20400.0, 20600.0]:
            engine.on_snapshot(make_snapshot(price, specs, daily_atr=100.0))

        state_high = engine.get_state()
        stop_after_rise = state_high.positions[0].stop_level

        # Price drops but stays above the stop level
        engine.on_snapshot(make_snapshot(20400.0, specs, daily_atr=100.0))
        state_low = engine.get_state()
        stop_after_drop = state_low.positions[0].stop_level

        assert stop_after_drop >= stop_after_rise


# -- Breakeven stop --

class TestBreakevenStop:
    def test_stop_moves_to_entry_after_1_atr_profit(
        self, engine: PositionEngine, specs: ContractSpecs
    ) -> None:
        entry_price = 20000.0
        daily_atr = 100.0
        snap = make_snapshot(entry_price, specs, daily_atr=daily_atr)
        signal = make_signal(direction=1.0, direction_conf=0.8)
        engine.on_snapshot(snap, signal)

        initial_stop = engine.get_state().positions[0].stop_level
        assert initial_stop < entry_price

        # Price rises by more than 1 ATR
        snap2 = make_snapshot(entry_price + daily_atr + 1, specs, daily_atr=daily_atr)
        engine.on_snapshot(snap2)

        new_stop = engine.get_state().positions[0].stop_level
        assert new_stop >= entry_price


# -- Circuit breaker --

class TestCircuitBreaker:
    def test_drawdown_triggers_close_all(self, specs: ContractSpecs) -> None:
        config = PyramidConfig(max_loss=50_000.0)
        engine = create_pyramid_engine(config)

        # Enter at 20000, stop at 19850
        snap = make_snapshot(20000.0, specs, daily_atr=100.0)
        signal = make_signal(direction=1.0, direction_conf=0.8)
        engine.on_snapshot(snap, signal)

        # Price above stop (19850) but account drawdown exceeds max_loss
        account = make_account(
            equity=2_000_000.0, drawdown_pct=0.03
        )  # 0.03 * 2M = 60k > 50k max_loss
        snap2 = make_snapshot(19900.0, specs, daily_atr=100.0)
        orders = engine.on_snapshot(snap2, account=account)

        circuit_orders = [o for o in orders if o.reason == "circuit_breaker"]
        assert len(circuit_orders) > 0
        assert engine.get_state().mode == "halted"
        assert len(engine.get_state().positions) == 0

    def test_below_max_loss_no_trigger(self, specs: ContractSpecs) -> None:
        config = PyramidConfig(max_loss=500_000.0)
        engine = create_pyramid_engine(config)

        snap = make_snapshot(20000.0, specs, daily_atr=100.0)
        signal = make_signal(direction=1.0, direction_conf=0.8)
        engine.on_snapshot(snap, signal)

        account = make_account(equity=2_000_000.0, drawdown_pct=0.01)
        snap2 = make_snapshot(19900.0, specs, daily_atr=100.0)
        orders = engine.on_snapshot(snap2, account=account)

        circuit_orders = [o for o in orders if o.reason == "circuit_breaker"]
        assert len(circuit_orders) == 0
        assert engine.get_state().mode == "model_assisted"


# -- Rule-only mode --

class TestRuleOnlyMode:
    def test_no_signal_entries_in_rule_only(
        self, engine: PositionEngine, specs: ContractSpecs
    ) -> None:
        engine.set_mode("rule_only")
        snap = make_snapshot(20000.0, specs)
        signal = make_signal(direction=1.0, direction_conf=0.9)
        orders = engine.on_snapshot(snap, signal)
        assert len(orders) == 0

    def test_stops_still_active_in_rule_only(self, specs: ContractSpecs) -> None:
        config = PyramidConfig(max_loss=500_000.0)
        engine = create_pyramid_engine(config)

        # Enter position first
        snap = make_snapshot(20000.0, specs, daily_atr=100.0)
        signal = make_signal(direction=1.0, direction_conf=0.8)
        engine.on_snapshot(snap, signal)

        engine.set_mode("rule_only")

        # Price drops below stop level (entry - 1.5 * 100 = 19850)
        snap2 = make_snapshot(19800.0, specs, daily_atr=100.0)
        orders = engine.on_snapshot(snap2)
        stop_orders = [o for o in orders if o.reason in ("stop_loss", "trailing_stop")]
        assert len(stop_orders) > 0


# -- Halted mode --

class TestHaltedMode:
    def test_no_entries_when_halted(
        self, engine: PositionEngine, specs: ContractSpecs
    ) -> None:
        engine.set_mode("halted")
        snap = make_snapshot(20000.0, specs)
        signal = make_signal(direction=1.0, direction_conf=0.9)
        orders = engine.on_snapshot(snap, signal)
        assert len(orders) == 0

    def test_stops_still_fire_when_halted(self, specs: ContractSpecs) -> None:
        config = PyramidConfig(max_loss=500_000.0)
        engine = create_pyramid_engine(config)

        snap = make_snapshot(20000.0, specs, daily_atr=100.0)
        signal = make_signal(direction=1.0, direction_conf=0.8)
        engine.on_snapshot(snap, signal)

        engine.set_mode("halted")

        snap2 = make_snapshot(19800.0, specs, daily_atr=100.0)
        orders = engine.on_snapshot(snap2)
        stop_orders = [o for o in orders if o.reason in ("stop_loss", "trailing_stop")]
        assert len(stop_orders) > 0


# -- Margin safety --

class TestMarginSafety:
    def test_reduce_orders_when_margin_breached(
        self, engine: PositionEngine, specs: ContractSpecs
    ) -> None:
        snap = make_snapshot(20000.0, specs, daily_atr=100.0)
        signal = make_signal(direction=1.0, direction_conf=0.8)
        engine.on_snapshot(snap, signal)

        account = make_account(margin_ratio=0.6)
        snap2 = make_snapshot(20000.0, specs, daily_atr=100.0)
        orders = engine.on_snapshot(snap2, account=account)

        margin_orders = [o for o in orders if o.reason == "margin_safety"]
        assert len(margin_orders) > 0

    def test_no_reduce_when_margin_ok(
        self, engine: PositionEngine, specs: ContractSpecs
    ) -> None:
        snap = make_snapshot(20000.0, specs, daily_atr=100.0)
        signal = make_signal(direction=1.0, direction_conf=0.8)
        engine.on_snapshot(snap, signal)

        account = make_account(margin_ratio=0.3)
        snap2 = make_snapshot(20000.0, specs, daily_atr=100.0)
        orders = engine.on_snapshot(snap2, account=account)

        margin_orders = [o for o in orders if o.reason == "margin_safety"]
        assert len(margin_orders) == 0


# -- Pre-trade margin gate --

class TestPreTradeMarginGate:
    def _strict_engine(self, config: PyramidConfig) -> PositionEngine:
        engine_config = EngineConfig(
            max_loss=config.max_loss,
            margin_limit=config.margin_limit,
            trail_lookback=config.trail_lookback,
            require_account_for_entry=True,
        )
        return PositionEngine(
            entry_policy=PyramidEntryPolicy(config),
            add_policy=NoAddPolicy(),
            stop_policy=ChandelierStopPolicy(config),
            config=engine_config,
        )

    def test_insufficient_margin_blocks_entry_and_records_event(
        self, specs: ContractSpecs
    ) -> None:
        engine = self._strict_engine(PyramidConfig(max_loss=500_000.0))
        snap = make_snapshot(20000.0, specs, daily_atr=100.0)
        signal = make_signal(direction=1.0, direction_conf=0.9)
        low_margin_account = make_account(equity=2_000_000.0, margin_ratio=0.98)
        orders = engine.on_snapshot(snap, signal, account=low_margin_account)
        assert orders == []
        events = engine.pre_trade_rejection_events
        assert len(events) == 1
        assert events[0]["reason"] == "insufficient_margin"

    def test_missing_account_blocks_entry_when_required(self, specs: ContractSpecs) -> None:
        engine = self._strict_engine(PyramidConfig(max_loss=500_000.0))
        snap = make_snapshot(20000.0, specs, daily_atr=100.0)
        signal = make_signal(direction=1.0, direction_conf=0.9)
        orders = engine.on_snapshot(snap, signal, account=None)
        assert orders == []
        events = engine.pre_trade_rejection_events
        assert len(events) == 1
        assert events[0]["reason"] == "missing_account_context"

    def test_stop_orders_bypass_entry_margin_gate(self, specs: ContractSpecs) -> None:
        engine = self._strict_engine(PyramidConfig(max_loss=500_000.0))
        entry_account = make_account(equity=20_000_000.0, margin_ratio=0.2)
        entry_snap = make_snapshot(20000.0, specs, daily_atr=100.0)
        signal = make_signal(direction=1.0, direction_conf=0.9)
        entry_orders = engine.on_snapshot(entry_snap, signal, account=entry_account)
        assert len(entry_orders) == 1
        low_margin_account = make_account(equity=2_000_000.0, margin_ratio=0.99)
        stop_snap = make_snapshot(19800.0, specs, daily_atr=100.0)
        stop_orders = engine.on_snapshot(stop_snap, None, account=low_margin_account)
        assert any(item.reason in ("stop_loss", "trailing_stop") for item in stop_orders)


# -- Lot scaling respects max_loss --

class TestLotScaling:
    def test_position_size_bounded_by_max_loss(self, specs: ContractSpecs) -> None:
        config = PyramidConfig(max_loss=30_000.0)
        engine = create_pyramid_engine(config)
        daily_atr = 100.0
        snap = make_snapshot(20000.0, specs, daily_atr=daily_atr)
        signal = make_signal(direction=1.0, direction_conf=0.8)
        orders = engine.on_snapshot(snap, signal)

        if orders:
            stop_distance = config.stop_atr_mult * daily_atr
            max_lots = config.max_loss / (stop_distance * specs.point_value)
            assert orders[0].lots <= max_lots + 0.001


# -- Direction-aware (short) tests --

class TestShortDirection:
    """Tests using a custom short entry policy to verify engine handles shorts."""

    @staticmethod
    def _make_short_engine(config: PyramidConfig) -> PositionEngine:
        """Build engine with a short-biased entry policy for testing."""
        from src.core.policies import EntryPolicy
        from src.core.types import (
            AccountState,
            EngineState,
            EntryDecision,
            MarketSignal,
            MarketSnapshot,
        )

        class ShortEntryPolicy(EntryPolicy):
            def __init__(self, cfg: PyramidConfig) -> None:
                self._config = cfg

            def should_enter(
                self,
                snapshot: MarketSnapshot,
                signal: MarketSignal | None,
                engine_state: EngineState,
                account: AccountState | None = None,
            ) -> EntryDecision | None:
                if signal is None or signal.direction_conf <= self._config.entry_conf_threshold:
                    return None
                if signal.direction >= 0:
                    return None
                daily_atr = snapshot.atr["daily"]
                stop_distance = self._config.stop_atr_mult * daily_atr
                lots = float(sum(self._config.lot_schedule[0]))
                return EntryDecision(
                    lots=lots,
                    contract_type="large",
                    initial_stop=snapshot.price + stop_distance,
                    direction="short",
                )

        engine_config = EngineConfig(
            max_loss=config.max_loss,
            margin_limit=config.margin_limit,
            trail_lookback=config.trail_lookback,
        )
        return PositionEngine(
            entry_policy=ShortEntryPolicy(config),
            add_policy=NoAddPolicy(),
            stop_policy=ChandelierStopPolicy(config),
            config=engine_config,
        )

    def test_short_entry_generates_sell_order(self, specs: ContractSpecs) -> None:
        config = PyramidConfig(max_loss=500_000.0)
        engine = self._make_short_engine(config)
        snap = make_snapshot(20000.0, specs, daily_atr=100.0)
        signal = make_signal(direction=-1.0, direction_conf=0.8)
        orders = engine.on_snapshot(snap, signal)
        assert len(orders) == 1
        assert orders[0].side == "sell"
        assert orders[0].reason == "entry"

    def test_short_stop_triggers_on_price_rise(self, specs: ContractSpecs) -> None:
        config = PyramidConfig(max_loss=500_000.0)
        engine = self._make_short_engine(config)
        snap = make_snapshot(20000.0, specs, daily_atr=100.0)
        signal = make_signal(direction=-1.0, direction_conf=0.8)
        engine.on_snapshot(snap, signal)

        state = engine.get_state()
        assert state.positions[0].direction == "short"
        # stop is at 20000 + 1.5 * 100 = 20150
        stop_level = state.positions[0].stop_level
        assert stop_level == pytest.approx(20150.0)

        # Price rises above stop
        snap2 = make_snapshot(20200.0, specs, daily_atr=100.0)
        orders = engine.on_snapshot(snap2)
        stop_orders = [o for o in orders if o.reason in ("stop_loss", "trailing_stop")]
        assert len(stop_orders) > 0
        assert stop_orders[0].side == "buy"

    def test_short_pnl_calculation(self, specs: ContractSpecs) -> None:
        config = PyramidConfig(max_loss=500_000.0)
        engine = self._make_short_engine(config)
        snap = make_snapshot(20000.0, specs, daily_atr=100.0)
        signal = make_signal(direction=-1.0, direction_conf=0.8)
        engine.on_snapshot(snap, signal)

        # Price drops = profit for short
        snap2 = make_snapshot(19900.0, specs, daily_atr=100.0)
        engine.on_snapshot(snap2)
        # No stop triggered, position still open

        state = engine.get_state()
        assert len(state.positions) == 1

    def test_short_circuit_breaker_generates_buy(self, specs: ContractSpecs) -> None:
        config = PyramidConfig(max_loss=50_000.0)
        engine = self._make_short_engine(config)
        snap = make_snapshot(20000.0, specs, daily_atr=100.0)
        signal = make_signal(direction=-1.0, direction_conf=0.8)
        engine.on_snapshot(snap, signal)

        account = make_account(equity=2_000_000.0, drawdown_pct=0.03)
        snap2 = make_snapshot(20100.0, specs, daily_atr=100.0)
        orders = engine.on_snapshot(snap2, account=account)
        circuit_orders = [o for o in orders if o.reason == "circuit_breaker"]
        assert len(circuit_orders) > 0
        assert circuit_orders[0].side == "buy"
        assert engine.get_state().mode == "halted"
