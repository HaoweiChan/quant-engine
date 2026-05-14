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


class TestResampledFillsNotifyCallback:
    """Pin the 2026-05-13 regression: when the MultiTimeframeRouter is wired,
    every fill produced by strategy evaluation must flow through the same
    notify hook the per-1m stop-check path uses (persist → blotter →
    Telegram). The chat-history export for that day showed 479 ``EXIT``
    alerts and zero ``ENTRY`` alerts because ``_dispatch_resampled``'s
    results were discarded after eval.
    """

    @staticmethod
    def _make_runner():
        import asyncio

        from src.data.multi_timeframe_router import MultiTimeframeRouter
        from src.execution.live_strategy_runner import LiveStrategyRunner

        router = MultiTimeframeRouter()
        runner = LiveStrategyRunner(
            session_id="sess-resample",
            account_id="acct-x",
            strategy_slug="medium_term/trend_following/ema_trend_pullback",
            symbol="TX",
            equity_budget=1_000_000.0,
            bar_router=router,
        )
        # Run on a private loop so awaiting _dispatch_resampled doesn't
        # contend with whatever the test framework owns.
        loop = asyncio.new_event_loop()
        return runner, loop

    def test_dispatch_resampled_invokes_notify_callback(self) -> None:
        from src.broker_gateway.live_bar_store import MinuteBar
        from src.core.types import Order
        from src.execution.engine import ExecutionResult

        runner, loop = self._make_runner()
        try:
            fake_fill = ExecutionResult(
                order=Order(
                    order_type="market", side="sell", symbol="TX",
                    contract_type="TXFR1", lots=1.0, price=None,
                    stop_price=None, reason="entry",
                ),
                status="filled",
                fill_price=41_488.0,
                expected_price=41_488.0,
                slippage=-0.001,
                fill_qty=1.0,
                remaining_qty=0.0,
                metadata={},
            )

            async def fake_eval(bar):
                return [fake_fill]

            runner._evaluate_strategy = fake_eval  # type: ignore[assignment]

            captured: list[tuple] = []

            async def notify(r, results):
                captured.append((r, results))

            runner.set_notify_callback(notify)

            bar = MinuteBar(
                timestamp=__import__("datetime").datetime(2026, 5, 13, 19, 15),
                open=41_488.0, high=41_490.0, low=41_485.0, close=41_488.0, volume=42,
            )
            results = loop.run_until_complete(runner._dispatch_resampled(bar))

            assert results == [fake_fill]
            assert captured == [(runner, [fake_fill])]
        finally:
            loop.close()

    def test_dispatch_resampled_skips_callback_on_empty_results(self) -> None:
        from src.broker_gateway.live_bar_store import MinuteBar

        runner, loop = self._make_runner()
        try:
            async def fake_eval(_bar):
                return []
            runner._evaluate_strategy = fake_eval  # type: ignore[assignment]

            calls: list[int] = []

            async def notify(_r, _results):
                calls.append(1)

            runner.set_notify_callback(notify)
            bar = MinuteBar(
                timestamp=__import__("datetime").datetime(2026, 5, 13, 19, 15),
                open=41_488.0, high=41_490.0, low=41_485.0, close=41_488.0, volume=10,
            )
            loop.run_until_complete(runner._dispatch_resampled(bar))
            # No fills → no notify call. Avoids burning a Telegram message
            # on every silent bar close.
            assert calls == []
        finally:
            loop.close()

    def test_dispatch_resampled_swallows_callback_exceptions(self) -> None:
        from src.broker_gateway.live_bar_store import MinuteBar
        from src.core.types import Order
        from src.execution.engine import ExecutionResult

        runner, loop = self._make_runner()
        try:
            fake_fill = ExecutionResult(
                order=Order(
                    order_type="market", side="buy", symbol="TX",
                    contract_type="TXFR1", lots=1.0, price=None,
                    stop_price=None, reason="entry",
                ),
                status="filled", fill_price=100.0, expected_price=100.0,
                slippage=0.0, fill_qty=1.0, remaining_qty=0.0, metadata={},
            )

            async def fake_eval(_bar):
                return [fake_fill]
            runner._evaluate_strategy = fake_eval  # type: ignore[assignment]

            async def notify(_r, _results):
                raise RuntimeError("telegram exploded")

            runner.set_notify_callback(notify)
            bar = MinuteBar(
                timestamp=__import__("datetime").datetime(2026, 5, 13, 19, 15),
                open=100.0, high=101.0, low=99.0, close=100.0, volume=1,
            )
            # Must return normally — a flaky notify sink must not abort
            # the eval loop and bring the whole runner down.
            results = loop.run_until_complete(runner._dispatch_resampled(bar))
            assert results == [fake_fill]
        finally:
            loop.close()


class TestPipelineWiresNotifyCallback:
    """Confirm ``LivePipelineManager.sync`` registers ``_notify_fills`` on
    each newly created runner. Without this wiring step the runner's own
    callback hook stays ``None`` and the resampled-path fix above goes
    dormant in production.
    """

    def test_sync_wires_notify_callback_on_new_runner(self) -> None:
        from unittest.mock import MagicMock, patch

        from src.execution.live_pipeline import LivePipelineManager
        from src.trading_session.session import TradingSession

        sess = TradingSession(
            session_id="sid-1",
            account_id="acct-1",
            strategy_slug="medium_term/trend_following/ema_trend_pullback",
            symbol="TX",
            status="active",
            started_at=__import__("datetime").datetime(2026, 5, 13, 19, 0),
            initial_equity=1_000_000.0,
            peak_equity=1_000_000.0,
        )
        sm = MagicMock()
        sm.get_all_sessions.return_value = [sess]
        sm.get_session.return_value = sess
        # _sync_runners reads effective equity via the session manager;
        # MagicMock would otherwise return a MagicMock that fails the
        # ``effective_eq <= 0`` comparison and the runner construction
        # bails before set_notify_callback runs.
        sm.get_effective_equity.return_value = 1_000_000.0

        mgr = LivePipelineManager(
            session_manager=sm,
            bar_store=MagicMock(),
            equity_store=MagicMock(),
        )

        # Stub the warmup so we don't drag the real bar store / strategy
        # warmup pipeline into this unit test.
        with patch.object(mgr, "_warmup_runner", lambda r: None), \
             patch.object(mgr, "_maybe_register_spread_builder", lambda *_a, **_k: None):
            mgr.sync()

        assert "sid-1" in mgr._runners  # noqa: SLF001
        runner = mgr._runners["sid-1"]  # noqa: SLF001
        # The bound method identity proves the pipeline wired its own
        # _notify_fills onto the runner so router-fed eval fan-outs to
        # the same persist+blotter+Telegram path as the per-1m path.
        assert runner._notify_callback == mgr._notify_fills  # noqa: SLF001
