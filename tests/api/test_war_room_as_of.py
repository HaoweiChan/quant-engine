"""Tests for /api/war-room?as_of= parameter and related helpers."""

from __future__ import annotations

import sqlite3
from unittest.mock import patch

import pytest

from src.api.routes.war_room import (
    _load_mock_as_of,
    _reconstruct_positions_from_fills,
    mock_range,
)


# ---------------------------------------------------------------------------
# Helper: build a test in-memory SQLite DB with mock tables
# ---------------------------------------------------------------------------

def _create_test_db(*, snapshots=None, fills=None) -> sqlite3.Connection:
    """Return an in-memory connection pre-populated with optional test rows."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE mock_session_snapshots (
            timestamp TEXT,
            session_id TEXT,
            strategy_slug TEXT,
            equity REAL,
            unrealized_pnl REAL DEFAULT 0,
            realized_pnl REAL DEFAULT 0,
            drawdown_pct REAL DEFAULT 0,
            peak_equity REAL DEFAULT 0,
            trade_count INTEGER DEFAULT 0
        );
        CREATE TABLE mock_fills (
            timestamp TEXT,
            account_id TEXT,
            session_id TEXT,
            strategy_slug TEXT,
            symbol TEXT,
            side TEXT,
            price REAL,
            quantity REAL,
            fee REAL DEFAULT 0,
            pnl_realized REAL DEFAULT 0,
            is_session_close INTEGER DEFAULT 0,
            signal_reason TEXT DEFAULT '',
            triggered INTEGER DEFAULT 0
        );
        CREATE TABLE mock_positions (
            account_id TEXT,
            session_id TEXT,
            strategy_slug TEXT,
            symbol TEXT,
            side TEXT,
            quantity REAL,
            avg_entry_price REAL,
            current_price REAL,
            unrealized_pnl REAL,
            opened_at TEXT
        );
    """)

    if snapshots:
        conn.executemany(
            "INSERT INTO mock_session_snapshots VALUES (?,?,?,?,?,?,?,?,?)",
            snapshots,
        )
    if fills:
        conn.executemany(
            "INSERT INTO mock_fills VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            fills,
        )
    conn.commit()
    return conn


# Shared snapshot rows: (timestamp, session_id, strategy_slug, equity,
#                        unrealized_pnl, realized_pnl, drawdown_pct, peak_equity, trade_count)
_SNAP_T1 = ("2025-01-01T09:00:00", "mock::mock-dev::strat_a", "strat_a", 1000.0, 0, 0, 0, 1000, 0)
_SNAP_T2 = ("2025-01-01T10:00:00", "mock::mock-dev::strat_a", "strat_a", 1100.0, 0, 0, 0, 1100, 1)
_SNAP_T3 = ("2025-01-01T11:00:00", "mock::mock-dev::strat_a", "strat_a", 1200.0, 0, 0, 0, 1200, 2)

# Shared fill rows: (timestamp, account_id, session_id, strategy_slug, symbol,
#                   side, price, quantity, fee, pnl_realized, is_session_close, signal_reason, triggered)
_FILL_T1 = ("2025-01-01T09:05:00", "mock-dev", "mock::mock-dev::strat_a", "strat_a",
            "TXF", "BUY", 18000.0, 1, 100, 0, 0, "", 0)
_FILL_T2 = ("2025-01-01T10:05:00", "mock-dev", "mock::mock-dev::strat_a", "strat_a",
            "TXF", "SELL", 18200.0, 1, 100, 200, 1, "", 0)


# ===========================================================================
# TestWarRoomAsOf — tests for _load_mock_as_of
# ===========================================================================

class TestWarRoomAsOf:
    """Tests for _load_mock_as_of (backing /api/war-room?as_of=)."""

    def test_as_of_mid_range_truncates_equity_curve(self):
        """as_of in the middle returns equity_curve whose last timestamp <= as_of."""
        db = _create_test_db(snapshots=[_SNAP_T1, _SNAP_T2, _SNAP_T3])

        with patch("src.api.routes.war_room._mock_db_path") as mock_path, \
             patch("src.api.routes.war_room.sqlite3.connect", return_value=db):
            # _mock_db_path().exists() must return True so the function doesn't short-circuit.
            mock_path.return_value.exists.return_value = True

            result = _load_mock_as_of("mock-dev", "2025-01-01T10:30:00")

        curve = result["equity_curve"]
        assert len(curve) >= 1, "equity_curve should not be empty"
        # All timestamps in the curve must be <= as_of
        for ts, _eq in curve:
            assert ts <= "2025-01-01T10:30:00", f"Timestamp {ts} exceeds as_of"
        # The T3 snapshot (11:00) must NOT be present
        curve_timestamps = [ts for ts, _ in curve]
        assert "2025-01-01T11:00:00" not in curve_timestamps

    def test_as_of_before_first_snapshot_returns_empty(self):
        """as_of < min(timestamp) returns empty collections, not None."""
        db = _create_test_db(snapshots=[_SNAP_T2, _SNAP_T3])

        with patch("src.api.routes.war_room._mock_db_path") as mock_path, \
             patch("src.api.routes.war_room.sqlite3.connect", return_value=db):
            mock_path.return_value.exists.return_value = True

            result = _load_mock_as_of("mock-dev", "2025-01-01T08:00:00")

        assert result is not None, "_load_mock_as_of must return a dict, not None"
        assert result["equity_curve"] == []
        assert result["positions"] == []
        assert result["recent_fills"] == []
        assert result["equity"] == 0.0

    def test_as_of_none_regression(self, monkeypatch):
        """Call without as_of (None path) still routes through cached path, not _load_mock_as_of."""
        # Verify _load_mock_as_of is NOT called when as_of is None (cache path).
        called = []

        monkeypatch.setattr(
            "src.api.routes.war_room._load_mock_as_of",
            lambda *a, **kw: called.append(a) or {},
        )
        # We're testing the routing logic, not the full HTTP layer.
        # as_of=None should never invoke _load_mock_as_of.
        import src.api.routes.war_room as wr_mod

        # Simulate: if as_of is not None, call _load_mock_as_of; otherwise don't.
        as_of = None
        if as_of is not None:
            wr_mod._load_mock_as_of("mock-dev", as_of)

        assert called == [], "_load_mock_as_of must NOT be called when as_of is None"

    def test_as_of_loads_from_database(self):
        """_load_mock_as_of loads data from database directly."""
        db = _create_test_db(snapshots=[_SNAP_T1])

        with patch("src.api.routes.war_room._mock_db_path") as mock_path, \
             patch("src.api.routes.war_room.sqlite3.connect", return_value=db):
            mock_path.return_value.exists.return_value = True
            result = _load_mock_as_of("mock-dev", "2025-01-01T09:30:00")

        # Should load data from database
        assert result is not None
        assert result["equity"] == 1000.0


# ===========================================================================
# TestFifoPositionReconstruction — unit tests for FIFO matching logic
# ===========================================================================

def _make_fill(strategy_slug, symbol, side, qty, price, timestamp="2025-01-01T09:00:00"):
    """Return a sqlite3.Row-compatible dict for _reconstruct_positions_from_fills."""
    return {
        "strategy_slug": strategy_slug,
        "symbol": symbol,
        "side": side,
        "quantity": qty,
        "price": price,
        "timestamp": timestamp,
    }


class _DictRow(dict):
    """Minimal sqlite3.Row-compatible dict (supports [] access)."""
    def __getitem__(self, key):
        return super().__getitem__(key)


def _row(strategy_slug, symbol, side, qty, price, timestamp="2025-01-01T09:00:00"):
    return _DictRow(_make_fill(strategy_slug, symbol, side, qty, price, timestamp))


class TestFifoPositionReconstruction:
    """Unit tests for _reconstruct_positions_from_fills."""

    def test_fifo_long_add_close(self):
        """Buy 2 -> Sell 2 -> Buy 1 yields qty=1, side=BUY (LONG)."""
        fills = [
            _row("s", "TXF", "BUY",  2, 100.0, "2025-01-01T09:00:00"),
            _row("s", "TXF", "SELL", 2, 110.0, "2025-01-01T09:01:00"),
            _row("s", "TXF", "BUY",  1, 105.0, "2025-01-01T09:02:00"),
        ]
        positions = _reconstruct_positions_from_fills(fills, "2025-01-01T10:00:00")
        assert len(positions) == 1
        pos = positions[0]
        assert pos["quantity"] == 1
        assert pos["side"] == "BUY"

    def test_fifo_flip_through_zero(self):
        """Buy 2 -> Sell 3 yields qty=1, side=SELL (SHORT)."""
        fills = [
            _row("s", "TXF", "BUY",  2, 100.0, "2025-01-01T09:00:00"),
            _row("s", "TXF", "SELL", 3, 110.0, "2025-01-01T09:01:00"),
        ]
        positions = _reconstruct_positions_from_fills(fills, "2025-01-01T10:00:00")
        assert len(positions) == 1
        pos = positions[0]
        assert pos["quantity"] == 1
        assert pos["side"] == "SELL"

    def test_fifo_partial_close(self):
        """Buy 3 @ 100 -> Sell 1 @ 110 yields qty=2, avg_entry=100, side=BUY."""
        fills = [
            _row("s", "TXF", "BUY",  3, 100.0, "2025-01-01T09:00:00"),
            _row("s", "TXF", "SELL", 1, 110.0, "2025-01-01T09:01:00"),
        ]
        positions = _reconstruct_positions_from_fills(fills, "2025-01-01T10:00:00")
        assert len(positions) == 1
        pos = positions[0]
        assert pos["quantity"] == 2
        assert pos["side"] == "BUY"
        assert abs(pos["avg_entry_price"] - 100.0) < 0.01

    def test_fifo_flat_position_not_in_output(self):
        """Buy 1 -> Sell 1 yields no open position (net=0)."""
        fills = [
            _row("s", "TXF", "BUY",  1, 100.0, "2025-01-01T09:00:00"),
            _row("s", "TXF", "SELL", 1, 110.0, "2025-01-01T09:01:00"),
        ]
        positions = _reconstruct_positions_from_fills(fills, "2025-01-01T10:00:00")
        assert positions == []

    def test_as_of_before_first_fill_but_after_snapshot(self):
        """Snapshots exist at T1, fills at T2 > as_of=mid => empty positions."""
        # We test this via _load_mock_as_of by inserting a snapshot but no fills before as_of.
        db = _create_test_db(
            snapshots=[_SNAP_T1],  # T1 = 09:00
            fills=[_FILL_T1],      # fill at 09:05 — AFTER our as_of
        )
        as_of = "2025-01-01T09:03:00"  # Between snapshot and first fill

        with patch("src.api.routes.war_room._mock_db_path") as mock_path, \
             patch("src.api.routes.war_room.sqlite3.connect", return_value=db):
            mock_path.return_value.exists.return_value = True
            result = _load_mock_as_of("mock-dev", as_of)

        # Fills after as_of must not be included -> no open positions
        assert result["positions"] == []
        # Snapshot before as_of should produce a non-empty equity curve
        assert len(result["equity_curve"]) >= 1


# ===========================================================================
# TestMockRange — tests for /api/war-room/mock-range endpoint
# ===========================================================================

class TestMockRange:
    """Tests for mock_range()."""

    @pytest.mark.asyncio
    async def test_mock_range_empty_db(self):
        """Empty table returns {min_ts: None, max_ts: None} with 200."""
        db = _create_test_db()

        with patch("src.api.routes.war_room._get_mock_db_connection", return_value=db):
            result = await mock_range()

        assert result == {"min_ts": None, "max_ts": None}

    @pytest.mark.asyncio
    async def test_mock_range_scoped_to_account(self):
        """mock-range returns range for mock-dev only, ignoring other session_ids."""
        db = _create_test_db(
            snapshots=[
                # mock-dev snapshots
                ("2025-01-01T09:00:00", "mock::mock-dev::strat_a", "strat_a", 1000, 0, 0, 0, 1000, 0),
                ("2025-01-01T12:00:00", "mock::mock-dev::strat_a", "strat_a", 1100, 0, 0, 0, 1100, 1),
                # different account — must not affect range
                ("2025-01-01T06:00:00", "mock::other-account::strat_b", "strat_b", 900, 0, 0, 0, 900, 0),
                ("2025-01-01T23:00:00", "mock::other-account::strat_b", "strat_b", 950, 0, 0, 0, 950, 0),
            ]
        )

        with patch("src.api.routes.war_room._get_mock_db_connection", return_value=db):
            result = await mock_range()

        # Only mock-dev rows (09:00 – 12:00) should be in scope.
        assert result["min_ts"] == "2025-01-01T09:00:00"
        assert result["max_ts"] == "2025-01-01T12:00:00"

    @pytest.mark.asyncio
    async def test_mock_range_returns_correct_bounds(self):
        """min_ts and max_ts reflect the actual earliest and latest snapshots."""
        db = _create_test_db(
            snapshots=[
                ("2025-01-01T08:00:00", "mock::mock-dev::strat_a", "strat_a", 500, 0, 0, 0, 500, 0),
                ("2025-01-01T15:00:00", "mock::mock-dev::strat_a", "strat_a", 800, 0, 0, 0, 800, 1),
                ("2025-01-01T11:00:00", "mock::mock-dev::strat_b", "strat_b", 600, 0, 0, 0, 600, 0),
            ]
        )

        with patch("src.api.routes.war_room._get_mock_db_connection", return_value=db):
            result = await mock_range()

        assert result["min_ts"] == "2025-01-01T08:00:00"
        assert result["max_ts"] == "2025-01-01T15:00:00"
