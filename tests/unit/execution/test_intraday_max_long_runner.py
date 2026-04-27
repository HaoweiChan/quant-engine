"""End-to-end test of the intraday_max_long runner against the paper executor.

Verifies:
- Entry at 08:50 fires once with daytrade=True for max-allowed lots
- No spurious orders mid-session (margin_safety doesn't trim under the
  intraday-margin override)
- Half-exit at 13:20 fires once with daytrade=True and ceil(lots/2) qty
- Half-exit is one-shot per day (no re-fire at 13:25)
- The 13:44 force-flat safety net is suppressed (force_flat_at_session_end
  meta opt-out works), so the kept half rides past session close
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import pytest

from src.broker_gateway.live_bar_store import MinuteBar
from src.core.sizing import SizingConfig
from src.execution.live_strategy_runner import LiveStrategyRunner


_TZ = timezone(timedelta(hours=8))


@pytest.fixture(autouse=True)
def _silence_db_warning(caplog):
    """The runner's per-session daily-ATR cache logs a debug warning when
    the local market.db lacks a ``timeframe_minutes`` column. That's
    benign for this paper-mode test; suppress it to keep CI logs quiet.
    """
    caplog.set_level(logging.ERROR)


def _bar(hh: int, mm: int, close: float = 20_000.0) -> MinuteBar:
    return MinuteBar(
        timestamp=datetime(2026, 4, 27, hh, mm, tzinfo=_TZ),
        open=close - 5, high=close + 5, low=close - 5, close=close, volume=100,
    )


@pytest.fixture
def runner() -> LiveStrategyRunner:
    return LiveStrategyRunner(
        session_id="intraday-max-test",
        account_id="4M-account",
        strategy_slug="short_term/breakout/intraday_max_long",
        symbol="TX",
        equity_budget=4_000_000.0,
        sizing_config=SizingConfig(
            risk_per_trade=0.02, margin_cap=0.95, max_lots=100, min_lots=1,
        ),
        execution_mode="paper",
    )


def test_runner_meta_loaded_from_strategy(runner: LiveStrategyRunner):
    assert runner._meta_force_flat is False
    assert runner._meta_daytrade is True
    assert runner._meta_half_exit_at_min == 13 * 60 + 20
    assert runner._meta_intraday_margin == 92_000.0
    assert runner.force_flat_at_session_end is False


async def test_full_session_flow(runner: LiveStrategyRunner):
    # 08:50 entry — full position, daytrade-flagged
    res = await runner.on_bar_complete("TX", _bar(8, 50, close=20_005.0))
    positions = list(runner._engine.get_state().positions)
    assert len(positions) == 1
    assert positions[0].lots == 30.0
    assert positions[0].direction == "long"
    assert all(r.status == "filled" for r in res)
    assert all(r.order.daytrade for r in res)
    assert all(r.order.reason == "entry" for r in res)

    # 10:00 mid-session quiet
    res = await runner.on_bar_complete("TX", _bar(10, 0, close=20_022.0))
    assert res == []
    assert runner._engine.get_state().positions[0].lots == 30.0

    # 13:20 half-exit — exactly one partial_exit for half the lots
    res = await runner.on_bar_complete("TX", _bar(13, 20, close=20_100.0))
    partial = [r for r in res if r.order.reason == "partial_exit"]
    assert len(partial) == 1
    assert partial[0].order.daytrade is True
    assert partial[0].order.lots == 15.0
    assert partial[0].order.side == "sell"
    assert runner._engine.get_state().positions[0].lots == 15.0
    assert runner._half_exit_done is True

    # 13:25 — one-shot guarantee: half-exit must not re-fire
    res = await runner.on_bar_complete("TX", _bar(13, 25, close=20_103.0))
    assert [r for r in res if r.order.reason == "partial_exit"] == []
    assert runner._engine.get_state().positions[0].lots == 15.0

    # 13:44 — strategy meta opt-out suppresses the runner's session-close flatten
    await runner.on_bar_complete("TX", _bar(13, 44, close=20_100.0))
    assert runner._engine.get_state().positions[0].lots == 15.0


async def test_session_boundary_does_not_force_flat(runner: LiveStrategyRunner):
    """When a bar gap crosses a session boundary, the runner must still
    NOT force-flat the kept half (the explicit meta opt-out covers both
    the deterministic timer in LivePipelineManager AND this in-runner
    gap-detected boundary path)."""
    await runner.on_bar_complete("TX", _bar(8, 50, close=20_005.0))
    await runner.on_bar_complete("TX", _bar(13, 20, close=20_100.0))
    assert runner._engine.get_state().positions[0].lots == 15.0

    # Synthesise a bar from the next day session to trigger
    # is_new_session(). Without the meta opt-out this would
    # force-flatten the 15-lot kept half.
    next_day_bar = MinuteBar(
        timestamp=datetime(2026, 4, 28, 8, 51, tzinfo=_TZ),
        open=20_100, high=20_105, low=20_095, close=20_100, volume=10,
    )
    await runner.on_bar_complete("TX", next_day_bar)
    assert runner._engine.get_state().positions[0].lots == 15.0
