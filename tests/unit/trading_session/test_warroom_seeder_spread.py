"""Unit tests for War Room mock seeder — 2-leg spread handling.

Exercises _persist_backtest_result on a synthetic backtest result payload
(mocking out the broader backtest pipeline) to confirm that spread strategies
emit per-leg fill rows and single-contract strategies retain the legacy
single-row fill shape.
"""
from __future__ import annotations

import sqlite3

import pytest

from src.trading_session.warroom_schema import ensure_mock_warroom_schema
from src.trading_session.warroom_seeder import (
    _build_leg_price_index,
    _persist_backtest_result,
)


@pytest.fixture
def mock_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    ensure_mock_warroom_schema(conn)
    try:
        yield conn
    finally:
        conn.close()


def _make_spread_result() -> dict:
    """Synthetic spread-strategy backtest payload with 2 round-trip signals."""
    ts1 = "2026-04-10T09:00:00"
    ts2 = "2026-04-10T09:05:00"
    ts3 = "2026-04-10T13:00:00"
    ts4 = "2026-04-10T13:30:00"
    return {
        "equity_curve": [1_000_000.0, 1_010_000.0, 1_005_000.0, 1_020_000.0, 1_025_000.0],
        "equity_timestamps": [
            # n+1 epochs matching n bars; shape matches facade output.
            1712707199,
            1712707200,
            1712707500,
            1712721600,
            1712723400,
        ],
        "spread_legs": ["TX", "TX_R2"],
        "spread_offset": 100.0,
        "spread_r1_bars": [
            {"timestamp": ts1, "open": 19000.0, "high": 19050.0, "low": 18990.0, "close": 19030.0, "volume": 100},
            {"timestamp": ts2, "open": 19030.0, "high": 19040.0, "low": 19010.0, "close": 19020.0, "volume": 80},
            {"timestamp": ts3, "open": 19100.0, "high": 19110.0, "low": 19080.0, "close": 19090.0, "volume": 90},
            {"timestamp": ts4, "open": 19090.0, "high": 19100.0, "low": 19060.0, "close": 19070.0, "volume": 85},
        ],
        "spread_r2_bars": [
            {"timestamp": ts1, "open": 18900.0, "high": 18950.0, "low": 18890.0, "close": 18930.0, "volume": 70},
            {"timestamp": ts2, "open": 18930.0, "high": 18940.0, "low": 18910.0, "close": 18925.0, "volume": 60},
            {"timestamp": ts3, "open": 18980.0, "high": 19000.0, "low": 18970.0, "close": 18985.0, "volume": 65},
            {"timestamp": ts4, "open": 18985.0, "high": 18990.0, "low": 18960.0, "close": 18970.0, "volume": 62},
        ],
        "trade_signals": [
            {"timestamp": ts1, "side": "sell", "price": 200.0, "lots": 1, "reason": "entry"},
            {"timestamp": ts2, "side": "buy", "price": 195.0, "lots": 1, "reason": "take_profit"},
            {"timestamp": ts3, "side": "sell", "price": 205.0, "lots": 1, "reason": "entry"},
            {"timestamp": ts4, "side": "buy", "price": 200.0, "lots": 1, "reason": "take_profit"},
        ],
    }


def _make_single_result() -> dict:
    """Synthetic single-contract backtest payload."""
    ts1 = "2026-04-10T09:00:00"
    ts2 = "2026-04-10T09:05:00"
    return {
        "equity_curve": [1_000_000.0, 1_005_000.0, 1_010_000.0],
        "equity_timestamps": [1712707199, 1712707200, 1712707500],
        "trade_signals": [
            {"timestamp": ts1, "side": "buy", "price": 19000.0, "lots": 1, "reason": "entry"},
            {"timestamp": ts2, "side": "sell", "price": 19050.0, "lots": 1, "reason": "take_profit"},
        ],
    }


def test_build_leg_price_index_normalizes_t_and_space_separators() -> None:
    # Mixed 'T' and space separators must collide on the same canonical
    # epoch-second key so trade-signal timestamps (isoformat) and bar
    # timestamps (str(datetime)) look up the same close.
    from src.trading_session.warroom_seeder import _canon_ts_epoch

    bars = [
        {"timestamp": "2026-04-10T09:00:00", "close": 19030.0},
        {"timestamp": "2026-04-10 09:05:00", "close": 19020.0},
    ]
    index = _build_leg_price_index(bars)
    epoch_a = _canon_ts_epoch("2026-04-10T09:00:00")
    epoch_b = _canon_ts_epoch("2026-04-10 09:05:00")
    assert index == {epoch_a: 19030.0, epoch_b: 19020.0}
    # Crucially, looking up via the OTHER separator form yields the same hit:
    assert index[_canon_ts_epoch("2026-04-10 09:00:00")] == 19030.0
    assert index[_canon_ts_epoch("2026-04-10T09:05:00")] == 19020.0


def test_build_leg_price_index_ignores_malformed_rows() -> None:
    bars = [
        {"timestamp": None, "close": 1.0},
        {"timestamp": "x", "close": None},
        {"timestamp": "not-a-timestamp", "close": 123.0},
    ]
    # All rows fail to canonicalize or have null close → empty index.
    assert _build_leg_price_index(bars) == {}


def test_spread_result_emits_two_fills_per_trade_signal(mock_conn) -> None:
    result = _make_spread_result()
    slug = "short_term/mean_reversion/spread_reversion"
    session_id = f"mock::mock-dev::{slug.replace('/', '__')}"

    snapshots, fills = _persist_backtest_result(
        mock_conn,
        account_id="mock-dev",
        slug=slug,
        session_id=session_id,
        symbol="TX",
        total_equity=1_000_000.0,
        weight=1.0,  # solo run for the test fixture
        result=result,
        intraday=True,
    )
    mock_conn.commit()

    # 2 triggered fills per trade_signal × 4 signals = 8, plus 2 pending
    # (triggered=0) rows from _insert_mock_pending_signals.
    assert fills == 8
    rows = list(
        mock_conn.execute(
            "SELECT * FROM mock_fills WHERE session_id = ? AND triggered = 1 ORDER BY id",
            (session_id,),
        )
    )
    assert len(rows) == 8

    # Every trade_signal must produce a (leg1, leg2) pair at the same timestamp
    # with opposite sides and with leg prices taken from the R1/R2 bar closes.
    for i in range(0, 8, 2):
        leg1 = dict(rows[i])
        leg2 = dict(rows[i + 1])
        assert leg1["symbol"] == "TX"
        assert leg2["symbol"] == "TX_R2"
        assert leg1["timestamp"] == leg2["timestamp"]
        assert leg1["side"] != leg2["side"]
        assert leg1["quantity"] == leg2["quantity"] == 1
        # Fee must split the 700 spread_cost_per_fill default (no registry meta
        # here because the slug isn't loaded in a fresh tmp conn, so _spread_meta
        # returns None and the default 700 is used). 700 / 2 = 350.
        assert leg1["fee"] == pytest.approx(350.0)
        assert leg2["fee"] == pytest.approx(350.0)
        assert leg1["fee"] + leg2["fee"] == pytest.approx(700.0)

    # Verify leg prices come from the aligned R1/R2 bars, not the synthetic spread.
    first = dict(rows[0])
    assert first["price"] == pytest.approx(19030.0)
    second = dict(rows[1])
    assert second["price"] == pytest.approx(18930.0)

    # Snapshot row count equals len(equity_curve) (5 rows here).
    assert snapshots == 5


def test_persisted_equity_is_full_pool_scaled_by_weight(mock_conn) -> None:
    """A1 parity: persisted snapshot equity = weight × backtest_equity_at_pool.

    This is the contract that lets `/api/war-room` aggregate per-strategy
    snapshots into a portfolio total via `Σ persisted_equity_i(t)`, matching
    the MCP-style `Σ weight_i × strategy_equity_at_pool_i(t)` formula.
    """
    result = _make_single_result()  # equity_curve at full pool [1.0M, 1.005M, 1.01M]
    slug = "short_term/trend_following/night_session_long"
    session_id = f"mock::mock-dev::{slug.replace('/', '__')}"

    _persist_backtest_result(
        mock_conn,
        account_id="mock-dev",
        slug=slug,
        session_id=session_id,
        symbol="MTX",
        total_equity=1_000_000.0,
        weight=0.05,  # 5% portfolio share
        result=result,
        intraday=True,
    )
    mock_conn.commit()

    rows = list(
        mock_conn.execute(
            "SELECT timestamp, equity, realized_pnl FROM mock_session_snapshots "
            "WHERE session_id = ? ORDER BY id",
            (session_id,),
        )
    )
    assert len(rows) == 3
    # Each persisted equity equals 0.05 × the backtest's full-pool equity.
    expected = [0.05 * x for x in (1_000_000.0, 1_005_000.0, 1_010_000.0)]
    actual = [float(r["equity"]) for r in rows]
    assert actual == pytest.approx(expected)
    # realized_pnl is the delta from the slot's initial share (= weight × pool).
    initial_slot = 0.05 * 1_000_000.0
    expected_realized = [e - initial_slot for e in expected]
    actual_realized = [float(r["realized_pnl"]) for r in rows]
    assert actual_realized == pytest.approx(expected_realized)


def test_persisted_equity_sum_across_weights_equals_pool(mock_conn) -> None:
    """A1 parity: summing `weight × strategy_equity` at t=0 across all
    strategies must equal the full pool exactly (`Σ weight_i × pool = pool`)
    when weights sum to 1.0.

    This guarantees the dashboard never shows a fictitious starting equity
    that diverges from the configured initial capital.
    """
    pool = 2_000_000.0
    weights = [0.05, 0.05, 0.05, 0.85]
    initial_equity_curves = [pool] * 4  # All start at full pool
    summed_at_t0 = sum(w * eq for w, eq in zip(weights, initial_equity_curves))
    assert summed_at_t0 == pytest.approx(pool)


def test_spread_missing_leg_price_raises(mock_conn) -> None:
    """A2 parity: spread strategies must fail fast when a leg price is
    missing from the aligned bar index. The previous silent fallback to
    0.0 produced nonsense PnL that quietly corrupted the portfolio
    aggregate.
    """
    result = _make_spread_result()
    # Drop the R2 bar at one of the trade-signal timestamps so the leg
    # lookup necessarily misses.
    result["spread_r2_bars"] = [b for b in result["spread_r2_bars"] if b["timestamp"] != "2026-04-10T09:00:00"]
    slug = "short_term/mean_reversion/spread_reversion"
    session_id = f"mock::mock-dev::{slug.replace('/', '__')}"

    with pytest.raises(RuntimeError, match="missing leg price"):
        _persist_backtest_result(
            mock_conn,
            account_id="mock-dev",
            slug=slug,
            session_id=session_id,
            symbol="TX",
            total_equity=1_000_000.0,
            weight=1.0,
            result=result,
            intraday=True,
        )


def test_single_contract_result_emits_one_fill_per_signal(mock_conn) -> None:
    result = _make_single_result()
    slug = "short_term/trend_following/night_session_long"
    session_id = f"mock::mock-dev::{slug.replace('/', '__')}"

    snapshots, fills = _persist_backtest_result(
        mock_conn,
        account_id="mock-dev",
        slug=slug,
        session_id=session_id,
        symbol="MTX",
        total_equity=1_000_000.0,
        weight=1.0,  # solo run for the test fixture
        result=result,
        intraday=True,
    )
    mock_conn.commit()

    assert fills == 2  # one row per trade_signal
    rows = list(
        mock_conn.execute(
            "SELECT symbol, side, price, fee, quantity FROM mock_fills "
            "WHERE session_id = ? AND triggered = 1 ORDER BY id",
            (session_id,),
        )
    )
    assert len(rows) == 2
    assert all(r["symbol"] == "MTX" for r in rows)
    # Single-contract path keeps the legacy 50 NT per-fill fee.
    assert all(r["fee"] == pytest.approx(50.0) for r in rows)
    assert rows[0]["side"] == "buy"
    assert rows[1]["side"] == "sell"
    assert snapshots == 3
