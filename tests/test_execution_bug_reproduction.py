"""Reproduction test for night_session_long multi-entry bug.

This test demonstrates that when a LiveStrategyRunner is recreated mid-session
(simulating broker reconnect or sync_pipeline flicker), the strategy's
_entered_this_session guard is reset, allowing multiple entries in the same
session.

Expected behavior: max 1 entry per night session
Observed behavior in live: 14x overtrading (84 fills over 3 days vs 2 expected)
"""
from __future__ import annotations

import asyncio
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from src.broker_gateway.live_bar_store import MinuteBar
from src.execution.live_strategy_runner import LiveStrategyRunner
from src.core.sizing import SizingConfig, PortfolioSizer
from src.core.types import ContractSpecs, TradingHours


TAIPEI_TZ = ZoneInfo("Asia/Taipei")


class MockBrokerAPI:
    """Minimal mock broker API for testing."""
    def __init__(self):
        self.orders = []


class MockExecutionEventLoop:
    """Mock event loop for testing."""
    pass


def load_tmf_bars_from_db(start_date: str, end_date: str) -> list[dict]:
    """Load real TMF bars from market.db for the specified date range.

    Args:
        start_date: ISO format date string (e.g. '2026-04-20')
        end_date: ISO format date string (e.g. '2026-04-22')

    Returns:
        List of bar dicts: {timestamp, open, high, low, close, volume}
    """
    conn = sqlite3.connect("data/market.db")
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    c.execute("""
        SELECT timestamp, open, high, low, close, volume
        FROM ohlcv_bars
        WHERE symbol='TMF'
        AND date(timestamp) >= ?
        AND date(timestamp) <= ?
        ORDER BY timestamp
    """, (start_date, end_date))

    bars = [dict(row) for row in c.fetchall()]
    conn.close()
    return bars


def parse_timestamp(ts_str: str) -> datetime:
    """Parse SQLite timestamp string to datetime with Taipei timezone."""
    dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TAIPEI_TZ)
    else:
        dt = dt.astimezone(TAIPEI_TZ)
    return dt


def get_night_session_key(ts: datetime) -> str:
    """Get the night session identifier for a given timestamp.

    Night sessions span 15:00 one day to 05:00 the next day.
    The session is identified by the calendar date of the 15:00 open.
    """
    from datetime import time as Time
    t = ts.time()
    d = ts.date()
    NIGHT_OPEN = Time(15, 0)
    if t >= NIGHT_OPEN:
        return d.isoformat()
    else:
        # After midnight, same session as previous calendar day
        return (d - timedelta(days=1)).isoformat()


@pytest.mark.asyncio
async def test_night_session_long_single_entry_per_session():
    """Test that night_session_long produces exactly 1 entry per session.

    This test reproduces the execution bug by:
    1. Loading real TMF bars from 2026-04-20 to 2026-04-22
    2. Creating a LiveStrategyRunner
    3. Replaying bars through the runner
    4. Tracking entries by session
    5. Asserting that exactly 1 entry occurs per session

    Note: This test should PASS if the bug is fixed. It should FAIL with
    the current code, showing > 1 entries per session.
    """
    # Load real bars
    bars_data = load_tmf_bars_from_db("2026-04-20", "2026-04-22")
    assert len(bars_data) > 0, "No bars found in database for the test period"

    # Convert to MinuteBar objects
    bars = [
        MinuteBar(
            timestamp=parse_timestamp(b["timestamp"]),
            open=float(b["open"]),
            high=float(b["high"]),
            low=float(b["low"]),
            close=float(b["close"]),
            volume=int(b["volume"]),
        )
        for b in bars_data
    ]

    print(f"\nLoaded {len(bars)} bars, spanning {bars[0].timestamp.date()} to {bars[-1].timestamp.date()}")

    # Create contract specs for TMF
    contract_specs = ContractSpecs(
        symbol="TMF",
        exchange="TAIFEX",
        currency="TWD",
        point_value=100.0,
        margin_initial=50000.0,
        margin_maintenance=40000.0,
        min_tick=1.0,
        trading_hours=TradingHours(
            open_time="08:45",
            close_time="13:45",
            timezone="Asia/Taipei"
        ),
        fee_per_contract=40.0,
        tax_rate=0.00002,
        lot_types={"large": 100.0, "small": 50.0},
    )

    # Create sizing config (use defaults, only override kelly_fraction)
    sizing_config = SizingConfig(
        risk_per_trade=0.02,
        margin_cap=0.50,
        max_lots=10,
        kelly_fraction=0.25,
        use_kelly=False,
    )
    sizer = PortfolioSizer(sizing_config)

    # Create the runner with active parameters for night_session_long
    # These are the parameters from the live portfolio "TMF Max Sharpe 28/62/10"
    session_id = "test-session-night-long"
    runner = LiveStrategyRunner(
        session_id=session_id,
        account_id="test-account",
        strategy_slug="short_term/trend_following/night_session_long",
        symbol="TMF",
        equity_budget=2_000_000.0,
        strategy_params={
            "breakeven_enabled": 1,
            "breakeven_trigger_atr": 0.5,
            "atr_sl_mult": 1.0,
            "entry_offset_min": 30,
            "exit_before_close_min": 5,
        },
        sizing_config=sizing_config,
        sizer=sizer,
        execution_mode="paper",
    )

    # Track entries by session
    entries_by_session: dict[str, int] = {}
    all_fills: list[tuple[str, datetime]] = []  # (session_key, timestamp)

    async def replay_bars():
        """Replay bars and track entries."""
        for i, bar in enumerate(bars):
            # Simulate mid-session runner recreation at bar 500 (approximately mid-session)
            # This tests whether runner recreation preserves the entry guard
            if i == 500:
                print(f"\n[Bar {i}] Simulating runner recreation at {bar.timestamp}")
                # Recreate the runner to simulate a broker reconnect or sync_pipeline flicker
                old_engine = runner._engine

                # Rebuild components (this destroys the old policy object)
                new_engine, new_executor, new_exec_engine = runner._build_components(None)
                runner._engine = new_engine
                runner._executor = new_executor
                runner._paper_engine = new_exec_engine

                print(f"  Old engine object: {id(old_engine)}")
                print(f"  New engine object: {id(new_engine)}")

            # Call on_bar_complete and collect fill results
            results = await runner.on_bar_complete("TMF", bar)

            # Track entries from fill results
            for result in results:
                if result.order.reason == "entry":
                    session_key = get_night_session_key(bar.timestamp)
                    entries_by_session[session_key] = entries_by_session.get(session_key, 0) + 1
                    all_fills.append((session_key, bar.timestamp))
                    print(f"  Entry #{entries_by_session[session_key]} in session {session_key} at {bar.timestamp} (bar {i})")

    # Run the replay
    await replay_bars()

    # Assertions
    print(f"\n=== TEST RESULTS ===")
    print(f"Total fills: {len(all_fills)}")
    print(f"Entries by session:")
    for session_key in sorted(entries_by_session.keys()):
        count = entries_by_session[session_key]
        print(f"  {session_key}: {count} entries")

    # The bug manifests as multiple entries per session
    # With the bug fixed, there should be exactly 1 entry per session
    max_entries_per_session = max(entries_by_session.values()) if entries_by_session else 0

    assert max_entries_per_session <= 1, (
        f"BUG DETECTED: {max_entries_per_session} entries in a single session "
        f"(expected max 1). This confirms the runner recreation destroys the "
        f"_entered_this_session guard. Total fills: {len(all_fills)}"
    )

    print(f"\n✓ PASS: At most 1 entry per session (max={max_entries_per_session})")


@pytest.mark.asyncio
async def test_night_session_long_without_recreation():
    """Test baseline: without runner recreation, entries should be limited."""
    bars_data = load_tmf_bars_from_db("2026-04-20", "2026-04-22")
    assert len(bars_data) > 0

    bars = [
        MinuteBar(
            timestamp=parse_timestamp(b["timestamp"]),
            open=float(b["open"]),
            high=float(b["high"]),
            low=float(b["low"]),
            close=float(b["close"]),
            volume=int(b["volume"]),
        )
        for b in bars_data
    ]

    contract_specs = ContractSpecs(
        symbol="TMF",
        exchange="TAIFEX",
        currency="TWD",
        point_value=100.0,
        margin_initial=50000.0,
        margin_maintenance=40000.0,
        min_tick=1.0,
        trading_hours=TradingHours(
            open_time="08:45",
            close_time="13:45",
            timezone="Asia/Taipei"
        ),
        fee_per_contract=40.0,
        tax_rate=0.00002,
        lot_types={"large": 100.0, "small": 50.0},
    )

    sizing_config = SizingConfig(
        risk_per_trade=0.02,
        margin_cap=0.50,
        max_lots=10,
        kelly_fraction=0.25,
        use_kelly=False,
    )
    sizer = PortfolioSizer(sizing_config)

    runner = LiveStrategyRunner(
        session_id="test-baseline",
        account_id="test-account",
        strategy_slug="short_term/trend_following/night_session_long",
        symbol="TMF",
        equity_budget=2_000_000.0,
        strategy_params={
            "breakeven_enabled": 1,
            "breakeven_trigger_atr": 0.5,
            "atr_sl_mult": 1.0,
            "entry_offset_min": 30,
            "exit_before_close_min": 5,
        },
        sizing_config=sizing_config,
        sizer=sizer,
        execution_mode="paper",
    )

    entries_by_session: dict[str, int] = {}

    async def replay():
        for bar in bars:
            results = await runner.on_bar_complete("TMF", bar)
            for result in results:
                if result.order.reason == "entry":
                    session_key = get_night_session_key(bar.timestamp)
                    entries_by_session[session_key] = entries_by_session.get(session_key, 0) + 1

    await replay()

    print(f"\n=== BASELINE TEST (no recreation) ===")
    print(f"Entries by session (expected max 1):")
    for session_key in sorted(entries_by_session.keys()):
        print(f"  {session_key}: {entries_by_session[session_key]}")

    # Even without recreation, we expect at most 1 entry per session
    max_entries = max(entries_by_session.values()) if entries_by_session else 0
    assert max_entries <= 1, f"Baseline test failed: {max_entries} entries in a session"
    print(f"✓ PASS: Baseline respects 1 entry/session limit")
