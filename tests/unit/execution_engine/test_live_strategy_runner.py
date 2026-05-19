"""Tests for LiveStrategyRunner's PortfolioSizer wiring.

Assertions:
  - The dead ``elif order.reason == "add":`` branch is removed from
    ``_apply_portfolio_sizing`` (engine tags adds as ``add_level_{N}``).
  - ``__init__`` attaches ``engine.add_sizer`` so multiplier metadata is
    resolved inside the engine, not in the runner's pass.
"""
from __future__ import annotations

import inspect
import sqlite3
from datetime import date
from datetime import datetime

from src.broker_gateway.live_bar_store import MinuteBar
from src.core.types import Order
from src.execution.engine import ExecutionResult
from src.execution import live_strategy_runner as runner_module


class TestDeadAddBranchRemoved:
    def test_apply_portfolio_sizing_has_no_add_reason_branch(self) -> None:
        """The legacy 'elif order.reason == "add":' branch must be gone."""
        source = inspect.getsource(runner_module.LiveStrategyRunner._apply_portfolio_sizing)
        assert 'order.reason == "add"' not in source, (
            "Dead branch still present in _apply_portfolio_sizing; "
            "engine tags adds as 'add_level_{N}' so the branch never matched."
        )


class TestDailyAtrFromHourlyRows:
    """Pin the 2026-05-15 regression: _compute_daily_atr queried a non-
    existent ``timeframe_minutes=1440`` column and silently fell back to
    100.0, pinning trail stops to ~70 pts and stopping out every donchian
    entry one bar later. The aggregation now lives in
    ``_atr_from_hourly_rows`` (pure function) and groups 1h bars by
    ``trading_day()``.
    """

    def test_returns_fallback_on_empty_rows(self) -> None:
        v = runner_module.LiveStrategyRunner._atr_from_hourly_rows([], lookback=14)
        assert v == 100.0

    def test_returns_fallback_with_only_one_trading_day(self) -> None:
        # All bars in one night session → only 1 trading day → cannot
        # compute a TR (needs prior day's close). Fall back to 100.0.
        rows = [
            ("2026-05-15 15:00:00.000000", 40000.0, 39900.0, 39950.0),
            ("2026-05-15 16:00:00.000000", 40010.0, 39920.0, 39960.0),
        ]
        v = runner_module.LiveStrategyRunner._atr_from_hourly_rows(rows, lookback=14)
        assert v == 100.0

    def test_realistic_atr_across_multiple_trading_days(self) -> None:
        """Three trading days with 100-pt ranges should yield ATR ≈ 100."""
        # Each tuple: (timestamp string, high, low, close). The hours
        # are placed during the day session so trading_day() maps each
        # row to the same calendar date.
        rows = []
        for d in (10, 11, 12):  # three consecutive day-session days
            ts = f"2026-05-{d:02d} 10:00:00.000000"
            rows.append((ts, 20100.0 + d, 20000.0 + d, 20050.0 + d))
            ts = f"2026-05-{d:02d} 11:00:00.000000"
            rows.append((ts, 20105.0 + d, 20005.0 + d, 20055.0 + d))
        atr = runner_module.LiveStrategyRunner._atr_from_hourly_rows(rows, lookback=14)
        # Daily H-L = 105 pts; |H - prev_close| could be larger when
        # day-to-day drift is added. Sanity check: at least 100 pts.
        assert atr >= 100.0
        assert atr < 250.0  # well below any pathological value

    def test_uses_latest_close_per_trading_day(self) -> None:
        # First trading day: high=40100, low=39900, last close=40050.
        # Second trading day: high=40300, low=40050, last close=40250.
        # TR_day2 = max(40300-40050, |40300-40050|, |40050-40050|) = 250.
        rows = [
            ("2026-05-10 09:00:00.000000", 40050.0, 39900.0, 39990.0),
            ("2026-05-10 12:00:00.000000", 40100.0, 39950.0, 40050.0),
            ("2026-05-11 09:00:00.000000", 40200.0, 40050.0, 40150.0),
            ("2026-05-11 13:00:00.000000", 40300.0, 40100.0, 40250.0),
        ]
        atr = runner_module.LiveStrategyRunner._atr_from_hourly_rows(rows, lookback=14)
        assert atr == 250.0

    def test_compute_daily_atr_falls_back_to_1m_when_1h_missing(self, tmp_path) -> None:
        """Live ATR must not return 100.0 just because derived 1h bars are stale.

        The live bar store updates ``ohlcv_bars`` first; aggregation tables can
        lag. This pins the May-2026 failure mode where a missing derived table
        quietly tightened ATR stops to 70 points.
        """
        db_path = tmp_path / "market.db"
        conn = sqlite3.connect(db_path)
        conn.execute(
            "CREATE TABLE ohlcv_bars (symbol TEXT, timestamp TEXT, high REAL, low REAL, close REAL)"
        )
        rows = [
            ("TMF", "2026-05-10 10:00:00", 20100.0, 20000.0, 20050.0),
            ("TMF", "2026-05-11 10:00:00", 20300.0, 20050.0, 20250.0),
        ]
        conn.executemany("INSERT INTO ohlcv_bars VALUES (?, ?, ?, ?, ?)", rows)
        conn.commit()
        conn.close()

        atr = runner_module.LiveStrategyRunner._compute_daily_atr(
            "TMF", date(2026, 5, 11), lookback=14, db_path=db_path,
        )
        assert atr == 250.0


class TestAddSizerWired:
    def test_runner_attaches_add_sizer_via_init(self) -> None:
        """__init__ calls _attach_add_sizer which sets engine.add_sizer."""
        # Smoke-check: the attach method exists and references add_sizer.
        method = runner_module.LiveStrategyRunner._attach_add_sizer
        source = inspect.getsource(method)
        assert "engine.add_sizer" in source or "self._engine.add_sizer" in source, (
            "LiveStrategyRunner._attach_add_sizer must wire engine.add_sizer."
        )
        # And __init__ invokes it.
        init_source = inspect.getsource(runner_module.LiveStrategyRunner.__init__)
        assert "_attach_add_sizer" in init_source, (
            "LiveStrategyRunner.__init__ must call _attach_add_sizer so live "
            "runs resolve exposure_multiplier metadata."
        )


class TestLiveRunnerPnlAccounting:
    def test_process_fills_deducts_executor_commission(self, monkeypatch) -> None:
        class _NoopActivityLogger:
            def log_trade(self, **_kwargs) -> None:
                return None

        monkeypatch.setattr(
            "src.trading_session.store.ActivityLogger",
            lambda: _NoopActivityLogger(),
        )
        runner = runner_module.LiveStrategyRunner(
            session_id="pnl-test",
            account_id="acct",
            strategy_slug="medium_term/trend_following/donchian_trend_strength",
            symbol="TMF",
            equity_budget=500_000.0,
            execution_mode="paper",
        )
        snapshot = runner._bar_to_snapshot(
            MinuteBar(
                timestamp=datetime(2026, 5, 19, 10, 0),
                open=20_100.0,
                high=20_100.0,
                low=20_100.0,
                close=20_100.0,
                volume=100,
            )
        )
        order = Order(
            order_type="market",
            side="sell",
            symbol="TMF",
            contract_type="large",
            lots=2,
            price=None,
            stop_price=None,
            reason="trailing_stop",
            metadata={"entry_price": 20_000.0},
        )
        result = ExecutionResult(
            order=order,
            status="filled",
            fill_price=20_100.0,
            expected_price=20_100.0,
            slippage=0.0,
            fill_qty=2,
            remaining_qty=0.0,
            metadata={"commission": 40.0},
        )

        runner._process_fills([result], snapshot)

        assert result.metadata["realized_pnl"] == 1_960.0
        assert runner._realized_pnl == 1_960.0
