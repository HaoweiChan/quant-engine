"""Per-session live strategy runner: bar → snapshot → signal → orders → fills."""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any, Literal, Union
from zoneinfo import ZoneInfo

import structlog

from src.adapters.taifex import TaifexAdapter
from src.broker_gateway.live_bar_store import MinuteBar
from src.core.position_engine import PositionEngine
from src.core.sizing import PortfolioSizer, SizingConfig, _base_position_lots
from src.core.types import (
    METADATA_EXPOSURE_MULTIPLIER,
    METADATA_STRATEGY_SIZED,
    AccountState,
    AddDecision,
    MarketSnapshot,
    Order,
    Position,
)
from src.data.session_utils import is_new_session
from src.execution.engine import ExecutionResult
from src.execution.live import LiveExecutor, LiveExecutorConfig
from src.execution.live_execution_engine import LiveExecutionEngine
from src.execution.paper import PaperExecutor
from src.execution.paper_execution_engine import PaperExecutionEngine

ExecutionMode = Literal["paper", "live"]
_AnyExecutor = Union[PaperExecutor, LiveExecutor]
_AnyExecutionEngine = Union[PaperExecutionEngine, LiveExecutionEngine]

logger = structlog.get_logger(__name__)
_TAIPEI_TZ = ZoneInfo("Asia/Taipei")


def _parse_hhmm_to_minutes(value: Any) -> int | None:
    """Parse ``"HH:MM"`` into minutes-from-midnight. Returns None for invalid."""
    if not isinstance(value, str) or ":" not in value:
        return None
    try:
        hh, mm = value.split(":", 1)
        h = int(hh)
        m = int(mm)
    except ValueError:
        return None
    if not (0 <= h < 24 and 0 <= m < 60):
        return None
    return h * 60 + m


def _force_flat_enabled_for_strategy(strategy_slug: str, meta: dict[str, Any]) -> bool:
    """Return live session-close behavior using the backtest holding rule.

    The invariant is holding-period driven: only intraday strategies may be
    force-flattened at TAIFEX session boundaries. ``force_flat_at_session_end``
    can opt an intraday strategy out (for special day-trade handling), but it
    cannot opt a medium/swing strategy into session-close liquidation.
    """
    from src.strategies.registry import is_intraday_strategy

    intraday = is_intraday_strategy(strategy_slug)
    explicit = meta.get("force_flat_at_session_end")
    if not intraday:
        if explicit is True:
            logger.warning(
                "live_runner_ignored_non_intraday_force_flat_true",
                strategy=strategy_slug,
                note=(
                    "session-close flattening is driven by stop_architecture; "
                    "non-intraday strategies must carry across sessions"
                ),
            )
        return False
    return explicit is not False


class LiveStrategyRunner:
    """Drives a single strategy session: receives completed bars, evaluates
    the PositionEngine, and executes paper orders.

    One instance per active TradingSession.
    """

    def __init__(
        self,
        session_id: str,
        account_id: str,
        strategy_slug: str,
        symbol: str,
        equity_budget: float,
        equity_share: float = 1.0,
        strategy_params: dict[str, Any] | None = None,
        sizing_config: SizingConfig | None = None,
        sizer: PortfolioSizer | None = None,
        execution_mode: ExecutionMode = "paper",
        broker_api: Any | None = None,
        event_loop: asyncio.AbstractEventLoop | None = None,
        live_executor_config: LiveExecutorConfig | None = None,
        bar_router: Any | None = None,
    ) -> None:
        """Per-session live strategy runner.

        Args:
            sizer: Optional shared ``PortfolioSizer`` injected by a
                ``LivePipelineManager`` that is enforcing a portfolio-wide
                margin cap or Kelly-mode allocation. When supplied, the
                runner consumes the shared sizer rather than constructing
                its own — this is how cross-strategy margin pooling and
                per-slug Kelly scaling take effect at the runner boundary.
                Backward compatible: when ``sizer`` is ``None``, a fresh
                per-runner ``PortfolioSizer`` is created from ``sizing_config``
                (legacy behaviour).
            execution_mode: Resolved by ``mode_resolver.resolve_session_mode``
                before construction. "paper" builds a simulated executor
                (default, backward compatible). "live" builds a real
                broker executor using ``broker_api`` and ``event_loop``.
            broker_api: shioaji API handle — required when
                ``execution_mode="live"``.
            event_loop: asyncio event loop for live callback bridging —
                required when ``execution_mode="live"``.
            live_executor_config: Optional override for LiveExecutor.
        """
        self.session_id = session_id
        self.account_id = account_id
        self.strategy_slug = strategy_slug
        self.symbol = symbol
        self._equity_budget = equity_budget
        self._equity_share = equity_share
        self._realized_pnl = 0.0
        self._fill_history: list[ExecutionResult] = []
        self._last_bar_ts: datetime | None = None
        self._bar_count = 0
        # Notification callback for fills produced by the router-fed eval
        # path. When the MultiTimeframeRouter is wired, strategy evaluation
        # runs from ``_on_resampled_bar`` → ``_dispatch_resampled`` instead
        # of the legacy ``on_bar_complete`` buffer flush. The pipeline
        # registers ``_notify_fills`` here so resampled-path fills also get
        # persisted to ``live_fills``, broadcast on the blotter, and
        # dispatched to Telegram — without this, entries (which only fire
        # on the resampled close) were silently filed to nowhere while
        # exits (firing from the per-1m stop check via ``on_bar_complete``)
        # still got reported. The 2026-05-13 sinopac-main report — 479
        # EXIT alerts, 0 ENTRY alerts in 24h — is the canonical regression.
        self._notify_callback: Callable[
            [LiveStrategyRunner, list[ExecutionResult]], Awaitable[None]
        ] | None = None
        # Cached margin-per-unit from the most recent snapshot, so
        # ``margin_used`` can be computed outside the bar-tick context
        # (e.g. by LivePipelineManager.aggregate_open_exposure).
        self._last_margin_per_unit: float = 0.0
        self._adapter = TaifexAdapter(backtest_mode=False)
        self._sizer = sizer if sizer is not None else PortfolioSizer(sizing_config)
        self._owns_sizer = sizer is None
        # Per-trading-day daily ATR cache. The previous design defaulted
        # to a hardcoded 100.0 every bar (`taifex.py:to_snapshot` line 51),
        # so disaster-stop distances and any ATR-aware stops were sized
        # against a constant, not the actual instrument volatility. The
        # cache key is `data.session_utils.trading_day(bar.timestamp)` so
        # the value refreshes once per TAIFEX trading day. See B4.
        from datetime import date as _date
        self._daily_atr_by_day: dict[_date, float] = {}
        self._execution_mode: ExecutionMode = execution_mode
        self._broker_api = broker_api
        self._event_loop = event_loop
        self._live_executor_config = live_executor_config
        # Cached last observed tick price for unrealized-PnL fallback
        # when running live (LiveExecutor does not hold a _current_price).
        self._last_bar_close: float = 0.0
        # Strategy-meta-driven session-management hooks. Read once at runner
        # construction so `_meta_*` lookups are cheap on every bar tick.
        # ``half_exit_at_min`` (minutes from midnight) optionally schedules a
        # one-shot partial close — the runner emits a sell-half order once
        # at the first bar at or after this time, then the rest of the
        # position rides through the session (used by the `intraday_max_long`
        # strategy that buys 當沖 max at open and keeps half overnight).
        # By default, session-close flattening is driven by the strategy's
        # holding-period semantics: intraday strategies flatten, swing/medium
        # strategies carry. A strategy may still explicitly override this in
        # STRATEGY_META, e.g. intraday_max_long keeps half past session close.
        from src.strategies.registry import get_info
        try:
            _info = get_info(strategy_slug)
            _meta = _info.meta or {}
        except Exception:
            _meta = {}
        self._meta_force_flat = _force_flat_enabled_for_strategy(strategy_slug, _meta)
        self._meta_daytrade: bool = bool(_meta.get("daytrade", False))
        self._meta_half_exit_at_min: int | None = _parse_hhmm_to_minutes(
            _meta.get("half_exit_at"),
        )
        self._half_exit_done: bool = False
        # Intraday-margin override: when the strategy declares
        # ``intraday_margin_per_contract`` (TAIFEX 當沖 half-margin), every
        # snapshot built by this runner has its ``margin_per_unit``
        # rewritten to that value. That keeps the engine's pre-trade
        # margin gate, the engine's margin_safety reduce-half trigger,
        # and the runner's own ``_make_account`` margin accounting all
        # consistent with the broker's actual buying-power charge —
        # otherwise the engine would see overnight margin (184k for TX)
        # and trim a position that the broker would have accepted in
        # full at half margin.
        self._meta_intraday_margin: float | None = None
        try:
            from src.strategies.registry import get_active_params as _gap
            _active = _gap(strategy_slug)
            _im = _active.get("intraday_margin_per_contract")
            if isinstance(_im, (int, float)) and _im > 0:
                self._meta_intraday_margin = float(_im)
        except Exception:
            pass
        # Bar resampling: strategies may run on 5m/15m bars while
        # the live pipeline dispatches 1m bars. Accumulate 1m bars
        # and only evaluate the strategy on the resampled bar.
        from src.strategies.registry import get_bar_agg
        self._bar_agg: int = get_bar_agg(strategy_slug)
        self._bar_buffer: list[MinuteBar] = []
        # When a MultiTimeframeRouter is supplied, strategy evaluation
        # runs from the router's resampled callback (one canonical
        # window per (symbol, tf) shared across all subscribers) rather
        # than the per-runner buffer. Stop checks still run on every
        # 1m bar via on_bar_complete; only the eval path is rerouted.
        self._bar_router = bar_router
        if bar_router is not None:
            try:
                bar_router.subscribe(symbol, self._bar_agg, self._on_resampled_bar)
            except Exception:
                logger.exception(
                    "live_runner_router_subscribe_failed",
                    session_id=session_id,
                    symbol=symbol,
                )
                self._bar_router = None
        else:
            logger.warning(
                "live_runner_no_bar_router",
                session_id=session_id,
                strategy=strategy_slug,
                bar_agg=self._bar_agg,
                note="falling back to per-runner _bar_buffer aggregation; "
                     "wire MultiTimeframeRouter for shared cross-strategy windows",
            )
        engine, executor, exec_engine = self._build_components(strategy_params)
        self._engine: PositionEngine = engine
        self._executor: _AnyExecutor = executor
        # Legacy attribute name preserved for historical reasons; now
        # refers to whichever execution engine (paper or live) was built.
        self._paper_engine: _AnyExecutionEngine = exec_engine
        self._attach_add_sizer()
        logger.info(
            "live_runner_init",
            session_id=session_id,
            strategy=strategy_slug,
            symbol=symbol,
            equity=equity_budget,
            mode=execution_mode,
            bar_agg=self._bar_agg,
            sizing=self._sizer.config.__dict__,
            shared_sizer=not self._owns_sizer,
        )

    def _build_components(
        self, params: dict[str, Any] | None
    ) -> tuple[PositionEngine, _AnyExecutor, _AnyExecutionEngine]:
        """Resolve strategy factory and build engine + executor.

        When ``QUANT_PINNED_EXECUTION`` is enabled and the active candidate
        has a stored ``strategy_code``, the engine executes the pinned source
        rather than importing the current ``src/strategies/<slug>.py``. This
        insulates the live session from in-flight edits to the strategy file.

        Dispatches between paper and live executors based on
        ``self._execution_mode``. The mode must have been resolved by
        the caller via ``mode_resolver.resolve_session_mode`` —
        constructing a runner directly with the wrong mode is the
        caller's bug, not this function's.
        """
        from src.core.types import get_instrument_cost_config
        from src.mcp_server.facade import (
            PinnedExecutionError,
            get_active_params_for_mcp,
            resolve_factory_by_hash,
        )

        merged = dict(params or {})
        active = get_active_params_for_mcp(strategy=self.strategy_slug)
        active_source = active.get("source") if isinstance(active, dict) else None
        active_params = active.get("params", {}) or {}
        if not merged and active_source == "registry":
            merged = active_params
        # Always pass session_id to the factory for DB-backed entry guards
        merged["session_id"] = self.session_id
        pinned_hash = active.get("strategy_hash") if isinstance(active, dict) else None
        pinned_code = active.get("strategy_code") if isinstance(active, dict) else None

        # B5 precondition guard: surface every silent precedence path so a
        # mismatched runner doesn't quietly trade with the wrong code or
        # params. Three failure modes are pinned by these checks:
        #   1. User passed params that mask non-empty active registry params
        #      (the user's params win silently — confirm intent in logs).
        #   2. Active candidate has an unexpected ``source`` that the runner
        #      doesn't know how to merge (registry vs defaults vs unknown).
        #   3. ``pinned_hash`` is set but ``pinned_code`` is missing — the
        #      `resolve_factory_by_hash` path 4 will then look the code up
        #      in the registry; if that fails, PinnedExecutionError fires
        #      and we refuse to start. Still warn so the operator sees that
        #      the runner is one DB outage away from refusing to start.
        if params and active_source == "registry" and active_params and active_params != merged:
            logger.warning(
                "live_runner_param_override",
                session_id=self.session_id,
                slug=self.strategy_slug,
                active_keys=sorted(active_params.keys()),
                user_keys=sorted(merged.keys()),
                note="user-provided params win over registry-active params",
            )
        if active_source not in (None, "registry", "defaults"):
            logger.warning(
                "live_runner_active_params_unknown_source",
                session_id=self.session_id,
                slug=self.strategy_slug,
                source=active_source,
            )
        if pinned_hash and not pinned_code:
            logger.warning(
                "live_runner_pinned_hash_without_code",
                session_id=self.session_id,
                slug=self.strategy_slug,
                pinned_hash=(pinned_hash or "")[:12],
                note="will look up code via ParamRegistry; refuses to start if absent",
            )

        try:
            factory, _pinned_meta = resolve_factory_by_hash(
                self.strategy_slug,
                strategy_hash=pinned_hash,
                strategy_code=pinned_code,
            )
        except PinnedExecutionError:
            # Refuse to start a live session against unloadable pinned code.
            # Silently falling through to the current file would defeat the
            # whole point of pin-by-hash execution on the live path.
            logger.error(
                "live_runner_pinned_compile_failed",
                session_id=self.session_id,
                slug=self.strategy_slug,
                pinned_hash=(pinned_hash or "")[:12] or None,
            )
            raise

        logger.info(
            "live_runner_pinned",
            session_id=self.session_id,
            slug=self.strategy_slug,
            pinned_hash=(pinned_hash or "")[:12] or None,
            using_pin=bool(pinned_hash and pinned_code),
        )
        cost = get_instrument_cost_config(self.symbol)
        specs = self._adapter.get_contract_specs(self.symbol)
        # Older pinned factories may predate the session_id kwarg and reject
        # it (either by signature or by their own unknown-kwarg guard). Drop
        # it and retry once so B5 doesn't silently lose runners on restart.
        try:
            engine: PositionEngine = factory(**merged)
        except TypeError as e:
            if "session_id" in merged and "session_id" in str(e):
                retry_merged = {k: v for k, v in merged.items() if k != "session_id"}
                logger.warning(
                    "live_runner_factory_session_id_dropped",
                    session_id=self.session_id,
                    slug=self.strategy_slug,
                    reason=str(e),
                )
                engine = factory(**retry_merged)
            else:
                raise

        if self._execution_mode == "paper":
            # Commission is round-trip per contract; PaperExecutor charges
            # per fill (one side), so divide by 2 to keep round-trip cost
            # aligned with the backtester's MarketImpactFillModel.
            # 當沖 strategies declare ``intraday_margin_per_contract`` in
            # PARAM_SCHEMA — when present, paper-mode uses that as the
            # buying-power charge so paper smoke tests don't reject the
            # max-BP buy that the live broker would happily accept.
            # Resolve from the registry's effective params (PARAM_SCHEMA
            # default + TOML override) rather than ``merged`` because the
            # runner injects ``session_id`` before this point so the
            # active-params merge above is bypassed for unit-test callers
            # that pass no explicit params.
            paper_margin = specs.margin_initial
            try:
                from src.strategies.registry import get_active_params
                _active = get_active_params(self.strategy_slug)
                _im = _active.get("intraday_margin_per_contract")
                if isinstance(_im, (int, float)) and _im > 0:
                    paper_margin = float(_im)
            except Exception:
                pass
            intraday_margin = (merged or {}).get("intraday_margin_per_contract")
            if isinstance(intraday_margin, (int, float)) and intraday_margin > 0:
                paper_margin = float(intraday_margin)
            executor: _AnyExecutor = PaperExecutor(
                slippage_points=0.0 if cost.slippage_bps else 1.0,
                slippage_bps=cost.slippage_bps if cost.slippage_bps else None,
                current_price=0.0,
                available_margin=self._equity_budget,
                margin_per_lot=paper_margin,
                commission_per_contract_per_side=cost.commission_per_contract / 2.0,
            )
            exec_engine: _AnyExecutionEngine = PaperExecutionEngine(
                executor=executor,
                position_engine=engine,
                config=engine._config,
            )
            return engine, executor, exec_engine

        # Live mode — requires a broker API and asyncio loop.
        if self._broker_api is None or self._event_loop is None:
            raise ValueError(
                f"execution_mode='live' for session {self.session_id} requires "
                "broker_api and event_loop to be provided"
            )
        live_executor = LiveExecutor(
            api=self._broker_api,
            loop=self._event_loop,
            config=self._live_executor_config,
        )
        live_engine = LiveExecutionEngine(
            executor=live_executor,
            position_engine=engine,
            config=engine._config,
        )
        return engine, live_executor, live_engine

    def _attach_add_sizer(self) -> None:
        """Attach PortfolioSizer.size_add hook to the engine.

        Mirrors BacktestRunner._attach_sizer's add sizer. Strategies that emit
        AddDecision with metadata[METADATA_EXPOSURE_MULTIPLIER]=True have their
        lots resolved here from a ratio into absolute contracts using the base
        position's lots, then capped by margin headroom.
        """
        sizer = self._sizer

        def _size_add(
            decision: AddDecision,
            snapshot: MarketSnapshot,
            positions: list[Position],
        ) -> AddDecision | None:
            is_multiplier = bool(decision.metadata.get(METADATA_EXPOSURE_MULTIPLIER, False))
            base_lots = _base_position_lots(positions) if is_multiplier else 0.0
            existing_margin = sum(p.lots * snapshot.margin_per_unit for p in positions)
            result = sizer.size_add(
                equity=self.equity,
                existing_margin_used=existing_margin,
                margin_per_unit=snapshot.margin_per_unit,
                requested_lots=decision.lots,
                base_lots=base_lots,
                is_multiplier=is_multiplier,
                strategy_slug=self.strategy_slug,
            )
            if result.lots < 1:
                return None
            return AddDecision(
                lots=result.lots,
                contract_type=decision.contract_type,
                move_existing_to_breakeven=decision.move_existing_to_breakeven,
                metadata={
                    **decision.metadata,
                    "sizer": result.method,
                    "sizer_caps": result.caps_applied,
                },
            )

        self._engine.add_sizer = _size_add

    @property
    def equity(self) -> float:
        return self._equity_budget + self._realized_pnl + self._unrealized_pnl

    @property
    def margin_used(self) -> float:
        """Current margin consumption across all open positions.

        Uses the most recently observed ``margin_per_unit`` from the bar
        tick. Returns 0 before the first bar completes — consumers
        (``LivePipelineManager.aggregate_open_exposure``) treat that as
        "no cross-strategy exposure yet".
        """
        if self._last_margin_per_unit <= 0:
            return 0.0
        state = self._engine.get_state()
        return sum(p.lots * self._last_margin_per_unit for p in state.positions)

    @property
    def positions(self) -> list[Position]:
        """Snapshot of the engine's open positions (safe for kill-switch iteration)."""
        return list(self._engine.get_state().positions)

    @property
    def _unrealized_pnl(self) -> float:
        state = self._engine.get_state()
        if not state.positions:
            return 0.0
        specs = self._adapter.get_contract_specs(self.symbol)
        # PaperExecutor exposes ``_current_price`` set via set_market_state;
        # LiveExecutor does not (price discovery lives at the broker). Fall
        # back to the last observed bar close so the PnL reporting path
        # remains defined in both modes.
        current_price = getattr(self._executor, "_current_price", None)
        if not current_price:
            current_price = self._last_bar_close
        if not current_price:
            return 0.0
        total = 0.0
        for pos in state.positions:
            if pos.direction == "long":
                total += (current_price - pos.entry_price) * pos.lots * specs.point_value
            else:
                total += (pos.entry_price - current_price) * pos.lots * specs.point_value
        return total

    async def on_bar_complete(self, symbol: str, bar: MinuteBar) -> list[ExecutionResult]:
        """Called when a 1m bar completes. Core evaluation loop.

        When the strategy's signal_timeframe is coarser than 1m, bars are
        accumulated and resampled before running the strategy evaluation.
        Stop-loss checks still run on every 1m bar for timely exits.
        """
        if not self._matches_symbol(symbol):
            return []
        self._bar_count += 1
        # Bar-input record — emit a single structured log line per incoming
        # bar so the playback verifier can replay the EXACT bar stream this
        # runner saw rather than whatever market.db ended up with after
        # gap_repair / aggregator side-effects. The verifier greps the
        # journal for ``runner_bar_seen session_id=<sid>`` and feeds those
        # bars in order. Adds negligible overhead (one info-level log per
        # 1m bar per active session = ≤6 lines/min in production).
        logger.info(
            "runner_bar_seen",
            session_id=self.session_id,
            symbol=symbol,
            bar_ts=bar.timestamp.isoformat(),
            open=bar.open, high=bar.high, low=bar.low, close=bar.close,
            volume=bar.volume,
        )
        # Engine-state record — capture position list (entry_price, lots,
        # direction, stop_level, pyramid_level) per bar so the playback
        # verifier can seed runner state at any journal-window start with
        # the EXACT stop_level LIVE was using (not a reconstructed
        # approximation). Without this, seeded positions use a generous
        # stop and the trailing_stop ratchet diverges from LIVE.
        try:
            _state = self._engine.get_state()
            if _state.positions:
                logger.info(
                    "runner_state_seen",
                    session_id=self.session_id,
                    bar_ts=bar.timestamp.isoformat(),
                    positions=[
                        {
                            "direction": p.direction,
                            "entry_price": p.entry_price,
                            "lots": p.lots,
                            "stop_level": p.stop_level,
                            "pyramid_level": p.pyramid_level,
                        }
                        for p in _state.positions
                    ],
                )
        except Exception:
            pass
        # Session boundary check: force flat if new session started.
        # Strategies opting out of session-end-flat (intraday_max_long,
        # SWING strategies on 5m bars) also opt out of this gap-detected
        # boundary close — the kept half is already reconciled at the broker;
        # force-flatting here would double-close it. The bar still falls
        # through to the rest of the per-bar pipeline so half-exit / stop
        # checks / strategy eval all run normally on the new session. The
        # gate uses self._meta_force_flat (cached from STRATEGY_META at init).
        if self._last_bar_ts is not None and is_new_session(self._last_bar_ts, bar.timestamp):
            self._bar_buffer.clear()
            if self._meta_force_flat:
                results = await self._force_flat(bar)
                self._last_bar_ts = bar.timestamp
                return results
        self._last_bar_ts = bar.timestamp
        # Check if this is the last bar of the session (force flat at 04:59 / 13:44).
        # Strategies with `STRATEGY_META["force_flat_at_session_end"] = False`
        # opt out of this safety-net flatten so they can keep half a position
        # overnight (e.g. intraday_max_long: 當沖 buy at open, sell half at
        # 13:20, ride the rest into Sinopac's own end-of-session handling).
        # SWING strategies that consume 5m bars (compounding_trend_long_mtf)
        # also declare force_flat_at_session_end=False in their META.
        if self._meta_force_flat and self._is_session_close_bar(bar.timestamp):
            self._bar_buffer.clear()
            return await self._force_flat(bar)
        # Update last bar close for unrealized PnL calc on every tick
        self._last_bar_close = bar.close
        # Check stops on every 1m bar for timely exits
        results = await self._check_stops_on_tick(bar)
        # One-shot half-exit: when the strategy's META declares a
        # `half_exit_at` time and we've reached it (in the runner's
        # local TAIFEX-day timeline), emit a sell-half close for any
        # open long position before the strategy's normal eval runs.
        # Idempotent — once `_half_exit_done` flips, it never re-fires
        # in the same trading day.
        half_results = await self._maybe_half_exit(bar)
        if half_results:
            results.extend(half_results)
        # Strategy evaluation: when a MultiTimeframeRouter is wired,
        # _on_resampled_bar is the canonical eval path and the legacy
        # per-runner buffer is bypassed entirely (avoids double-fire).
        if self._bar_router is not None:
            return results
        # Legacy fallback: accumulate 1m bars and evaluate on the
        # resampled bar. Kept for runners constructed without a
        # router (unit tests, paper smoke runs).
        self._bar_buffer.append(bar)
        if len(self._bar_buffer) < self._bar_agg:
            return results
        resampled = self._resample_buffer()
        strategy_results = await self._evaluate_strategy(resampled)
        results.extend(strategy_results)
        return results

    def _on_resampled_bar(self, symbol: str, bar: MinuteBar) -> None:
        """Router callback: dispatch a closed N-minute bar to strategy eval.

        Synchronous in signature (router calls from the bar-store thread)
        but the actual evaluation is awaited on the runner's event loop
        via ``run_coroutine_threadsafe`` so it doesn't block the router.
        """
        if not self._matches_symbol(symbol):
            return
        loop = self._event_loop
        if loop is None or loop.is_closed():
            try:
                from src.api.main import get_main_loop
                loop = get_main_loop()
                self._event_loop = loop
            except Exception:
                pass
        if loop is None or loop.is_closed():
            logger.warning(
                "live_runner_resampled_no_loop",
                session_id=self.session_id,
                bar_ts=bar.timestamp.isoformat(),
            )
            return
        try:
            asyncio.run_coroutine_threadsafe(self._dispatch_resampled(bar), loop)
        except Exception:
            logger.exception(
                "live_runner_resampled_dispatch_failed",
                session_id=self.session_id,
                bar_ts=bar.timestamp.isoformat(),
            )

    def set_notify_callback(
        self,
        callback: Callable[
            [LiveStrategyRunner, list[ExecutionResult]], Awaitable[None]
        ] | None,
    ) -> None:
        """Register the pipeline's ``_notify_fills`` (or any compatible
        coroutine) so router-fed strategy evaluations notify the same way
        the legacy buffer flush does. Calling with ``None`` clears it.
        """
        self._notify_callback = callback

    async def _dispatch_resampled(self, bar: MinuteBar) -> list[ExecutionResult]:
        """Run strategy evaluation against a router-supplied resampled bar.

        Returned results are also pushed through the registered notify
        callback so the router-fed eval path (entries, adds, strategy
        closes) reaches ``live_fills`` persistence, the blotter
        WebSocket, and Telegram — the same destinations served by
        ``LivePipelineManager._notify_fills`` on the per-1m path.
        Notification failures are logged but never raised so a flaky
        sink can't break the eval loop.
        """
        results = await self._evaluate_strategy(bar)
        if results and self._notify_callback is not None:
            try:
                await self._notify_callback(self, results)
            except Exception:
                logger.exception(
                    "live_runner_resampled_notify_failed",
                    session_id=self.session_id,
                    fills=len(results),
                )
        return results

    def _resample_buffer(self) -> MinuteBar:
        """Merge accumulated 1m bars into a single resampled bar."""
        buf = self._bar_buffer
        resampled = MinuteBar(
            timestamp=buf[0].timestamp,
            open=buf[0].open,
            high=max(b.high for b in buf),
            low=min(b.low for b in buf),
            close=buf[-1].close,
            volume=sum(b.volume for b in buf),
        )
        self._bar_buffer.clear()
        return resampled

    async def _check_stops_on_tick(self, bar: MinuteBar) -> list[ExecutionResult]:
        """Check stop-loss/trailing-stop exits on every 1m bar."""
        state = self._engine.get_state()
        if not state.positions:
            return []
        snapshot = self._bar_to_snapshot(bar)
        self._last_margin_per_unit = snapshot.margin_per_unit
        if hasattr(self._executor, "set_market_state"):
            self._executor.set_market_state(
                price=snapshot.price,
                available_margin=max(self._equity_budget + self._realized_pnl - self._margin_used(snapshot), 0),
            )
        pre_stops = {p.position_id: p.stop_level for p in state.positions}
        pre_entries = {p.position_id: p.entry_price for p in state.positions}
        orders = self._engine.check_stops(snapshot)
        if not orders:
            return []
        # Diagnostic: surface stop-level + bar-range + daily_atr whenever a
        # 1m stop check fires, so the 2026-05-15 "exit on next 1m bar after
        # every entry" pattern can be debugged from production logs.
        logger.info(
            "stop_trigger_diagnostic",
            session_id=self.session_id,
            strategy=self.strategy_slug,
            bar_ts=bar.timestamp.isoformat(),
            bar_open=bar.open,
            bar_high=bar.high,
            bar_low=bar.low,
            bar_close=bar.close,
            daily_atr=snapshot.atr.get("daily"),
            pre_stop_levels=pre_stops,
            pre_entry_prices=pre_entries,
            order_reasons=[o.reason for o in orders],
        )
        orders = [self._tag_daytrade(o) for o in orders]
        await self._paper_engine.on_bar_open(self.symbol, bar.open)
        results = await self._paper_engine.execute(orders, snapshot)
        self._process_fills(results, snapshot)
        return results

    async def _evaluate_strategy(self, bar: MinuteBar) -> list[ExecutionResult]:
        """Run the full strategy evaluation on a (resampled) bar."""
        snapshot = self._bar_to_snapshot(bar)
        self._last_margin_per_unit = snapshot.margin_per_unit
        self._last_bar_close = snapshot.price
        if hasattr(self._executor, "set_market_state"):
            self._executor.set_market_state(
                price=snapshot.price,
                available_margin=max(self._equity_budget + self._realized_pnl - self._margin_used(snapshot), 0),
            )
        account = self._make_account(snapshot)
        orders = self._engine.on_snapshot(snapshot, signal=None, account=account)
        if not orders:
            return []
        orders = self._apply_portfolio_sizing(orders, snapshot, account)
        if not orders:
            return []
        await self._paper_engine.on_bar_open(self.symbol, bar.open)
        results = await self._paper_engine.execute(orders, snapshot)
        self._process_fills(results, snapshot)
        return results

    def _apply_portfolio_sizing(
        self, orders: list[Order], snapshot: MarketSnapshot, account: AccountState
    ) -> list[Order]:
        """Override strategy-determined lots with portfolio-level sizing.

        Entry orders are resized using stop-distance risk sizing UNLESS the
        strategy marked the order with ``metadata[METADATA_STRATEGY_SIZED]
        = True`` — that flag is the contract for "I sized this myself
        against my own constraint (e.g. 當沖 BP / margin), don't let the
        portfolio sizer override me." Add orders are resized in the engine
        via ``engine.add_sizer`` (attached in __init__); their Orders flow
        through here unchanged. Exit orders pass through unchanged.
        Strategy-level ``daytrade`` meta is propagated onto every emitted
        order so the LiveExecutor builds shioaji orders with
        ``octype=FuturesOCType.DayTrade``.
        """
        sized: list[Order] = []
        for order in orders:
            if order.reason in ("exit", "stop", "stop_loss", "trailing_stop",
                                "session_close", "circuit_breaker", "margin_safety"):
                sized.append(self._tag_daytrade(order))
                continue
            strategy_self_sized = bool((order.metadata or {}).get(METADATA_STRATEGY_SIZED))
            if order.reason == "entry" and not strategy_self_sized:
                stop_dist = self._infer_stop_distance(snapshot)
                result = self._sizer.size_entry(
                    equity=account.equity,
                    stop_distance=stop_dist,
                    point_value=snapshot.contract_specs.point_value,
                    margin_per_unit=snapshot.margin_per_unit,
                    strategy_slug=self.strategy_slug,
                )
                if result.lots <= 0:
                    logger.info("sizer_rejected_entry", session=self.session_id, details=result.details)
                    continue
                order = Order(
                    order_type=order.order_type, side=order.side, symbol=order.symbol,
                    contract_type=order.contract_type, lots=result.lots, price=order.price,
                    stop_price=order.stop_price, reason=order.reason,
                    metadata={**(order.metadata or {}), "sizer": result.method, "sizer_caps": result.caps_applied},
                    parent_position_id=order.parent_position_id, order_class=order.order_class,
                    daytrade=order.daytrade,
                )
                # Also update the Position in the engine to match the resized lots
                self._resize_last_position(result.lots)
                logger.info(
                    "sizer_resized_entry", session=self.session_id,
                    lots=result.lots, method=result.method,
                )
            sized.append(self._tag_daytrade(order))
        return sized

    def _tag_daytrade(self, order: Order) -> Order:
        """Stamp the strategy's META daytrade flag onto an order.

        Returns the order unchanged when the meta flag is False or the
        order already carries an explicit True (so a strategy can flag a
        single order without flipping the whole strategy to daytrade).
        """
        if not self._meta_daytrade or order.daytrade:
            return order
        return Order(
            order_type=order.order_type, side=order.side, symbol=order.symbol,
            contract_type=order.contract_type, lots=order.lots, price=order.price,
            stop_price=order.stop_price, reason=order.reason,
            metadata=dict(order.metadata or {}),
            parent_position_id=order.parent_position_id, order_class=order.order_class,
            daytrade=True,
        )

    async def _maybe_half_exit(self, bar: MinuteBar) -> list[ExecutionResult]:
        """One-shot partial close at the strategy-meta-configured time.

        Fires the first time ``bar.timestamp`` reaches the configured
        ``half_exit_at`` (HH:MM, Taipei time) within a trading day. Sells
        ceil(open_lots / 2) of every open long position (or buys back
        the same fraction for shorts). Sets ``daytrade=True`` on the
        order so Sinopac books the closed portion against the day-trade
        BP. Mutates the engine's Position in-place to reduce its ``lots``
        by the closed amount — this is the only place the runner does an
        explicit partial close, since PositionEngine has no native
        partial-close API. Resets ``_half_exit_done`` whenever the
        trading day rolls over so it re-arms across multiple sessions.
        """
        if self._meta_half_exit_at_min is None:
            return []
        bar_min = bar.timestamp.hour * 60 + bar.timestamp.minute
        # Re-arm at midnight rollover so a runner that survives across
        # days fires once per day (matches the daily 當沖 cycle).
        from src.data.session_utils import trading_day
        bar_day = trading_day(bar.timestamp)
        if getattr(self, "_half_exit_armed_day", None) != bar_day:
            self._half_exit_done = False
            self._half_exit_armed_day = bar_day
        if self._half_exit_done:
            return []
        if bar_min < self._meta_half_exit_at_min:
            return []
        state = self._engine.get_state()
        if not state.positions:
            self._half_exit_done = True
            return []
        snapshot = self._bar_to_snapshot(bar)
        if hasattr(self._executor, "set_market_state"):
            self._executor.set_market_state(price=snapshot.price)
        orders: list[Order] = []
        for pos in state.positions:
            half = max(1, int(pos.lots // 2))
            if half >= pos.lots:
                # Position too small to split (1 lot) — skip.
                continue
            close_side = "sell" if pos.direction == "long" else "buy"
            orders.append(Order(
                symbol=self.symbol,
                side=close_side,
                lots=float(half),
                contract_type=pos.contract_type,
                order_type="market",
                price=None,
                stop_price=None,
                reason="partial_exit",
                order_class="algo_exit",
                parent_position_id=pos.position_id,
                metadata={
                    "entry_price": pos.entry_price,
                    "timestamp": bar.timestamp.isoformat(),
                    "half_exit": True,
                },
                daytrade=self._meta_daytrade,
            ))
        if not orders:
            self._half_exit_done = True
            return []
        results = await self._paper_engine.execute(orders, snapshot)
        # Mutate the engine's positions to reflect the partial close. The
        # PositionEngine has no native partial-close path, but the Position
        # dataclass is mutable and the engine reads ``pos.lots`` everywhere.
        for order, result in zip(orders, results, strict=False):
            if result.status != "filled":
                continue
            for pos in self._engine._positions:  # noqa: SLF001
                if pos.position_id == order.parent_position_id:
                    pos.lots = max(0.0, pos.lots - result.fill_qty)
                    break
        self._engine._positions = [
            p for p in self._engine._positions if p.lots > 0  # noqa: SLF001
        ]
        self._process_fills(results, snapshot)
        self._half_exit_done = True
        logger.info(
            "live_half_exit_fired",
            session_id=self.session_id,
            strategy=self.strategy_slug,
            orders=len(orders),
            ts=bar.timestamp.isoformat(),
        )
        return results

    def _infer_stop_distance(self, snapshot: MarketSnapshot) -> float:
        """Extract stop distance from the engine's current position or ATR."""
        state = self._engine.get_state()
        if state.positions:
            pos = state.positions[-1]
            dist = abs(snapshot.price - pos.stop_level)
            if dist > 0:
                return dist
        daily_atr = snapshot.atr.get("daily", 0.0)
        if daily_atr > 0:
            return daily_atr * 2.0
        return snapshot.price * 0.02

    def _resize_last_position(self, new_lots: float) -> None:
        """Adjust the last position's lots to match the sizer's output.

        The PositionEngine already created the Position at strategy-requested lots;
        we fix it here to match the portfolio-sized amount.
        """
        positions = self._engine._positions
        if positions:
            positions[-1].lots = new_lots

    def _matches_symbol(self, tick_symbol: str) -> bool:
        """Check if an incoming bar belongs to this runner's contract.

        The bar store normally emits canonical DB symbols (``TMF`` or
        ``TMF_R2``), but some tests and recovery paths may pass broker-style
        aliases such as ``TMFR1`` or ``TMF202506``. Plain front-month runners
        must never accept next-month bars (``*_R2`` / ``*R2``), because those
        prices can incorrectly drive live stop checks.
        """
        incoming = (tick_symbol or "").upper()
        target = (self.symbol or "").upper()
        if not incoming or not target:
            return False
        if incoming == target:
            return True

        if target.endswith("_R2"):
            base = target[:-3]
            return incoming in {f"{base}_R2", f"{base}R2", f"{base}FR2"}

        if incoming.endswith("_R2") or incoming.endswith("R2"):
            return False

        if incoming in {f"{target}_R1", f"{target}R1", f"{target}FR1"}:
            return True
        if incoming.startswith(f"{target}F") and incoming[len(target) + 1:].isdigit():
            return True
        if incoming.startswith(target) and incoming[len(target):].isdigit():
            return True
        return False

    def _bar_to_snapshot(self, bar: MinuteBar) -> MarketSnapshot:
        snap = self._adapter.to_snapshot({
            "symbol": self.symbol,
            "price": bar.close,
            "high": bar.high,
            "low": bar.low,
            "volume": bar.volume,
            "timestamp": bar.timestamp,
            "daily_atr": self._daily_atr_for(bar.timestamp),
        })
        # Apply 當沖 intraday-margin override (see __init__ comment).
        if self._meta_intraday_margin is not None:
            snap.margin_per_unit = self._meta_intraday_margin
        return snap

    def _daily_atr_for(self, ts: datetime) -> float:
        """Return the cached daily ATR for ``ts``'s trading day.

        Computes from the last 14 daily closes in market.db on a cache
        miss so each trading day pays the lookup cost exactly once. If
        the database is unreachable or has fewer than 2 daily bars,
        falls back to TaifexAdapter's hardcoded 100.0 (matching the
        legacy behaviour rather than crashing the runner).
        """
        from src.data.session_utils import trading_day

        day = trading_day(ts)
        cached = self._daily_atr_by_day.get(day)
        if cached is not None:
            return cached

        atr = 100.0
        try:
            atr = self._compute_daily_atr(self.symbol, day, lookback=14)
        except Exception:
            logger.debug(
                "live_runner_daily_atr_compute_failed",
                slug=self.strategy_slug,
                day=day.isoformat(),
                exc_info=True,
            )
        self._daily_atr_by_day[day] = atr
        return atr

    @staticmethod
    def _atr_from_hourly_rows(
        rows: list[tuple[str, float, float, float]], lookback: int,
    ) -> float:
        """Aggregate (timestamp, high, low, close) 1h rows into per-trading-day
        OHLC and return the mean True Range over the last ``lookback`` days.

        Pure function — no DB access, no logging. Made into its own method
        so the aggregation logic can be unit-tested without a real
        market.db. The DB-reading wrapper is ``_compute_daily_atr``.
        """
        from datetime import datetime

        from src.data.session_utils import trading_day

        if not rows:
            return 100.0
        # Walk chronologically (ascending) so each trading-day's last close
        # is preserved. The SQL query returns DESC and tests may pass ASC,
        # so sort here rather than relying on the caller.
        daily: dict = {}
        for ts_str, h, lo, c in sorted(rows, key=lambda r: r[0]):
            ts = datetime.fromisoformat(ts_str)
            td = trading_day(ts)
            if td not in daily:
                daily[td] = [float(h), float(lo), float(c)]
            else:
                d = daily[td]
                d[0] = max(d[0], float(h))
                d[1] = min(d[1], float(lo))
                d[2] = float(c)
        days_sorted = sorted(daily.items(), key=lambda kv: kv[0])
        if len(days_sorted) < 2:
            return 100.0
        trs: list[float] = []
        for i in range(1, len(days_sorted)):
            _, (h, lo, _c) = days_sorted[i]
            prev_c = days_sorted[i - 1][1][2]
            tr = max(h - lo, abs(h - prev_c), abs(lo - prev_c))
            trs.append(tr)
        trs = trs[-lookback:]
        if not trs:
            return 100.0
        return sum(trs) / len(trs)

    @staticmethod
    def _compute_daily_atr(symbol: str, day, lookback: int = 14, db_path=None) -> float:
        """Return the mean True Range over the last ``lookback`` TAIFEX
        trading days, aggregated from market.db OHLC bars.

        market.db has no daily table — only ohlcv_bars (1m), ohlcv_5m,
        ohlcv_1h. Earlier versions queried a non-existent
        ``timeframe_minutes=1440`` filter and silently fell back to
        100.0, which pinned trail stops to ~70 pts and caused every
        donchian entry to exit on the very next 1m bar.

        Prefer 1h rows for speed, but fall back to 5m and then 1m rows.
        This matters in live: the 1m table can be current while derived
        aggregation tables are stale or empty after a restart.
        """
        import sqlite3
        from pathlib import Path

        if db_path is None:
            db_path = Path(__file__).resolve().parent.parent.parent / "data" / "market.db"
        else:
            db_path = Path(db_path)
        if not db_path.exists():
            return 100.0
        conn = sqlite3.connect(str(db_path))
        try:
            table_limits = (
                ("ohlcv_1h", lookback * 50),
                ("ohlcv_5m", lookback * 600),
                ("ohlcv_bars", lookback * 3_000),
            )
            for table, limit in table_limits:
                exists = conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                    (table,),
                ).fetchone()
                if not exists:
                    continue
                rows = conn.execute(
                    f"""
                    SELECT timestamp, high, low, close FROM {table}
                    WHERE symbol = ? AND date(timestamp) <= date(?)
                    ORDER BY timestamp DESC
                    LIMIT ?
                    """,
                    (symbol, day.isoformat(), limit),
                ).fetchall()
                if LiveStrategyRunner._row_trading_day_count(rows) >= 2:
                    return LiveStrategyRunner._atr_from_hourly_rows(rows, lookback)
        finally:
            conn.close()
        logger.warning(
            "live_runner_daily_atr_fallback_100",
            symbol=symbol,
            day=day.isoformat(),
            lookback=lookback,
            note="no usable OHLC rows in ohlcv_1h/ohlcv_5m/ohlcv_bars",
        )
        return 100.0

    @staticmethod
    def _row_trading_day_count(rows: list[tuple[str, float, float, float]]) -> int:
        """Count distinct TAIFEX trading days represented in OHLC rows."""
        from datetime import datetime

        from src.data.session_utils import trading_day

        days = set()
        for ts_str, *_ in rows:
            try:
                days.add(trading_day(datetime.fromisoformat(ts_str)))
            except Exception:
                continue
        return len(days)

    def _make_account(self, snapshot: MarketSnapshot) -> AccountState:
        state = self._engine.get_state()
        margin_used = self._margin_used(snapshot)
        eq = self.equity
        return AccountState(
            equity=eq,
            unrealized_pnl=self._unrealized_pnl,
            realized_pnl=self._realized_pnl,
            margin_used=margin_used,
            margin_available=max(eq - margin_used, 0),
            margin_ratio=margin_used / eq if eq > 0 else 0.0,
            drawdown_pct=0.0,
            positions=list(state.positions),
            timestamp=snapshot.timestamp,
        )

    def _margin_used(self, snapshot: MarketSnapshot) -> float:
        state = self._engine.get_state()
        return sum(p.lots * snapshot.margin_per_unit for p in state.positions)

    def _process_fills(self, results: list[ExecutionResult], snapshot: MarketSnapshot) -> None:
        pv = snapshot.contract_specs.point_value
        for r in results:
            if r.status != "filled":
                continue
            self._fill_history.append(r)
            fill_pnl = 0.0
            commission = float((r.metadata or {}).get("commission", 0.0) or 0.0)

            # Record entry guard for DB persistence (survives runner recreation).
            # Key is scoped by (session_id, session_date) so the guard expires
            # at each trading-session boundary. Previously the key was just
            # self.session_id which made the guard permanent — blocking the
            # strategy after its very first entry forever (cf. night_session_long
            # on TMF, ecc3f22b, entered 2026-05-04 and blocked for two weeks).
            if r.order.reason == "entry":
                try:
                    from datetime import time as _dt_time, timedelta as _timedelta
                    from src.trading_session.store import SnapshotStore
                    store = SnapshotStore()
                    now_tpe = datetime.now(_TAIPEI_TZ)
                    # Night-session strategies roll the date at 15:00 TPE:
                    # entries between 00:00-04:59 belong to the previous
                    # calendar day's session. Day strategies always use today.
                    is_night = "night_session" in self.strategy_slug
                    if is_night and now_tpe.time() < _dt_time(5, 0):
                        session_date = (now_tpe.date() - _timedelta(days=1)).isoformat()
                    else:
                        session_date = now_tpe.date().isoformat()
                    guard_key = f"{self.session_id}:{session_date}"
                    store.record_entry_guard(guard_key, self.strategy_slug)
                except Exception as e:
                    logger.warning("entry_guard_record_failed", session_id=self.session_id, error=str(e))

            if r.order.reason in ("exit", "stop", "stop_loss", "trail_stop", "trailing_stop",
                                   "session_close", "close", "circuit_breaker"):
                # Calculate realized PnL using entry price from order metadata
                entry_price = r.order.metadata.get("entry_price") if r.order.metadata else None
                if entry_price is not None:
                    if r.order.side == "sell":  # Closing a long
                        fill_pnl = (r.fill_price - entry_price) * r.fill_qty * pv
                    else:  # Closing a short
                        fill_pnl = (entry_price - r.fill_price) * r.fill_qty * pv
                r.metadata["entry_price"] = entry_price
            if commission:
                fill_pnl -= commission
            self._realized_pnl += fill_pnl
            # Store realized PnL in result metadata for notifications and DB
            # persistence. Entries show their commission as a small realized
            # cost, matching BacktestRunner's per-fill accounting.
            r.metadata["realized_pnl"] = fill_pnl
            r.metadata["commission"] = commission
            logger.info(
                "live_fill",
                session_id=self.session_id,
                side=r.order.side,
                qty=r.fill_qty,
                price=r.fill_price,
                slippage=r.slippage,
                reason=r.order.reason,
                realized_pnl=fill_pnl,
                commission=commission,
            )

            # Log to activity log for portfolio/strategy tracking
            try:
                from src.trading_session.store import ActivityLogger
                activity_logger = ActivityLogger()
                activity_logger.log_trade(
                    account_id=self.account_id,
                    timestamp=snapshot.timestamp.isoformat(),
                    portfolio_id=None,  # Could be populated from session context
                    strategy_slug=self.strategy_slug,
                    side=r.order.side,
                    symbol=self.symbol,
                    price=r.fill_price,
                    quantity=r.fill_qty,
                    reason=r.order.reason,
                )
            except Exception as e:
                logger.debug("activity_log_trade_failed", error=str(e))

    async def _force_flat(self, bar: MinuteBar) -> list[ExecutionResult]:
        """Force-close all open positions at session boundary."""
        state = self._engine.get_state()
        if not state.positions:
            return []
        snapshot = self._bar_to_snapshot(bar)
        if hasattr(self._executor, "set_market_state"):
            self._executor.set_market_state(price=snapshot.price)
        orders: list[Order] = []
        for pos in state.positions:
            close_side = "sell" if pos.direction == "long" else "buy"
            orders.append(Order(
                symbol=self.symbol,
                side=close_side,
                lots=pos.lots,
                contract_type=pos.contract_type,
                order_type="market",
                price=None,
                stop_price=None,
                reason="session_close",
                order_class="algo_exit",
                parent_position_id=pos.position_id,
                metadata={"entry_price": pos.entry_price, "timestamp": bar.timestamp.isoformat()},
                daytrade=self._meta_daytrade,
            ))
        if not orders:
            return []
        results = await self._paper_engine.execute(orders, snapshot)
        self._process_fills(results, snapshot)
        logger.info(
            "live_session_flat",
            session_id=self.session_id,
            positions_closed=len(orders),
            bar_ts=bar.timestamp.isoformat(),
        )
        return results

    @property
    def force_flat_at_session_end(self) -> bool:
        """Whether the LivePipelineManager safety-net should flatten this runner.

        Mirrors the strategy's ``STRATEGY_META["force_flat_at_session_end"]``
        (default True). The pipeline's deterministic 13:44/04:59 timer
        consults this before issuing the synthesised force-flat bar so
        opt-out strategies (intraday_max_long) can keep half a position
        across the session boundary.
        """
        return self._meta_force_flat

    @staticmethod
    def _is_session_close_bar(ts: datetime) -> bool:
        """True for the last tradeable minute of each session."""
        t = ts.time()
        from datetime import time as dt_time
        # Night session last bar: 04:59
        if t == dt_time(4, 59):
            return True
        # Day session last bar: 13:44
        if t == dt_time(13, 44):
            return True
        return False

    def get_stats(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "strategy": self.strategy_slug,
            "symbol": self.symbol,
            "bars_processed": self._bar_count,
            "fills": len(self._fill_history),
            "realized_pnl": self._realized_pnl,
            "equity": self.equity,
            "fill_stats": self._executor.get_fill_stats(),
        }
