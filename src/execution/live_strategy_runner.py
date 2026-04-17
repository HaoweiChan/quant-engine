"""Per-session live strategy runner: bar → snapshot → signal → orders → fills."""
from __future__ import annotations

import asyncio
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
        strategy_params: dict[str, Any] | None = None,
        sizing_config: SizingConfig | None = None,
        sizer: PortfolioSizer | None = None,
        execution_mode: ExecutionMode = "paper",
        broker_api: Any | None = None,
        event_loop: asyncio.AbstractEventLoop | None = None,
        live_executor_config: LiveExecutorConfig | None = None,
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
        self._realized_pnl = 0.0
        self._fill_history: list[ExecutionResult] = []
        self._last_bar_ts: datetime | None = None
        self._bar_count = 0
        # Cached margin-per-unit from the most recent snapshot, so
        # ``margin_used`` can be computed outside the bar-tick context
        # (e.g. by LivePipelineManager.aggregate_open_exposure).
        self._last_margin_per_unit: float = 0.0
        self._adapter = TaifexAdapter(backtest_mode=False)
        self._sizer = sizer if sizer is not None else PortfolioSizer(sizing_config)
        self._owns_sizer = sizer is None
        self._execution_mode: ExecutionMode = execution_mode
        self._broker_api = broker_api
        self._event_loop = event_loop
        self._live_executor_config = live_executor_config
        # Cached last observed tick price for unrealized-PnL fallback
        # when running live (LiveExecutor does not hold a _current_price).
        self._last_bar_close: float = 0.0
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
            sizing=self._sizer.config.__dict__,
            shared_sizer=not self._owns_sizer,
        )

    def _build_components(
        self, params: dict[str, Any] | None
    ) -> tuple[PositionEngine, _AnyExecutor, _AnyExecutionEngine]:
        """Resolve strategy factory and build engine + executor.

        Dispatches between paper and live executors based on
        ``self._execution_mode``. The mode must have been resolved by
        the caller via ``mode_resolver.resolve_session_mode`` —
        constructing a runner directly with the wrong mode is the
        caller's bug, not this function's.
        """
        from src.core.types import get_instrument_cost_config
        from src.mcp_server.facade import get_active_params_for_mcp, resolve_factory

        factory = resolve_factory(self.strategy_slug)
        merged = dict(params or {})
        if not merged:
            active = get_active_params_for_mcp(strategy=self.strategy_slug)
            if active.get("source") == "registry":
                merged = active.get("params", {})
        cost = get_instrument_cost_config(self.symbol)
        specs = self._adapter.get_contract_specs(self.symbol)
        engine: PositionEngine = factory(**merged)

        if self._execution_mode == "paper":
            executor: _AnyExecutor = PaperExecutor(
                slippage_points=(
                    cost.slippage_bps * specs.point_value / 10000
                    if cost.slippage_bps else 1.0
                ),
                current_price=0.0,
                available_margin=self._equity_budget,
                margin_per_lot=specs.margin_initial,
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
        """Called when a 1m bar completes. Core evaluation loop."""
        if not self._matches_symbol(symbol):
            return []
        self._bar_count += 1
        # Session boundary check: force flat if new session started
        if self._last_bar_ts is not None and is_new_session(self._last_bar_ts, bar.timestamp):
            results = await self._force_flat(bar)
            self._last_bar_ts = bar.timestamp
            return results
        self._last_bar_ts = bar.timestamp
        # Check if this is the last bar of the session (force flat at 04:59 / 13:44)
        if self._is_session_close_bar(bar.timestamp):
            return await self._force_flat(bar)
        snapshot = self._bar_to_snapshot(bar)
        # Cache margin_per_unit so the public ``margin_used`` property is
        # accurate for cross-runner aggregation (LivePipelineManager uses
        # this to push exposure into the shared PortfolioSizer).
        self._last_margin_per_unit = snapshot.margin_per_unit
        self._last_bar_close = snapshot.price
        # ``set_market_state`` is paper-only — LiveExecutor gets price
        # and margin from the broker. Guard the call so the runner
        # works uniformly across modes.
        if hasattr(self._executor, "set_market_state"):
            self._executor.set_market_state(
                price=snapshot.price,
                available_margin=max(self._equity_budget + self._realized_pnl - self._margin_used(snapshot), 0),
            )
        account = self._make_account(snapshot)
        orders = self._engine.on_snapshot(snapshot, signal=None, account=account)
        if not orders:
            return []
        # Portfolio-level sizing: override strategy lots with centralized sizing
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

        Entry orders are resized using stop-distance risk sizing.
        Add orders are resized in the engine via ``engine.add_sizer`` (attached in
        __init__); their Orders flow through here unchanged.
        Exit orders pass through unchanged.
        """
        sized: list[Order] = []
        for order in orders:
            if order.reason in ("exit", "stop", "stop_loss", "trailing_stop",
                                "session_close", "circuit_breaker", "margin_safety"):
                sized.append(order)
                continue
            if order.reason == "entry":
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
                )
                # Also update the Position in the engine to match the resized lots
                self._resize_last_position(result.lots)
                logger.info(
                    "sizer_resized_entry", session=self.session_id,
                    lots=result.lots, method=result.method,
                )
            sized.append(order)
        return sized

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
        """Check if tick symbol matches this runner's target.

        TMF ticks may arrive as "TMFR1", "TMF202506", etc.
        """
        return tick_symbol.startswith(self.symbol)

    def _bar_to_snapshot(self, bar: MinuteBar) -> MarketSnapshot:
        return self._adapter.to_snapshot({
            "symbol": self.symbol,
            "price": bar.close,
            "high": bar.high,
            "low": bar.low,
            "volume": bar.volume,
            "timestamp": bar.timestamp,
        })

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
            if r.order.reason in ("exit", "stop", "stop_loss", "trail_stop", "trailing_stop",
                                   "session_close", "close", "circuit_breaker"):
                # Calculate realized PnL using entry price from order metadata
                entry_price = r.order.metadata.get("entry_price") if r.order.metadata else None
                if entry_price is not None:
                    if r.order.side == "sell":  # Closing a long
                        fill_pnl = (r.fill_price - entry_price) * r.fill_qty * pv
                    else:  # Closing a short
                        fill_pnl = (entry_price - r.fill_price) * r.fill_qty * pv
                    self._realized_pnl += fill_pnl
                # Store realized PnL in result metadata for notifications
                r.metadata["realized_pnl"] = fill_pnl
                r.metadata["entry_price"] = entry_price
            logger.info(
                "live_fill",
                session_id=self.session_id,
                side=r.order.side,
                qty=r.fill_qty,
                price=r.fill_price,
                slippage=r.slippage,
                reason=r.order.reason,
                realized_pnl=fill_pnl,
            )

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
                reason="session_close",
                order_class="algo_exit",
                parent_position_id=pos.position_id,
                metadata={"entry_price": pos.entry_price, "timestamp": bar.timestamp.isoformat()},
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
