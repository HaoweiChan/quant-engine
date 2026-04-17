"""Unit tests for LivePipelineManager shared PortfolioSizer integration (US-008).

Verifies cross-runner exposure aggregation and push into the shared sizer,
without spinning up real broker / session / bar-store dependencies.
"""
from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from src.core.sizing import PortfolioSizer, SizingConfig, SizingMode
from src.execution.live_pipeline import LivePipelineManager


class _FakeRunner:
    """Minimal runner stub exposing the fields LivePipelineManager reads."""

    def __init__(
        self,
        session_id: str,
        strategy_slug: str,
        margin_used: float,
        account_id: str = "acct",
        equity: float = 1_000_000.0,
        symbol: str = "TX",
    ) -> None:
        self.session_id = session_id
        self.strategy_slug = strategy_slug
        self.margin_used = margin_used
        self.account_id = account_id
        self.equity = equity
        self.symbol = symbol


def _make_manager(
    portfolio_sizer: PortfolioSizer | None = None,
) -> LivePipelineManager:
    """Build a LivePipelineManager wired to mocks."""
    sm = MagicMock()
    bar_store = MagicMock()
    equity_store = MagicMock()
    return LivePipelineManager(
        session_manager=sm,
        bar_store=bar_store,
        equity_store=equity_store,
        portfolio_sizer=portfolio_sizer,
    )


class TestIterRunners:
    def test_iter_runners_returns_snapshot_list(self) -> None:
        """iter_runners() must return a list (not a live view) so kill-switch
        iteration is safe against concurrent _sync_runners mutation."""
        mgr = _make_manager()
        r1 = _FakeRunner("s1", "alpha", margin_used=0)
        mgr._runners = {"s1": r1}
        snapshot = mgr.iter_runners()
        # Mutating the manager's dict does not mutate the snapshot
        mgr._runners["s2"] = _FakeRunner("s2", "beta", margin_used=0)
        assert len(snapshot) == 1
        assert snapshot[0][0] == "s1"
        # New snapshot sees both
        assert len(mgr.iter_runners()) == 2


class TestAggregateOpenExposure:
    def test_empty_runners_returns_empty_dict(self) -> None:
        mgr = _make_manager()
        assert mgr.aggregate_open_exposure() == {}

    def test_sums_margin_across_runners(self) -> None:
        mgr = _make_manager()
        mgr._runners = {
            "s1": _FakeRunner("s1", "alpha", margin_used=100_000),
            "s2": _FakeRunner("s2", "beta", margin_used=200_000),
        }
        exposure = mgr.aggregate_open_exposure()
        assert exposure == {"alpha": 100_000.0, "beta": 200_000.0}

    def test_same_strategy_runners_sum_together(self) -> None:
        """Two runners for the same strategy slug → combined exposure."""
        mgr = _make_manager()
        mgr._runners = {
            "s1": _FakeRunner("s1", "alpha", margin_used=50_000),
            "s2": _FakeRunner("s2", "alpha", margin_used=75_000),
            "s3": _FakeRunner("s3", "beta", margin_used=30_000),
        }
        exposure = mgr.aggregate_open_exposure()
        assert exposure == {"alpha": 125_000.0, "beta": 30_000.0}

    def test_missing_margin_used_defaults_to_zero(self) -> None:
        """Runners without a margin_used attribute are treated as zero."""

        class _AncientRunner:
            session_id = "s1"
            strategy_slug = "old"
            account_id = "acct"
            symbol = "TX"
            # No margin_used attribute

        mgr = _make_manager()
        mgr._runners = {"s1": _AncientRunner()}  # type: ignore[dict-item]
        assert mgr.aggregate_open_exposure() == {"old": 0.0}


class TestRefreshPortfolioExposure:
    def test_noop_when_no_sizer_configured(self) -> None:
        """refresh_portfolio_exposure is safe to call without a sizer."""
        mgr = _make_manager(portfolio_sizer=None)
        mgr._runners = {"s1": _FakeRunner("s1", "alpha", margin_used=50_000)}
        # Should not raise
        mgr.refresh_portfolio_exposure()

    def test_pushes_exposure_to_sizer(self) -> None:
        sizer = PortfolioSizer(SizingConfig(portfolio_margin_cap=0.65))
        mgr = _make_manager(portfolio_sizer=sizer)
        mgr._runners = {
            "s1": _FakeRunner("s1", "alpha", margin_used=100_000),
            "s2": _FakeRunner("s2", "beta", margin_used=200_000),
        }
        mgr.refresh_portfolio_exposure()
        assert sizer.open_exposure == {"alpha": 100_000.0, "beta": 200_000.0}

    def test_refresh_updates_on_each_call(self) -> None:
        """State is mutable — second refresh replaces first."""
        sizer = PortfolioSizer()
        mgr = _make_manager(portfolio_sizer=sizer)
        mgr._runners = {"s1": _FakeRunner("s1", "alpha", margin_used=100_000)}
        mgr.refresh_portfolio_exposure()
        assert sizer.open_exposure == {"alpha": 100_000.0}

        mgr._runners["s1"].margin_used = 500_000
        mgr.refresh_portfolio_exposure()
        assert sizer.open_exposure == {"alpha": 500_000.0}


class TestSharedPoolEnforcement:
    """End-to-end sanity: with a shared sizer, combined exposure is honoured
    when sizing new orders — preventing combined margin from exceeding the
    global portfolio_margin_cap regardless of per-strategy budgets."""

    def test_simulated_fourth_strategy_blocked_when_pool_full(self) -> None:
        sizer = PortfolioSizer(SizingConfig(
            margin_cap=0.50,
            portfolio_margin_cap=0.65,
            max_lots=10,
            min_lots=1,
        ))
        mgr = _make_manager(portfolio_sizer=sizer)
        equity = 2_000_000.0

        # Three running strategies collectively eating 1.25M of 1.3M budget
        mgr._runners = {
            "s1": _FakeRunner("s1", "alpha", margin_used=500_000),
            "s2": _FakeRunner("s2", "beta", margin_used=500_000),
            "s3": _FakeRunner("s3", "gamma", margin_used=250_000),
        }
        mgr.refresh_portfolio_exposure()

        # A brand-new 4th strategy tries to enter — 50k headroom remains
        result = sizer.size_entry(
            equity=equity,
            stop_distance=20.0,
            point_value=200,
            margin_per_unit=184_000,
            strategy_slug="delta",
        )
        # floor(50k / 184k) = 0 → below min
        assert result.lots == 0.0

    def test_kelly_mode_with_shared_pool(self) -> None:
        """Kelly scaling applied first, then shared-pool cap floors further."""
        kelly_weights = {"alpha": 0.25, "beta": 0.30, "gamma": 0.20, "delta": 0.25}
        sizer = PortfolioSizer(SizingConfig(
            mode=SizingMode.KELLY_PORTFOLIO,
            kelly_weights=kelly_weights,
            margin_cap=0.50,
            portfolio_margin_cap=0.75,
            max_lots=20,
            min_lots=1,
        ))
        mgr = _make_manager(portfolio_sizer=sizer)
        mgr._runners = {
            "s1": _FakeRunner("s1", "alpha", margin_used=200_000),
            "s2": _FakeRunner("s2", "beta", margin_used=300_000),
        }
        mgr.refresh_portfolio_exposure()

        result = sizer.size_entry(
            equity=2_000_000,
            stop_distance=20.0,
            point_value=200,
            margin_per_unit=184_000,
            strategy_slug="gamma",
        )
        # Risk-lots cap: 2M * 0.02 / (20*200) = 10 → raw 10
        # Per-strat margin cap: 2M * 0.5 / 184k ≈ 5.43 → base = 5
        # Kelly weight gamma = 0.20 → scaled = 5.43 * 0.20 = 1.086
        # Portfolio cap slack: 2M * 0.75 - (200k + 300k) = 1M → floor(1M / 184k) = 5
        # Order-level min: floor(min(1.086, 5)) = floor(1.086) = 1
        assert result.lots == 1.0
        assert "kelly_scaled" in result.caps_applied


@pytest.mark.asyncio
async def test_dispatch_bar_refreshes_exposure_before_runner_tick() -> None:
    """_dispatch_bar calls refresh_portfolio_exposure BEFORE runner.on_bar_complete."""
    sizer = PortfolioSizer(SizingConfig())
    mgr = _make_manager(portfolio_sizer=sizer)

    call_order: list[str] = []

    class _RecordingRunner:
        session_id = "s1"
        strategy_slug = "alpha"
        account_id = "acct"
        symbol = "TX"
        margin_used = 0.0
        equity = 1_000_000.0

        async def on_bar_complete(self, _symbol: Any, _bar: Any) -> list:
            call_order.append("on_bar_complete")
            self.margin_used = 500_000
            return []

    runner = _RecordingRunner()
    mgr._runners = {"s1": runner}  # type: ignore[dict-item]

    # Wrap refresh to capture ordering
    original_refresh = mgr.refresh_portfolio_exposure

    def spy_refresh() -> None:
        call_order.append("refresh_portfolio_exposure")
        original_refresh()

    mgr.refresh_portfolio_exposure = spy_refresh  # type: ignore[method-assign]

    await mgr._dispatch_bar(runner, "TX", MagicMock(timestamp=MagicMock(isoformat=lambda: "x")))
    assert call_order == ["refresh_portfolio_exposure", "on_bar_complete"]
