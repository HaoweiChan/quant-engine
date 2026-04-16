"""Unit tests for Donchian Trend-Strength structural parameters.

Tests adaptive trailing stop, breakeven logic, and factory wiring.
"""
from __future__ import annotations

from collections import deque
from datetime import datetime

from src.core.types import (
    ContractSpecs,
    MarketSnapshot,
    Position,
    TradingHours,
)
from src.strategies.medium_term.trend_following.donchian_trend_strength import (
    DonchianTrendStrengthEntry,
    DonchianTrendStrengthStop,
    _Indicators,
    create_donchian_trend_strength_engine,
)

_TX_HOURS = TradingHours(open_time="08:45", close_time="13:45", timezone="Asia/Taipei")
_TX_SPECS = ContractSpecs(
    symbol="TX",
    exchange="TAIFEX",
    currency="TWD",
    point_value=200.0,
    margin_initial=184_000.0,
    margin_maintenance=141_000.0,
    min_tick=1.0,
    trading_hours=_TX_HOURS,
    fee_per_contract=50.0,
    tax_rate=0.00002,
    lot_types={"full": 1.0, "mini": 0.25},
)


def _make_snapshot(
    price: float,
    ts: datetime,
    daily_atr: float = 200.0,
    volume: float = 100.0,
) -> MarketSnapshot:
    return MarketSnapshot(
        price=price,
        timestamp=ts,
        volume=volume,
        atr={"daily": daily_atr},
        point_value=200.0,
        margin_per_unit=184_000.0,
        min_lot=1.0,
        contract_specs=_TX_SPECS,
    )


def _make_position(
    entry_price: float,
    direction: str = "long",
    stop_level: float = 0.0,
    position_id: str = "pos-1",
) -> Position:
    return Position(
        entry_price=entry_price,
        lots=1.0,
        contract_type="TX",
        stop_level=stop_level,
        pyramid_level=0,
        entry_timestamp=datetime(2025, 6, 1, 10, 0),
        direction=direction,
        position_id=position_id,
    )


def _warmed_indicators(n: int = 25, lookback: int = 20) -> _Indicators:
    """Return indicators with enough bars to produce Donchian / VWAP / RSI."""
    ind = _Indicators(lookback_period=lookback, rsi_len=5)
    base = 20000.0
    for i in range(n):
        ts = datetime(2025, 6, 1, 9, i)
        ind.update(base + i * 5, ts, 100.0, 200.0)
    return ind


class TestAdaptiveTrailingStop:
    """Verify trail_atr_multi tightens when profit exceeds profit_lock_atr."""

    def test_trail_tightens_when_profit_locked(self) -> None:
        ind = _warmed_indicators()
        stop = DonchianTrendStrengthStop(
            indicators=ind,
            atr_sl_multi=2.0,
            atr_tp_multi=4.0,
            trail_atr_multi=2.0,
            max_hold_bars=120,
            profit_lock_atr=1.0,
            locked_trail_ratio=0.5,
            breakeven_atr=0.0,
        )
        entry = 20000.0
        daily_atr = 200.0
        pos = _make_position(entry, "long", stop_level=entry - 400)
        snap_init = _make_snapshot(entry, datetime(2025, 6, 1, 10, 0), daily_atr)
        stop.initial_stop(entry, "long", snap_init)
        # Price moves > 1.0 * daily_atr (200) above entry → profit locked
        profit_price = entry + 250.0
        snap = _make_snapshot(profit_price, datetime(2025, 6, 1, 10, 15), daily_atr)
        new_stop = stop.update_stop(pos, snap, deque([profit_price]))
        # Tightened trail: price - daily_atr * (2.0 * 0.5) = 20250 - 200 = 20050
        expected_tight_trail = profit_price - daily_atr * 2.0 * 0.5
        assert new_stop >= expected_tight_trail

    def test_no_tightening_below_threshold(self) -> None:
        ind = _warmed_indicators()
        stop = DonchianTrendStrengthStop(
            indicators=ind,
            atr_sl_multi=2.0,
            atr_tp_multi=4.0,
            trail_atr_multi=2.0,
            max_hold_bars=120,
            profit_lock_atr=1.0,
            locked_trail_ratio=0.5,
            breakeven_atr=0.0,
        )
        entry = 20000.0
        daily_atr = 200.0
        pos = _make_position(entry, "long", stop_level=entry - 400)
        snap_init = _make_snapshot(entry, datetime(2025, 6, 1, 10, 0), daily_atr)
        stop.initial_stop(entry, "long", snap_init)
        # Price moves < 1.0 * daily_atr → no tightening
        small_profit_price = entry + 100.0
        snap = _make_snapshot(small_profit_price, datetime(2025, 6, 1, 10, 15), daily_atr)
        new_stop = stop.update_stop(pos, snap, deque([small_profit_price]))
        # Normal trail: price - daily_atr * 2.0 = 20100 - 400 = 19700
        normal_trail = small_profit_price - daily_atr * 2.0
        assert new_stop <= max(normal_trail, pos.stop_level)

    def test_disabled_when_zero(self) -> None:
        ind = _warmed_indicators()
        stop = DonchianTrendStrengthStop(
            indicators=ind,
            atr_sl_multi=2.0,
            atr_tp_multi=4.0,
            trail_atr_multi=2.0,
            max_hold_bars=120,
            profit_lock_atr=0.0,
            locked_trail_ratio=0.5,
            breakeven_atr=0.0,
        )
        entry = 20000.0
        daily_atr = 200.0
        pos = _make_position(entry, "long", stop_level=entry - 400)
        snap_init = _make_snapshot(entry, datetime(2025, 6, 1, 10, 0), daily_atr)
        stop.initial_stop(entry, "long", snap_init)
        profit_price = entry + 300.0
        snap = _make_snapshot(profit_price, datetime(2025, 6, 1, 10, 15), daily_atr)
        new_stop = stop.update_stop(pos, snap, deque([profit_price]))
        # With profit_lock_atr=0 (disabled), normal trail applies
        normal_trail = profit_price - daily_atr * 2.0
        assert new_stop <= max(normal_trail, pos.stop_level)


class TestBreakevenStop:
    """Verify stop ratchets to entry when profit > breakeven_atr * daily_atr."""

    def test_breakeven_activates_on_threshold(self) -> None:
        ind = _warmed_indicators()
        stop = DonchianTrendStrengthStop(
            indicators=ind,
            atr_sl_multi=2.0,
            atr_tp_multi=4.0,
            trail_atr_multi=2.0,
            max_hold_bars=120,
            profit_lock_atr=0.0,
            locked_trail_ratio=0.5,
            breakeven_atr=0.5,
        )
        entry = 20000.0
        daily_atr = 200.0
        initial_stop = entry - 400  # 2.0 * 200
        pos = _make_position(entry, "long", stop_level=initial_stop)
        snap_init = _make_snapshot(entry, datetime(2025, 6, 1, 10, 0), daily_atr)
        stop.initial_stop(entry, "long", snap_init)
        # Price moves > 0.5 * 200 = 100 above entry → breakeven floor = entry
        profit_price = entry + 150.0
        snap = _make_snapshot(profit_price, datetime(2025, 6, 1, 10, 15), daily_atr)
        new_stop = stop.update_stop(pos, snap, deque([profit_price]))
        # Stop must be at least at entry (breakeven)
        assert new_stop >= entry

    def test_breakeven_not_active_below_threshold(self) -> None:
        ind = _warmed_indicators()
        stop = DonchianTrendStrengthStop(
            indicators=ind,
            atr_sl_multi=2.0,
            atr_tp_multi=4.0,
            trail_atr_multi=2.0,
            max_hold_bars=120,
            profit_lock_atr=0.0,
            locked_trail_ratio=0.5,
            breakeven_atr=1.0,
        )
        entry = 20000.0
        daily_atr = 200.0
        initial_stop = entry - 400
        pos = _make_position(entry, "long", stop_level=initial_stop)
        snap_init = _make_snapshot(entry, datetime(2025, 6, 1, 10, 0), daily_atr)
        stop.initial_stop(entry, "long", snap_init)
        # Price moves only 100 < 1.0 * 200 → breakeven NOT active
        small_profit_price = entry + 100.0
        snap = _make_snapshot(small_profit_price, datetime(2025, 6, 1, 10, 15), daily_atr)
        new_stop = stop.update_stop(pos, snap, deque([small_profit_price]))
        # Trail = 20100 - 400 = 19700 which is below entry
        assert new_stop < entry

    def test_short_breakeven(self) -> None:
        ind = _warmed_indicators()
        stop = DonchianTrendStrengthStop(
            indicators=ind,
            atr_sl_multi=2.0,
            atr_tp_multi=4.0,
            trail_atr_multi=2.0,
            max_hold_bars=120,
            profit_lock_atr=0.0,
            locked_trail_ratio=0.5,
            breakeven_atr=0.5,
        )
        entry = 20000.0
        daily_atr = 200.0
        initial_stop = entry + 400
        pos = _make_position(entry, "short", stop_level=initial_stop)
        snap_init = _make_snapshot(entry, datetime(2025, 6, 1, 10, 0), daily_atr)
        stop.initial_stop(entry, "short", snap_init)
        # Price drops > 0.5 * 200 = 100 below entry → breakeven active
        profit_price = entry - 150.0
        snap = _make_snapshot(profit_price, datetime(2025, 6, 1, 10, 15), daily_atr)
        new_stop = stop.update_stop(pos, snap, deque([profit_price]))
        # For short, breakeven means stop ratchets DOWN to entry
        assert new_stop <= entry


class TestMaxHoldBarsTimeout:
    """Verify that max_hold_bars triggers a time exit."""

    def test_exit_on_max_hold(self) -> None:
        ind = _warmed_indicators()
        stop = DonchianTrendStrengthStop(
            indicators=ind,
            atr_sl_multi=2.0,
            atr_tp_multi=4.0,
            trail_atr_multi=2.0,
            max_hold_bars=3,
            profit_lock_atr=0.0,
            locked_trail_ratio=0.5,
            breakeven_atr=0.0,
        )
        entry = 20000.0
        daily_atr = 200.0
        pos = _make_position(entry, "long", stop_level=entry - 400)
        snap_init = _make_snapshot(entry, datetime(2025, 6, 1, 10, 0), daily_atr)
        stop.initial_stop(entry, "long", snap_init)
        # Tick through 3 bars — on the 3rd, stop should return current price (exit)
        for i in range(1, 4):
            snap = _make_snapshot(entry + 10, datetime(2025, 6, 1, 10, i), daily_atr)
            new_stop = stop.update_stop(pos, snap, deque([entry + 10]))
        # On bar 3 (max_hold_bars=3), stop == current price → forces exit
        assert new_stop == entry + 10


class TestFactoryWiresNewParams:
    """Verify create_donchian_trend_strength_engine passes structural params."""

    def test_factory_creates_engine(self) -> None:
        engine = create_donchian_trend_strength_engine(
            profit_lock_atr=1.5,
            locked_trail_ratio=0.6,
            breakeven_atr=1.0,
        )
        assert engine is not None
        stop = engine._stop_policy
        assert stop._profit_lock_atr == 1.5
        assert stop._locked_trail_ratio == 0.6
        assert stop._breakeven_atr == 1.0
