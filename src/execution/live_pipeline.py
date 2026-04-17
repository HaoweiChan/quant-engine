"""LivePipelineManager — singleton orchestrating per-session strategy runners.

Listens for bar-complete events from LiveMinuteBarStore and fans out to
active LiveStrategyRunner instances. Manages runner lifecycle when sessions
start/stop/change.
"""
from __future__ import annotations

import asyncio
import threading
from typing import Any

import structlog

from src.broker_gateway.live_bar_store import LiveMinuteBarStore, MinuteBar
from src.core.sizing import PortfolioSizer, SizingConfig
from src.execution.live_strategy_runner import LiveStrategyRunner
from src.trading_session.manager import SessionManager
from src.trading_session.store import AccountEquityStore, FillStore

logger = structlog.get_logger(__name__)


class LivePipelineManager:
    """Manages the lifecycle of LiveStrategyRunner instances for all active sessions.

    Optional shared portfolio sizer:
        When a ``portfolio_sizer`` is supplied, the manager aggregates open
        exposure across all active runners before each bar dispatch and
        pushes it to the sizer via ``set_open_exposure``. Downstream runners
        that consume the shared sizer can then enforce a portfolio-wide
        ``portfolio_margin_cap`` and apply Kelly-mode scaling uniformly.
        This hook is backward compatible — when no sizer is supplied the
        legacy per-runner sizing behaviour is unchanged.
    """

    # Default sizing: 2% risk per trade, 50% margin cap, max 10 lots
    DEFAULT_SIZING = SizingConfig(risk_per_trade=0.02, margin_cap=0.50, max_lots=10, min_lots=1)

    def __init__(
        self,
        session_manager: SessionManager,
        bar_store: LiveMinuteBarStore,
        equity_store: AccountEquityStore,
        notifier: Any = None,
        sizing_config: SizingConfig | None = None,
        portfolio_sizer: PortfolioSizer | None = None,
    ) -> None:
        self._sm = session_manager
        self._bar_store = bar_store
        self._equity_store = equity_store
        self._notifier = notifier
        self._sizing_config = sizing_config or self.DEFAULT_SIZING
        self._portfolio_sizer = portfolio_sizer
        self._runners: dict[str, LiveStrategyRunner] = {}
        self._lock = threading.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._started = False
        self._fill_store = FillStore()

    @property
    def portfolio_sizer(self) -> PortfolioSizer | None:
        """The shared portfolio sizer, if any, driving global margin/Kelly policy."""
        return self._portfolio_sizer

    def aggregate_open_exposure(self) -> dict[str, float]:
        """Compute aggregate open margin across all runners, keyed by strategy slug.

        Used to feed the shared PortfolioSizer with cross-strategy exposure so
        shared-pool cap enforcement can see the full book, not just one runner.
        Iterates under ``self._lock`` via ``iter_runners()`` so concurrent
        ``_sync_runners`` mutations cannot produce an inconsistent aggregate.
        """
        exposure: dict[str, float] = {}
        for _sid, runner in self.iter_runners():
            slug = runner.strategy_slug
            margin = float(getattr(runner, "margin_used", 0.0) or 0.0)
            exposure[slug] = exposure.get(slug, 0.0) + margin
        return exposure

    def refresh_portfolio_exposure(self) -> None:
        """Push aggregated exposure into the shared portfolio sizer.

        Safe to call when no portfolio_sizer is configured — becomes a no-op.
        """
        if self._portfolio_sizer is None:
            return
        try:
            self._portfolio_sizer.set_open_exposure(self.aggregate_open_exposure())
        except Exception:
            logger.exception("portfolio_exposure_refresh_failed")

    def iter_runners(self) -> list[tuple[str, LiveStrategyRunner]]:
        """Lock-safe snapshot of (session_id, runner) pairs.

        Use this from cross-cutting code (kill-switch, dashboard) that must
        iterate runners without risking a ``dictionary changed size during
        iteration`` race with ``_sync_runners``.
        """
        with self._lock:
            return list(self._runners.items())

    def start(self, loop: asyncio.AbstractEventLoop | None = None) -> None:
        """Register bar callback and create runners for all active sessions."""
        if self._started:
            return
        self._loop = loop
        self._bar_store.register_bar_callback(self._on_bar_complete)
        self._sync_runners()
        self._started = True
        logger.info("live_pipeline_started", runners=len(self._runners))

    def stop(self) -> None:
        """Tear down all runners."""
        with self._lock:
            self._runners.clear()
        self._started = False
        logger.info("live_pipeline_stopped")

    def sync(self) -> None:
        """Re-sync runners with current session states (call after session changes)."""
        self._sync_runners()

    def get_runner(self, session_id: str) -> LiveStrategyRunner | None:
        return self._runners.get(session_id)

    def get_all_stats(self) -> list[dict[str, Any]]:
        return [r.get_stats() for r in self._runners.values()]

    def _sync_runners(self) -> None:
        """Create runners for active sessions, remove stopped ones."""
        with self._lock:
            active_sessions = {
                s.session_id: s
                for s in self._sm.get_all_sessions()
                if s.status == "active"
            }
            # Remove runners for sessions that are no longer active
            stale = [sid for sid in self._runners if sid not in active_sessions]
            for sid in stale:
                del self._runners[sid]
                logger.info("live_runner_removed", session_id=sid)
            # Create runners for new active sessions
            for sid, session in active_sessions.items():
                if sid in self._runners:
                    continue
                try:
                    effective_eq = self._sm.get_effective_equity(sid)
                    if effective_eq is None or effective_eq <= 0:
                        effective_eq = session.equity_share * 1_000_000
                    runner = LiveStrategyRunner(
                        session_id=sid,
                        account_id=session.account_id,
                        strategy_slug=session.strategy_slug,
                        symbol=session.symbol,
                        equity_budget=effective_eq,
                        sizing_config=self._sizing_config,
                        sizer=self._portfolio_sizer,
                    )
                    self._runners[sid] = runner
                    logger.info(
                        "live_runner_created",
                        session_id=sid,
                        strategy=session.strategy_slug,
                        symbol=session.symbol,
                        equity=effective_eq,
                    )
                except Exception:
                    logger.exception("live_runner_create_failed", session_id=sid)

    def _on_bar_complete(self, symbol: str, bar: MinuteBar) -> None:
        """Callback from LiveMinuteBarStore — dispatches to matching runners."""
        runners = list(self._runners.values())
        if not runners:
            return
        loop = self._loop
        if loop is None or loop.is_closed():
            try:
                from src.api.main import get_main_loop
                loop = get_main_loop()
                self._loop = loop
            except Exception:
                logger.debug("live_pipeline_no_event_loop")
                return
        for runner in runners:
            try:
                coro = self._dispatch_bar(runner, symbol, bar)
                asyncio.run_coroutine_threadsafe(coro, loop)
            except Exception:
                logger.exception(
                    "live_pipeline_dispatch_error",
                    session_id=runner.session_id,
                    symbol=symbol,
                )

    async def _dispatch_bar(
        self, runner: LiveStrategyRunner, symbol: str, bar: MinuteBar
    ) -> None:
        """Run one bar through a runner and record aggregate account equity.

        When a shared portfolio sizer is configured, refresh its view of
        cross-strategy exposure BEFORE the runner ticks so sizing decisions
        see the full book state.
        """
        try:
            self.refresh_portfolio_exposure()
            results = await runner.on_bar_complete(symbol, bar)
            if results:
                logger.info(
                    "live_bar_results",
                    session_id=runner.session_id,
                    fills=[r.status for r in results],
                )
                await self._notify_fills(runner, results)
            self._record_account_equity(runner.account_id)
        except Exception:
            logger.exception(
                "live_bar_processing_error",
                session_id=runner.session_id,
                symbol=symbol,
                bar_ts=bar.timestamp.isoformat(),
            )

    async def _notify_fills(self, runner: LiveStrategyRunner, results: list) -> None:
        """Send Telegram notification, blotter broadcast, and persist each fill."""
        for result in results:
            if result.status != "filled":
                continue
            fill_timestamp = result.order.metadata.get("timestamp", "")
            is_session_close = result.order.reason == "session_close"
            pnl_realized = result.metadata.get("realized_pnl", 0.0)

            # Persist fill to database
            try:
                self._fill_store.record_fill(
                    timestamp=fill_timestamp,
                    account_id=runner.account_id,
                    session_id=runner.session_id,
                    strategy_slug=runner.strategy_slug,
                    symbol=runner.symbol,
                    side=result.order.side,
                    price=result.fill_price,
                    quantity=int(result.fill_qty),
                    fee=0.0,
                    pnl_realized=pnl_realized,
                    is_session_close=is_session_close,
                    signal_reason=result.order.reason or "",
                    slippage_bps=result.slippage_bps,
                )
            except Exception:
                logger.debug("fill_store_persist_failed", exc_info=True)

            # Broadcast to blotter WebSocket
            try:
                from src.api.ws.blotter import blotter_broadcaster
                await blotter_broadcaster.broadcast({
                    "type": "fill",
                    "timestamp": fill_timestamp,
                    "account_id": runner.account_id,
                    "session_id": runner.session_id,
                    "strategy_slug": runner.strategy_slug,
                    "symbol": runner.symbol,
                    "side": result.order.side,
                    "price": result.fill_price,
                    "quantity": int(result.fill_qty),
                    "expected_price": result.expected_price,
                    "slippage_bps": result.slippage_bps,
                    "fee": 0.0,
                    "pnl_realized": pnl_realized,
                    "is_session_close": is_session_close,
                    "signal_reason": result.order.reason,
                    "source": "live",
                })
            except Exception:
                logger.debug("blotter_broadcast_failed", exc_info=True)

        # Send Telegram notifications
        if not self._notifier:
            return
        try:
            from src.alerting.formatters import format_trade
            strategy_name = runner.strategy_slug.split("/")[-1]
            for result in results:
                if result.status != "filled":
                    continue
                msg = (
                    f"<b>{strategy_name}</b> ({runner.symbol})\n"
                    f"{format_trade(result)}\n"
                    f"Equity: {runner.equity:,.0f}"
                )
                await self._notifier.dispatch(msg)
        except Exception:
            logger.debug("telegram_notify_failed", exc_info=True)

    def _record_account_equity(self, account_id: str) -> None:
        """Sum equity (and margin used) across all runners for an account."""
        try:
            runners = [r for _sid, r in self.iter_runners() if r.account_id == account_id]
            total_equity = sum(r.equity for r in runners)
            total_margin = sum(
                float(getattr(r, "margin_used", 0.0) or 0.0) for r in runners
            )
            self._equity_store.record(
                account_id, total_equity, margin_used=total_margin,
            )
        except Exception:
            pass
