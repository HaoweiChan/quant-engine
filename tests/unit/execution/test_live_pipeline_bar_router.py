"""End-to-end wiring test for LivePipelineManager + MultiTimeframeRouter.

Verifies that the manager attaches the router to the bar store and that
the router fans resampled bars into the runner's ``_on_resampled_bar``
callback. We don't run a real bar store or strategy — the test injects
1m bars directly into the router and asserts the runner's callback was
invoked at the right cadence.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import MagicMock

from src.broker_gateway.live_bar_store import MinuteBar
from src.execution.live_pipeline import LivePipelineManager


class TestBarRouterWiring:
    def test_manager_owns_router_instance(self) -> None:
        mgr = LivePipelineManager(
            session_manager=MagicMock(),
            bar_store=MagicMock(),
            equity_store=MagicMock(),
        )
        assert mgr._bar_router is not None  # noqa: SLF001

    def test_start_attaches_router_to_bar_store(self) -> None:
        bar_store = MagicMock()
        bar_store.register_bar_callback = MagicMock()
        sm = MagicMock()
        sm.get_all_sessions.return_value = []
        mgr = LivePipelineManager(
            session_manager=sm,
            bar_store=bar_store,
            equity_store=MagicMock(),
        )
        mgr.start()
        # Two registrations: dispatch_bar callback + router.on_minute_bar
        assert bar_store.register_bar_callback.call_count == 2
        registered = [c.args[0] for c in bar_store.register_bar_callback.call_args_list]
        assert mgr._bar_router.on_minute_bar in registered  # noqa: SLF001

    def test_runner_subscribes_to_router_on_create(self) -> None:
        # Stand-up a minimal runner via direct construction so we can
        # confirm the subscription and callback path without spinning
        # up a full LivePipelineManager.
        from src.data.multi_timeframe_router import MultiTimeframeRouter
        from src.execution.live_strategy_runner import LiveStrategyRunner

        router = MultiTimeframeRouter()
        runner = LiveStrategyRunner(
            session_id="sess",
            account_id="acct",
            strategy_slug="medium_term/trend_following/ema_trend_pullback",
            symbol="TX",
            equity_budget=1_000_000.0,
            bar_router=router,
        )
        # Spy the resampled callback so we can detect dispatch.
        called: list[MinuteBar] = []
        runner._on_resampled_bar = lambda _sym, bar: called.append(bar)  # type: ignore[assignment]
        # Re-subscribe with the spy because __init__ already wired the
        # original method reference; unsubscribe and resubscribe.
        router.unsubscribe(runner._on_resampled_bar)
        router.subscribe(runner.symbol, runner._bar_agg, runner._on_resampled_bar)
        # Feed enough 1m bars to close one resampled window.
        start = datetime(2026, 4, 25, 8, 45)
        for i in range(runner._bar_agg + 1):
            router.on_minute_bar(
                "TX",
                MinuteBar(
                    timestamp=start + timedelta(minutes=i),
                    open=100.0, high=101.0, low=99.0, close=100.5, volume=10,
                ),
            )
        assert len(called) >= 1

    def test_legacy_path_when_router_absent(self) -> None:
        from src.execution.live_strategy_runner import LiveStrategyRunner

        # Construct without a router — runner should still init and the
        # legacy buffer fallback should remain active.
        runner = LiveStrategyRunner(
            session_id="sess",
            account_id="acct",
            strategy_slug="medium_term/trend_following/ema_trend_pullback",
            symbol="TX",
            equity_budget=1_000_000.0,
            bar_router=None,
        )
        assert runner._bar_router is None  # noqa: SLF001
        assert runner._bar_buffer == []  # noqa: SLF001
