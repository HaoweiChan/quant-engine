"""Unit tests for ``EngineConfig.intrabar_stop_check`` + ``whole_book_exit_on_stop``
+ ``stop_fill_at_level``.

Pins the contract added to close the MCP-vs-simulator gap for
``compounding_trend_long_mtf``. Default config preserves existing behavior;
opt-in flags switch the trigger to intra-bar low/high pierce, expand single
stop-outs into whole-book exits, and inject ``fill_price_override`` metadata.
"""
from __future__ import annotations

from datetime import datetime

import pytest

from src.core.policies import EntryPolicy, NoAddPolicy, StopPolicy
from src.core.position_engine import PositionEngine
from src.core.types import (
    ContractSpecs,
    EngineConfig,
    MarketSnapshot,
    Position,
    TradingHours,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
TX_SPECS = ContractSpecs(
    symbol="TX",
    exchange="TAIFEX",
    currency="TWD",
    point_value=200.0,
    margin_initial=477_000.0,
    margin_maintenance=366_000.0,
    min_tick=1.0,
    trading_hours=TradingHours(open_time="08:45", close_time="13:45", timezone="Asia/Taipei"),
    fee_per_contract=100.0,
    tax_rate=0.00002,
    lot_types={"large": 200.0},
)


def _snapshot(price: float, *, bar_high: float | None = None,
              bar_low: float | None = None, ts: datetime | None = None) -> MarketSnapshot:
    return MarketSnapshot(
        price=price,
        atr={"daily": 100.0},
        timestamp=ts or datetime(2025, 6, 11, 9, 5),
        margin_per_unit=477_000.0,
        point_value=200.0,
        min_lot=1.0,
        contract_specs=TX_SPECS,
        volume=10_000.0,
        bar_high=bar_high,
        bar_low=bar_low,
    )


class _NeverEnter(EntryPolicy):
    def should_enter(self, snapshot, signal, engine_state, account=None):
        return None


class _NoStopPolicy(StopPolicy):
    def initial_stop(self, entry_price, direction, snapshot):
        return entry_price - 1000 if direction == "long" else entry_price + 1000

    def update_stop(self, position, snapshot, high_history):
        return position.stop_level


def _build_engine(config: EngineConfig) -> PositionEngine:
    return PositionEngine(
        entry_policy=_NeverEnter(),
        add_policy=NoAddPolicy(),
        stop_policy=_NoStopPolicy(),
        config=config,
    )


def _seed_position(engine: PositionEngine, *, lots: float, stop_level: float,
                   pyramid_level: int = 0, entry_ts: datetime | None = None) -> Position:
    pos = Position(
        entry_price=22000.0,
        lots=lots,
        contract_type="large",
        stop_level=stop_level,
        pyramid_level=pyramid_level,
        entry_timestamp=entry_ts or datetime(2025, 6, 10, 13, 30),
        direction="long",
    )
    engine._positions.append(pos)  # type: ignore[attr-defined]
    return pos


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
def test_default_off_close_above_stop_no_exit() -> None:
    """Default config (intrabar=False): wick below stop but close above → no exit."""
    engine = _build_engine(EngineConfig(max_loss=1e9))
    _seed_position(engine, lots=10, stop_level=21900.0)
    snap = _snapshot(price=21950.0, bar_low=21800.0, bar_high=22000.0)
    orders = engine._check_stops(snap)  # type: ignore[attr-defined]
    assert orders == [], "close-based stop must not trigger when close > stop_level"


def test_intrabar_on_wick_below_stop_triggers_exit() -> None:
    """intrabar=True: bar_low pierces stop → exit even if close is above."""
    engine = _build_engine(EngineConfig(max_loss=1e9, intrabar_stop_check=True))
    _seed_position(engine, lots=10, stop_level=21900.0)
    snap = _snapshot(price=21950.0, bar_low=21850.0, bar_high=22000.0)
    orders = engine._check_stops(snap)  # type: ignore[attr-defined]
    assert len(orders) == 1
    assert orders[0].reason == "trailing_stop"
    assert orders[0].lots == 10.0


def test_intrabar_on_same_bar_entry_no_trigger() -> None:
    """Same-bar entry guard: position opened on this bar is ineligible for intra-bar trigger."""
    ts = datetime(2025, 6, 11, 9, 5)
    engine = _build_engine(EngineConfig(max_loss=1e9, intrabar_stop_check=True))
    # Entry timestamp matches snapshot timestamp.
    _seed_position(engine, lots=10, stop_level=21900.0, entry_ts=ts)
    snap = _snapshot(price=21950.0, bar_low=21850.0, bar_high=22000.0, ts=ts)
    orders = engine._check_stops(snap)  # type: ignore[attr-defined]
    assert orders == [], "same-bar entry must not be eligible for intra-bar stop trigger"


def test_whole_book_exit_closes_all_same_direction() -> None:
    """whole_book_exit_on_stop=True: one trigger flushes every same-direction position."""
    engine = _build_engine(EngineConfig(
        max_loss=1e9, intrabar_stop_check=True, whole_book_exit_on_stop=True,
    ))
    # Three pyramid adds with progressively wider stops; only level 1 will trigger.
    _seed_position(engine, lots=5, stop_level=21950.0, pyramid_level=1)
    _seed_position(engine, lots=5, stop_level=21800.0, pyramid_level=2)
    _seed_position(engine, lots=5, stop_level=21700.0, pyramid_level=3)
    snap = _snapshot(price=21960.0, bar_low=21940.0, bar_high=22000.0)
    orders = engine._check_stops(snap)  # type: ignore[attr-defined]
    assert len(orders) == 3, f"all 3 long positions should exit, got {len(orders)}"


def test_min_hold_lots_shields_level_zero_under_whole_book_exit() -> None:
    """Even with whole-book exit, level-0 must survive when min_hold_lots > 0."""
    engine = _build_engine(EngineConfig(
        max_loss=1e9, min_hold_lots=1.0,
        intrabar_stop_check=True, whole_book_exit_on_stop=True,
    ))
    _seed_position(engine, lots=5, stop_level=21000.0, pyramid_level=0)  # base, sheltered
    _seed_position(engine, lots=5, stop_level=21950.0, pyramid_level=1)  # will trigger
    _seed_position(engine, lots=5, stop_level=21800.0, pyramid_level=2)  # whole-book sweep
    snap = _snapshot(price=21960.0, bar_low=21940.0, bar_high=22000.0)
    orders = engine._check_stops(snap)  # type: ignore[attr-defined]
    # Level 0 must NOT be exited (min_hold_lots shield).
    assert len(orders) == 2
    levels = sorted(o.metadata["pyramid_level"] for o in orders)
    assert levels == [1, 2]


def test_stop_fill_at_level_emits_override_metadata() -> None:
    """stop_fill_at_level=True: order metadata carries fill_price_override = stop_level - min_tick."""
    engine = _build_engine(EngineConfig(
        max_loss=1e9, intrabar_stop_check=True, stop_fill_at_level=True,
    ))
    _seed_position(engine, lots=10, stop_level=21900.0)
    snap = _snapshot(price=21950.0, bar_low=21850.0, bar_high=22000.0)
    orders = engine._check_stops(snap)  # type: ignore[attr-defined]
    assert len(orders) == 1
    override = orders[0].metadata.get("fill_price_override")
    assert override is not None
    # Long exit fills one tick below stop_level.
    assert override == pytest.approx(21900.0 - 1.0)


def test_stop_fill_at_level_requires_intrabar_check_validation() -> None:
    """stop_fill_at_level=True without intrabar_stop_check raises at construction."""
    with pytest.raises(ValueError, match="stop_fill_at_level requires intrabar_stop_check"):
        EngineConfig(max_loss=1e9, stop_fill_at_level=True)


# ---------------------------------------------------------------------------
# Follow-up coverage (architect review): short-direction, fallback, mixed-book.
# ---------------------------------------------------------------------------
def _seed_short(engine: PositionEngine, *, lots: float, stop_level: float,
                pyramid_level: int = 0, entry_ts: datetime | None = None) -> Position:
    pos = Position(
        entry_price=22000.0,
        lots=lots,
        contract_type="large",
        stop_level=stop_level,
        pyramid_level=pyramid_level,
        entry_timestamp=entry_ts or datetime(2025, 6, 10, 13, 30),
        direction="short",
    )
    engine._positions.append(pos)  # type: ignore[attr-defined]
    return pos


def test_intrabar_short_bar_high_pierces_stop() -> None:
    """Short positions trigger when bar_high pierces stop (mirror of long path)."""
    engine = _build_engine(EngineConfig(max_loss=1e9, intrabar_stop_check=True))
    _seed_short(engine, lots=10, stop_level=22050.0)
    snap = _snapshot(price=22000.0, bar_low=21950.0, bar_high=22100.0)
    orders = engine._check_stops(snap)  # type: ignore[attr-defined]
    assert len(orders) == 1
    assert orders[0].side == "buy", "short exit must be a buy"
    assert orders[0].lots == 10.0


def test_short_stop_fill_at_level_fills_one_tick_above_stop() -> None:
    """Short fill override = stop_level + min_tick (worst-case for the trader)."""
    engine = _build_engine(EngineConfig(
        max_loss=1e9, intrabar_stop_check=True, stop_fill_at_level=True,
    ))
    _seed_short(engine, lots=5, stop_level=22050.0)
    snap = _snapshot(price=22000.0, bar_low=21950.0, bar_high=22100.0)
    orders = engine._check_stops(snap)  # type: ignore[attr-defined]
    assert orders[0].metadata["fill_price_override"] == pytest.approx(22050.0 + 1.0)


def test_whole_book_exit_isolates_to_triggering_direction() -> None:
    """Mixed long+short book: a long stop trigger only flushes longs, not shorts."""
    engine = _build_engine(EngineConfig(
        max_loss=1e9, intrabar_stop_check=True, whole_book_exit_on_stop=True,
    ))
    _seed_position(engine, lots=5, stop_level=21950.0, pyramid_level=1)  # long, will trigger
    _seed_position(engine, lots=5, stop_level=21800.0, pyramid_level=2)  # long, swept by whole-book
    _seed_short(engine, lots=3, stop_level=22500.0, pyramid_level=1)     # short, must survive
    snap = _snapshot(price=21960.0, bar_low=21940.0, bar_high=22000.0)
    orders = engine._check_stops(snap)  # type: ignore[attr-defined]
    assert len(orders) == 2
    sides = {o.side for o in orders}
    assert sides == {"sell"}, f"only longs should exit, got sides={sides}"


def test_intrabar_falls_back_to_close_when_bar_low_is_none() -> None:
    """When bar_low is None (no OHLC data), use snapshot.price for the trigger."""
    engine = _build_engine(EngineConfig(max_loss=1e9, intrabar_stop_check=True))
    _seed_position(engine, lots=5, stop_level=21900.0)
    # bar_low is None — strategy would need to fall back to snapshot.price.
    # Price 21950 > stop, so fallback should NOT trigger.
    snap_above = _snapshot(price=21950.0, bar_low=None, bar_high=None)
    assert engine._check_stops(snap_above) == []  # type: ignore[attr-defined]
    # Price 21850 <= stop, fallback DOES trigger.
    snap_below = _snapshot(price=21850.0, bar_low=None, bar_high=None)
    orders = engine._check_stops(snap_below)  # type: ignore[attr-defined]
    assert len(orders) == 1


def test_initial_stop_loss_reason_when_not_trailing() -> None:
    """If pos.stop_level == initial_stop, reason is 'stop_loss', not 'trailing_stop'."""
    engine = _build_engine(EngineConfig(max_loss=1e9, intrabar_stop_check=True))
    # _NoStopPolicy.initial_stop returns entry_price - 1000 = 21000 for a 22000 entry.
    # If we seed at exactly that level, _is_trailing returns False.
    _seed_position(engine, lots=5, stop_level=21000.0)
    snap = _snapshot(price=21500.0, bar_low=20950.0, bar_high=21600.0)
    orders = engine._check_stops(snap)  # type: ignore[attr-defined]
    assert len(orders) == 1
    assert orders[0].reason == "stop_loss"
