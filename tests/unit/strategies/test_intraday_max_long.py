"""Unit tests for the intraday_max_long 當沖 strategy.

Covers:
- Sizing: lots = min(position_cap, floor(margin_available / intraday_margin))
- Single-shot: re-arm only on a new trading day
- Day-session gate: rejects entries before 08:45 / after 13:30 / in night
- Entry-time gate: no entry before configured ``entry_time``
- Halted engine: no entry
- Strategy meta: daytrade / half_exit_at / force_flat_at_session_end
- Decision metadata carries METADATA_STRATEGY_SIZED + intraday margin
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.core.types import (
    METADATA_STRATEGY_SIZED,
    AccountState,
    ContractSpecs,
    EngineState,
    MarketSnapshot,
    TradingHours,
)
from src.strategies import HoldingPeriod, SignalTimeframe, StopArchitecture
from src.strategies.short_term.breakout.intraday_max_long import (
    IntradayMaxLongEntryPolicy,
    PARAM_SCHEMA,
    STRATEGY_META,
    create_intraday_max_long_engine,
)


_TZ = timezone(timedelta(hours=8))


def _specs() -> ContractSpecs:
    return ContractSpecs(
        symbol="TX", exchange="TAIFEX", currency="TWD",
        point_value=200.0, margin_initial=184_000.0, margin_maintenance=140_000.0,
        min_tick=1.0,
        trading_hours=TradingHours(open_time="08:45", close_time="13:45", timezone="Asia/Taipei"),
        fee_per_contract=100.0, tax_rate=0.00002, lot_types={"large": 1.0},
    )


def _snap(ts: datetime, price: float = 20_000.0) -> MarketSnapshot:
    return MarketSnapshot(
        price=price, atr={"daily": 200.0}, timestamp=ts,
        margin_per_unit=184_000.0, point_value=200.0, min_lot=1.0,
        contract_specs=_specs(), volume=1.0,
    )


def _account(equity: float = 4_000_000.0) -> AccountState:
    return AccountState(
        equity=equity, unrealized_pnl=0.0, realized_pnl=0.0,
        margin_used=0.0, margin_available=equity,
        margin_ratio=0.0, drawdown_pct=0.0, positions=[],
        timestamp=datetime(2026, 4, 27, 8, 50, tzinfo=_TZ),
    )


def _state() -> EngineState:
    return EngineState(positions=(), pyramid_level=0, mode="normal", total_unrealized_pnl=0.0)


# ---------------------------------------------------------------------------
# Strategy meta — these declarations are the contract with the runner
# ---------------------------------------------------------------------------

def test_strategy_meta_declares_daytrade_and_half_exit_and_no_force_flat():
    assert STRATEGY_META["daytrade"] is True
    assert STRATEGY_META["half_exit_at"] == "13:20"
    assert STRATEGY_META["force_flat_at_session_end"] is False
    assert STRATEGY_META["tradeable_sessions"] == ["day"]
    assert STRATEGY_META["holding_period"] == HoldingPeriod.SHORT_TERM
    assert STRATEGY_META["signal_timeframe"] == SignalTimeframe.ONE_MIN
    assert STRATEGY_META["stop_architecture"] == StopArchitecture.INTRADAY


def test_param_schema_keys():
    assert set(PARAM_SCHEMA.keys()) == {
        "intraday_margin_per_contract", "position_cap", "entry_time",
    }


# ---------------------------------------------------------------------------
# Sizing
# ---------------------------------------------------------------------------

def test_sizing_capped_at_position_cap():
    """4M / 92k = 43; default cap = 30 → expect 30 lots."""
    policy = IntradayMaxLongEntryPolicy()
    snap = _snap(datetime(2026, 4, 27, 8, 50, tzinfo=_TZ))
    decision = policy.should_enter(snap, signal=None, engine_state=_state(), account=_account())
    assert decision is not None
    assert decision.lots == 30.0
    assert decision.metadata[METADATA_STRATEGY_SIZED] is True
    assert decision.metadata["intraday_margin_per_contract"] == 92_000.0
    assert decision.metadata["max_by_bp"] == 43


def test_sizing_falls_below_cap_for_small_account():
    """1M / 92k = 10; cap = 30 → expect 10 lots."""
    policy = IntradayMaxLongEntryPolicy()
    snap = _snap(datetime(2026, 4, 27, 8, 50, tzinfo=_TZ))
    decision = policy.should_enter(snap, signal=None, engine_state=_state(), account=_account(equity=1_000_000.0))
    assert decision is not None
    assert decision.lots == 10.0


def test_sizing_returns_none_when_account_cannot_afford_one_contract():
    policy = IntradayMaxLongEntryPolicy()
    snap = _snap(datetime(2026, 4, 27, 8, 50, tzinfo=_TZ))
    tiny_account = _account(equity=10_000.0)  # 10k < 92k margin per contract
    decision = policy.should_enter(snap, signal=None, engine_state=_state(), account=tiny_account)
    assert decision is None


# ---------------------------------------------------------------------------
# Time gates
# ---------------------------------------------------------------------------

def test_entry_time_gate_blocks_early_bars():
    policy = IntradayMaxLongEntryPolicy(entry_time="09:00")
    early = _snap(datetime(2026, 4, 27, 8, 50, tzinfo=_TZ))
    assert policy.should_enter(early, signal=None, engine_state=_state(), account=_account()) is None


def test_night_session_blocked():
    policy = IntradayMaxLongEntryPolicy()
    night = _snap(datetime(2026, 4, 27, 22, 0, tzinfo=_TZ))
    assert policy.should_enter(night, signal=None, engine_state=_state(), account=_account()) is None


def test_post_close_blocked():
    policy = IntradayMaxLongEntryPolicy()
    after = _snap(datetime(2026, 4, 27, 13, 35, tzinfo=_TZ))
    assert policy.should_enter(after, signal=None, engine_state=_state(), account=_account()) is None


# ---------------------------------------------------------------------------
# Single-shot per day
# ---------------------------------------------------------------------------

def test_single_shot_same_day():
    policy = IntradayMaxLongEntryPolicy()
    snap = _snap(datetime(2026, 4, 27, 8, 50, tzinfo=_TZ))
    first = policy.should_enter(snap, signal=None, engine_state=_state(), account=_account())
    assert first is not None
    second = policy.should_enter(snap, signal=None, engine_state=_state(), account=_account())
    assert second is None


def test_re_arms_on_new_day():
    policy = IntradayMaxLongEntryPolicy()
    day1 = _snap(datetime(2026, 4, 27, 8, 50, tzinfo=_TZ))
    day2 = _snap(datetime(2026, 4, 28, 8, 50, tzinfo=_TZ))
    assert policy.should_enter(day1, signal=None, engine_state=_state(), account=_account()) is not None
    assert policy.should_enter(day2, signal=None, engine_state=_state(), account=_account()) is not None


# ---------------------------------------------------------------------------
# Engine state gates
# ---------------------------------------------------------------------------

def test_halted_engine_blocks_entry():
    policy = IntradayMaxLongEntryPolicy()
    snap = _snap(datetime(2026, 4, 27, 8, 50, tzinfo=_TZ))
    halted = EngineState(positions=(), pyramid_level=0, mode="halted", total_unrealized_pnl=0.0)
    assert policy.should_enter(snap, signal=None, engine_state=halted, account=_account()) is None


def test_open_position_blocks_re_entry():
    """Even if the day re-arm latch is clear, an existing engine position
    must block re-entry — the strategy is single-shot per session."""
    from src.core.types import Position

    policy = IntradayMaxLongEntryPolicy()
    snap = _snap(datetime(2026, 4, 27, 8, 50, tzinfo=_TZ))
    pos = Position(
        entry_price=20_000.0, lots=30.0, contract_type="large",
        stop_level=10_000.0, pyramid_level=0,
        entry_timestamp=snap.timestamp, direction="long",
    )
    state = EngineState(positions=(pos,), pyramid_level=1, mode="normal", total_unrealized_pnl=0.0)
    assert policy.should_enter(snap, signal=None, engine_state=state, account=_account()) is None


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def test_create_engine_uses_relaxed_margin_limit():
    engine = create_intraday_max_long_engine()
    # 0.95 keeps the safety net but doesn't trim a near-max 當沖 position.
    assert engine._config.margin_limit == pytest.approx(0.95)
    assert engine._config.disaster_stop_enabled is False
