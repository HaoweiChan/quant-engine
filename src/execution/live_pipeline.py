"""LivePipelineManager — singleton orchestrating per-session strategy runners.

Listens for bar-complete events from LiveMinuteBarStore and fans out to
active LiveStrategyRunner instances. Manages runner lifecycle when sessions
start/stop/change.
"""
from __future__ import annotations

import asyncio
import threading
from datetime import datetime, timedelta, timezone
from datetime import time as dt_time
from typing import Any

import structlog

from src.broker_gateway.live_bar_store import LiveMinuteBarStore, MinuteBar
from src.broker_gateway.live_spread_buffer import LiveSpreadBarBuilder
from src.core.sizing import PortfolioSizer, SizingConfig
from src.execution.live_strategy_runner import LiveStrategyRunner
from src.trading_session.manager import SessionManager
from src.trading_session.portfolio_db import LivePortfolioStore
from src.trading_session.store import AccountEquityStore, FillStore, PortfolioEquityStore

logger = structlog.get_logger(__name__)

_TAIPEI_TZ = timezone(timedelta(hours=8))

# Safety-net force-flat fires 30 seconds after the last tradeable minute
# of each TAIFEX session. This catches the case where a broker tick gap
# at 04:59 / 13:44 means LiveStrategyRunner.on_bar_complete never sees
# the session-close bar, leaving positions to carry into the next session.
_NIGHT_FORCE_FLAT_TIME = dt_time(4, 59, 30)   # 30s after night close last bar
_DAY_FORCE_FLAT_TIME = dt_time(13, 44, 30)    # 30s after day close last bar


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
        portfolio_equity_store: PortfolioEquityStore | None = None,
        portfolio_store: LivePortfolioStore | None = None,
    ) -> None:
        self._sm = session_manager
        self._bar_store = bar_store
        self._equity_store = equity_store
        self._notifier = notifier
        self._sizing_config = sizing_config or self.DEFAULT_SIZING
        self._portfolio_sizer = portfolio_sizer
        self._portfolio_equity_store = portfolio_equity_store
        self._portfolio_store = portfolio_store
        self._runners: dict[str, LiveStrategyRunner] = {}
        # Per-spread-runner synthetic bar builders. When a runner's
        # strategy declares ``spread_legs`` in STRATEGY_META, the
        # pipeline subscribes a LiveSpreadBarBuilder to the bar store
        # and routes the paired R1+R2 synthetic bar to the runner
        # (instead of the raw single-leg bar that the legacy
        # `_matches_symbol.startswith` check used to forward, which is
        # what made spread strategies trade on single-leg prices in
        # live mode — see plan C1).
        self._spread_builders: dict[str, LiveSpreadBarBuilder] = {}
        self._lock = threading.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._started = False
        self._fill_store = FillStore()
        # Session-close fallback: an asyncio task that fires force-flat
        # at the deterministic session-end times even if the broker tick
        # stream gaps and the per-runner on_bar_complete check (which
        # depends on receiving a bar at exactly 04:59 / 13:44) misses.
        self._force_flat_task: asyncio.Task | None = None
        # Optional broker-position reconciler. Wired in via ``start()``;
        # when present, its ``start_loop`` task runs alongside the
        # bar-dispatch + force-flat plumbing so engine ↔ broker
        # position drift is detected on a timer instead of only at
        # disaster-stop fill time.
        self._reconciler: Any | None = None
        self._reconciler_task: asyncio.Task | None = None

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

    def get_runner_snapshots(self) -> dict[str, dict[str, Any]]:
        """Return a session_id→snapshot dict with each runner's live state.

        Used by the war-room API to show paper-mode positions, PnL, and equity
        that the broker gateway cannot see.
        """
        snapshots: dict[str, dict[str, Any]] = {}
        for sid, runner in self.iter_runners():
            positions = runner.positions
            current_price = (
                getattr(runner._executor, "_current_price", None)
                or runner._last_bar_close
                or 0.0
            )
            try:
                specs = runner._adapter.get_contract_specs(runner.symbol)
                point_value = specs.point_value
            except Exception:
                point_value = 1.0
            pos_dicts = []
            for pos in positions:
                if pos.direction == "long":
                    upnl = (current_price - pos.entry_price) * pos.lots * point_value
                else:
                    upnl = (pos.entry_price - current_price) * pos.lots * point_value
                pos_dicts.append({
                    "symbol": runner.symbol,
                    "side": pos.direction,
                    "quantity": int(pos.lots),
                    "avg_entry_price": pos.entry_price,
                    "current_price": current_price,
                    "unrealized_pnl": upnl,
                    "strategy_slug": runner.strategy_slug,
                })
            snapshots[sid] = {
                "session_id": sid,
                "account_id": runner.account_id,
                "strategy_slug": runner.strategy_slug,
                "symbol": runner.symbol,
                "equity": runner.equity,
                "realized_pnl": runner._realized_pnl,
                "unrealized_pnl": runner._unrealized_pnl,
                "positions": pos_dicts,
                "trade_count": len(runner._fill_history),
                "last_bar_ts": runner._last_bar_ts.isoformat() if runner._last_bar_ts else None,
            }
        return snapshots

    def iter_runners(self) -> list[tuple[str, LiveStrategyRunner]]:
        """Lock-safe snapshot of (session_id, runner) pairs.

        Use this from cross-cutting code (kill-switch, dashboard) that must
        iterate runners without risking a ``dictionary changed size during
        iteration`` race with ``_sync_runners``.
        """
        with self._lock:
            return list(self._runners.items())

    def start(
        self,
        loop: asyncio.AbstractEventLoop | None = None,
        reconciler: Any | None = None,
    ) -> None:
        """Register bar callback, create runners, and optionally start
        the broker-position reconciliation loop.

        The ``reconciler`` argument is supplied by the caller because
        ``PositionReconciler`` needs broker-specific state (the shioaji
        API handle, an engine-position getter) that the pipeline
        manager doesn't own. Passing it here keeps the wiring explicit
        and lets the same pipeline run with or without reconciliation
        (e.g. CI tests, paper-only smoke runs).
        """
        if self._started:
            return
        self._loop = loop
        self._bar_store.register_bar_callback(self._on_bar_complete)
        self._sync_runners()
        self._startup_aggregate_bars()
        self._started = True
        self._reconciler = reconciler
        # Spawn the session-close safety-net timer when an event loop is
        # available. The task awaits until the next session-close moment
        # then triggers force-flat across all runners.
        if loop is not None and not loop.is_closed():
            try:
                self._force_flat_task = loop.create_task(self._force_flat_loop())
            except Exception:
                logger.exception("live_pipeline_force_flat_task_start_failed")
            if reconciler is not None:
                try:
                    self._reconciler_task = loop.create_task(reconciler.start_loop())
                    logger.info("live_pipeline_reconciler_started")
                except Exception:
                    logger.exception(
                        "live_pipeline_reconciler_start_failed",
                    )
        logger.info("live_pipeline_started", runners=len(self._runners))

    def _startup_aggregate_bars(self) -> None:
        """Catch up on any 1m bars that may exist before live aggregator started.

        Collects all unique symbols from active runners and calls incremental_update()
        to ensure 5m and 1h bars are available for War Room charts.
        """
        try:
            symbols: set[str] = {
                runner.symbol
                for runner in self._runners.values()
            }
            if not symbols:
                return
            from src.data.aggregator import incremental_update
            from src.data.db import Database, DEFAULT_DB_PATH
            db = Database(f"sqlite:///{DEFAULT_DB_PATH}")
            for symbol in symbols:
                try:
                    results = incremental_update(db, symbol, since=None)
                    logger.info(
                        "startup_aggregation_complete",
                        symbol=symbol,
                        new_5m=results.get("5m", 0),
                        new_1h=results.get("1h", 0),
                    )
                except Exception:
                    logger.exception("startup_aggregation_failed", symbol=symbol)
        except Exception:
            logger.exception("startup_aggregate_bars_failed")

    def stop(self) -> None:
        """Tear down all runners and cancel the session-close + reconciler tasks."""
        with self._lock:
            self._runners.clear()
        for attr in ("_force_flat_task", "_reconciler_task"):
            task = getattr(self, attr, None)
            if task is not None and not task.done():
                try:
                    task.cancel()
                except Exception:
                    logger.exception(
                        "live_pipeline_task_cancel_failed", task=attr,
                    )
            setattr(self, attr, None)
        self._reconciler = None
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
                self._spread_builders.pop(sid, None)
                logger.info("live_runner_removed", session_id=sid)
            # Create runners for new active sessions
            for sid, session in active_sessions.items():
                if sid in self._runners:
                    continue
                try:
                    effective_eq = self._sm.get_effective_equity(sid)
                    if effective_eq is None or effective_eq <= 0:
                        effective_eq = session.virtual_equity
                    if (effective_eq is None or effective_eq <= 0) and session.portfolio_id:
                        effective_eq = self._portfolio_share_equity(
                            session.portfolio_id, session.equity_share or 1.0,
                        )
                    if effective_eq is None or effective_eq <= 0:
                        effective_eq = (session.equity_share or 1.0) * 1_000_000
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
                    self._maybe_register_spread_builder(sid, session)
                    logger.info(
                        "live_runner_created",
                        session_id=sid,
                        strategy=session.strategy_slug,
                        symbol=session.symbol,
                        equity=effective_eq,
                    )
                except Exception:
                    logger.exception("live_runner_create_failed", session_id=sid)

    def _maybe_register_spread_builder(self, session_id: str, session: Any) -> None:
        """If the session's strategy has spread metadata, build a
        LiveSpreadBarBuilder for it so the runner sees synthetic
        spread bars instead of raw single-leg bars.
        """
        try:
            from src.strategies.registry import get_info

            info = get_info(session.strategy_slug)
            legs = (info.meta or {}).get("spread_legs") if info else None
        except Exception:
            legs = None
        if not legs or len(legs) != 2:
            return
        # Account-relative legs: when the seeder/loader places a spread
        # strategy on a different underlying than the META default
        # (e.g. MTX instead of TX), build the leg pair from the session's
        # symbol so the live builder watches the right tick streams.
        leg1 = session.symbol
        leg2 = f"{session.symbol}_R2"
        builder = LiveSpreadBarBuilder(
            spread_symbol=session.symbol,
            leg1_symbol=leg1,
            leg2_symbol=leg2,
        )
        builder.attach_to_store(self._bar_store)
        builder.register_callback(
            lambda sym, bar, _sid=session_id: self._on_spread_bar(_sid, sym, bar),
        )
        self._spread_builders[session_id] = builder
        logger.info(
            "live_spread_builder_registered",
            session_id=session_id,
            slug=session.strategy_slug,
            legs=[leg1, leg2],
        )

    def _on_spread_bar(self, session_id: str, symbol: str, bar: MinuteBar) -> None:
        """Synthetic-spread callback. Routes the paired bar to the spread
        runner via the same async dispatcher used for raw bars.
        """
        runner = self._runners.get(session_id)
        if runner is None:
            return
        loop = self._loop
        if loop is None or loop.is_closed():
            return
        try:
            asyncio.run_coroutine_threadsafe(self._dispatch_bar(runner, symbol, bar), loop)
        except Exception:
            logger.exception(
                "live_pipeline_spread_dispatch_error",
                session_id=session_id,
                symbol=symbol,
            )

    def _on_bar_complete(self, symbol: str, bar: MinuteBar) -> None:
        """Callback from LiveMinuteBarStore — dispatches to matching runners.

        Spread runners are excluded here: they receive bars only via
        their attached LiveSpreadBarBuilder, which emits a synthetic
        spread bar when both legs report at the same minute_ts. Routing
        raw single-leg bars to a spread runner was the source of the
        live-spread mispricing bug — see plan C1.
        """
        runners_to_dispatch = [
            (sid, r)
            for sid, r in self.iter_runners()
            if sid not in self._spread_builders
        ]
        if not runners_to_dispatch:
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
        for sid, runner in runners_to_dispatch:
            try:
                coro = self._dispatch_bar(runner, symbol, bar)
                asyncio.run_coroutine_threadsafe(coro, loop)
            except Exception:
                logger.exception(
                    "live_pipeline_dispatch_error",
                    session_id=sid,
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
            self._record_portfolio_equity(runner.session_id)
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
            if not fill_timestamp:
                bar_ts = runner._last_bar_ts
                fill_timestamp = (
                    bar_ts.strftime("%Y-%m-%d %H:%M:%S") if bar_ts
                    else datetime.now(_TAIPEI_TZ).strftime("%Y-%m-%d %H:%M:%S")
                )
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
            # Look up the runner's portfolio so the message can attribute the
            # fill to it. Paper portfolios are tagged so a glance at the
            # message is enough to know "this is sandbox money, not real".
            portfolio_label = ""
            try:
                session = self._sm.get_session(runner.session_id)
                pid = getattr(session, "portfolio_id", None) if session else None
                if pid and self._portfolio_store is not None:
                    p = self._portfolio_store.get(pid)
                    if p:
                        mode_tag = " [PAPER]" if p.mode == "paper" else " [LIVE]"
                        portfolio_label = (
                            f"<b>Portfolio:</b> {p.name}{mode_tag}\n"
                        )
            except Exception:
                logger.debug("telegram_portfolio_lookup_failed", exc_info=True)
            for result in results:
                if result.status != "filled":
                    continue
                msg = (
                    f"<b>Account:</b> {runner.account_id}\n"
                    f"{portfolio_label}"
                    f"<b>{strategy_name}</b> ({runner.symbol})\n"
                    f"{format_trade(result)}\n"
                    f"Equity: {runner.equity:,.0f}"
                )
                await self._notifier.dispatch(msg, account_id=runner.account_id)
        except Exception:
            logger.debug("telegram_notify_failed", exc_info=True)

    @staticmethod
    def _next_force_flat_at(now: datetime) -> datetime:
        """Return the next session-close fallback wake time after ``now``."""
        today_targets = [
            now.replace(
                hour=t.hour, minute=t.minute, second=t.second, microsecond=0,
            )
            for t in (_NIGHT_FORCE_FLAT_TIME, _DAY_FORCE_FLAT_TIME)
        ]
        future = [t for t in today_targets if t > now]
        if future:
            return min(future)
        # All times today have passed — wake at the first slot tomorrow.
        return (now + timedelta(days=1)).replace(
            hour=_NIGHT_FORCE_FLAT_TIME.hour,
            minute=_NIGHT_FORCE_FLAT_TIME.minute,
            second=_NIGHT_FORCE_FLAT_TIME.second,
            microsecond=0,
        )

    async def _force_flat_loop(self) -> None:
        """Safety-net loop: at each session boundary, call _force_flat on
        every runner using a synthesised bar with the close-time timestamp.

        Runs forever; cancelled in stop(). Idempotent — runners that have
        already flattened (no open positions) just return [] from
        ``_force_flat`` without sending any orders.
        """
        try:
            while True:
                now = datetime.now(_TAIPEI_TZ)
                next_at = self._next_force_flat_at(now)
                wait_s = max(1.0, (next_at - now).total_seconds())
                logger.info(
                    "force_flat_timer_scheduled",
                    next_at=next_at.isoformat(),
                    wait_s=int(wait_s),
                )
                await asyncio.sleep(wait_s)
                await self._fire_force_flat()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("force_flat_loop_error")

    async def _fire_force_flat(self) -> None:
        """Build a synthesised session-close bar and call _force_flat on
        each runner. Errors per runner are swallowed so one bad runner
        cannot starve the rest of the safety net.
        """
        now = datetime.now(_TAIPEI_TZ)
        # Snap timestamp back to the actual session-close minute (04:59 / 13:44).
        if now.time() >= _DAY_FORCE_FLAT_TIME and now.time().hour < _NIGHT_FORCE_FLAT_TIME.hour:
            close_min = now.replace(hour=13, minute=44, second=0, microsecond=0)
        else:
            close_min = now.replace(hour=4, minute=59, second=0, microsecond=0)
        synthetic_bar = MinuteBar(
            timestamp=close_min,
            open=0.0, high=0.0, low=0.0, close=0.0, volume=0,
        )
        for sid, runner in self.iter_runners():
            try:
                results = await runner._force_flat(synthetic_bar)
                if results:
                    logger.warning(
                        "force_flat_timer_fired",
                        session_id=sid,
                        positions_closed=len(results),
                        ts=close_min.isoformat(),
                    )
            except Exception:
                logger.exception(
                    "force_flat_timer_runner_failed",
                    session_id=sid,
                )

    def _portfolio_share_equity(
        self, portfolio_id: str, equity_share: float,
    ) -> float | None:
        """Return ``portfolio.initial_equity * equity_share`` if available.

        Used as the runner-init fallback when the session has no explicit
        ``virtual_equity`` and the session-manager has no effective equity
        yet. Lets paper portfolios start at the user-chosen seed.
        """
        if self._portfolio_store is None:
            return None
        try:
            portfolio = self._portfolio_store.get(portfolio_id)
        except Exception:
            return None
        if portfolio is None or not portfolio.initial_equity:
            return None
        return float(portfolio.initial_equity) * float(equity_share)

    def _record_portfolio_equity(self, session_id: str) -> None:
        """Record per-portfolio equity for the portfolio that owns ``session_id``.

        Sums equity across every runner whose session belongs to the same
        portfolio, then writes one point to ``portfolio_equity_history``.
        Sessions not bound to a portfolio are skipped — the dashboard only
        renders portfolio-scoped curves and the top account chip uses the
        broker snapshot directly.
        """
        if self._portfolio_equity_store is None:
            return
        try:
            session = self._sm.get_session(session_id)
        except Exception:
            return
        if session is None or not session.portfolio_id:
            return
        pid = session.portfolio_id
        try:
            total_equity = 0.0
            total_margin = 0.0
            for sid, runner in self.iter_runners():
                s = self._sm.get_session(sid)
                if s is not None and s.portfolio_id == pid:
                    total_equity += runner.equity
                    total_margin += float(getattr(runner, "margin_used", 0.0) or 0.0)
            self._portfolio_equity_store.record(
                pid, total_equity, margin_used=total_margin,
            )
        except Exception:
            logger.exception(
                "live_pipeline_portfolio_equity_record_failed",
                portfolio_id=pid,
            )
