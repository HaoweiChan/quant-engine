"""Live executor: place real orders via shioaji with callback→asyncio bridge."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from time import monotonic_ns
from typing import Any, Literal

import structlog

from src.core.types import Order
from src.execution.engine import ExecutionEngine, ExecutionResult
from src.runtime.telemetry import FillQualityMonitor, RollingP99, StageTimestamps

logger = structlog.get_logger(__name__)

_TRANSIENT_CODES = {"ECONNRESET", "ETIMEDOUT", "EAI_AGAIN"}


@dataclass
class LiveExecutorConfig:
    fill_timeout: float = 30.0
    max_retries: int = 3
    retry_base_delay: float = 1.0
    simulation: bool = False
    run_mode: Literal["shadow", "micro_live"] = "micro_live"
    calm_vol_threshold: float = 0.30
    high_vol_threshold: float = 0.80
    calm_wait_ms: float = 300.0
    normal_wait_ms: float = 200.0
    high_wait_ms: float = 100.0
    quality_slippage_bps: float = 2.0
    quality_breach_ratio: float = 0.20
    p99_alert_threshold_ms: float = 200.0
    allow_slo_override: bool = False


class LiveExecutor(ExecutionEngine):
    """Place real TAIFEX futures orders via shioaji and await fill confirmations."""

    def __init__(
        self,
        api: Any,
        loop: asyncio.AbstractEventLoop,
        config: LiveExecutorConfig | None = None,
        rollout_config: Any | None = None,
        order_store: Any | None = None,
    ) -> None:
        super().__init__()
        self._api = api
        self._loop = loop
        self._config = config or LiveExecutorConfig()
        self._rollout = rollout_config
        self._pending: dict[str, asyncio.Future[dict[str, Any]]] = {}
        self._fill_history: list[ExecutionResult] = []
        self._latency_window = RollingP99()
        self._quality_monitor = FillQualityMonitor(
            threshold_bps=self._config.quality_slippage_bps,
            degrade_ratio=self._config.quality_breach_ratio,
        )
        self._forced_shadow_mode = False
        # Persistent order-state store. When unset (legacy / unit-test
        # callers), the in-memory ``_pending`` dict remains the only
        # state — survives nothing across a process crash. Production
        # wiring in LivePipelineManager passes a shared ``OrderStateStore``.
        self._order_store = order_store
        if hasattr(self._api, "set_order_callback"):
            self._api.set_order_callback(self._on_callback)

    async def execute(self, orders: list[Order]) -> list[ExecutionResult]:
        if not orders:
            return []
        results: list[ExecutionResult] = []
        for order in orders:
            if self._effective_run_mode() == "shadow":
                result = self._execute_shadow(order)
            else:
                result = await self._execute_single(order)
            self._enrich_result_metrics(order, result)
            self._fill_history.append(result)
            results.append(result)
        return results

    def get_fill_stats(self) -> dict[str, float]:
        filled = [r for r in self._fill_history if r.status == "filled"]
        if not filled:
            return {
                "mean": 0.0, "median": 0.0, "p95": 0.0, "max": 0.0,
                "count": 0.0, "deviation_mean": 0.0, "deviation_p95": 0.0,
                "double_slippage_count": 0.0,
                "pct_over_2bps": 0.0,
                "quality_degraded": 0.0,
                "tick_to_order_p99_ms": self._latency_window.p99(),
            }
        slippages = sorted(abs(r.slippage) for r in filled)
        n = len(slippages)
        p95_idx = min(int(n * 0.95), n - 1)
        stats: dict[str, float] = {
            "mean": sum(slippages) / n,
            "median": slippages[n // 2],
            "p95": slippages[p95_idx],
            "max": slippages[-1],
            "count": float(n),
        }
        slippage_bps = [abs(r.slippage_bps) for r in filled]
        over_2bps = sum(1 for value in slippage_bps if value > 2.0)
        stats["pct_over_2bps"] = over_2bps / len(slippage_bps) if slippage_bps else 0.0
        stats["quality_degraded"] = 1.0 if self._quality_monitor.degraded() else 0.0
        stats["tick_to_order_p99_ms"] = self._latency_window.p99()
        deviations = [
            abs(r.fill_price - r.backtest_expected_price)
            for r in filled if r.backtest_expected_price is not None
        ]
        if deviations:
            deviations.sort()
            nd = len(deviations)
            dp95_idx = min(int(nd * 0.95), nd - 1)
            avg_slip = stats["mean"]
            stats["deviation_mean"] = sum(deviations) / nd
            stats["deviation_p95"] = deviations[dp95_idx]
            stats["double_slippage_count"] = float(
                sum(1 for d in deviations if d > 2 * avg_slip)
            )
        else:
            stats["deviation_mean"] = 0.0
            stats["deviation_p95"] = 0.0
            stats["double_slippage_count"] = 0.0
        return stats

    @property
    def fill_history(self) -> list[ExecutionResult]:
        return list(self._fill_history)

    # ------------------------------------------------------------------
    # Callback bridge (runs on shioaji C++ thread)
    # ------------------------------------------------------------------

    def _on_callback(self, stat: Any, msg: dict[str, Any]) -> None:
        # shioaji fires OrderState.FuturesDeal ('FDEAL') for fills;
        # OrderState.FuturesOrder ('FORDER') for new/cancel/reject events.
        if "Deal" in str(stat):
            self._on_deal_event(msg)
        else:
            self._on_order_event(msg)

    def _on_order_event(self, msg: dict[str, Any]) -> None:
        op = msg.get("operation", {})
        order_id = msg.get("order", {}).get("id", "")
        logger.debug(
            "order_event", order_id=order_id,
            op_type=op.get("op_type"), op_code=op.get("op_code"),
        )
        op_code = op.get("op_code", "")
        if op_code not in ("00", "0000", ""):
            future = self._pending.get(order_id)
            if future and not future.done():
                err = {"error": True, "op_code": op_code, "op_msg": op.get("op_msg", "")}
                self._loop.call_soon_threadsafe(future.set_result, err)

    def _on_deal_event(self, msg: dict[str, Any]) -> None:
        # Real shioaji FDEAL message: {"order": {"id": "..."}, "status": {"deals": [...]}}
        # Unit-test synthetic message:  {"trade_id": "...", "price": ..., "quantity": ...}
        order_id = msg.get("order", {}).get("id") or msg.get("trade_id", "")
        deals = msg.get("status", {}).get("deals", [])
        if deals:
            deal = deals[0] if isinstance(deals[0], dict) else vars(deals[0])
            price = float(deal.get("price", 0.0))
            qty = float(deal.get("quantity", 0))
        else:
            price = float(msg.get("price", 0.0))
            qty = float(msg.get("quantity", 0))
        logger.info("deal_event", order_id=order_id, price=price, quantity=qty)
        future = self._pending.get(order_id)
        if future and not future.done():
            normalized = {
                "trade_id": order_id,
                "price": price,
                "quantity": qty,
                "ack_ns": monotonic_ns(),
            }
            self._loop.call_soon_threadsafe(future.set_result, normalized)

    # ------------------------------------------------------------------
    # Single order execution
    # ------------------------------------------------------------------

    async def _execute_single(self, order: Order) -> ExecutionResult:
        if self._rollout and self._rollout.enabled:
            rejection = self._check_rollout(order)
            if rejection:
                return rejection

        regime = self._classify_volatility(order)
        wait_seconds = self._wait_budget_seconds(regime)
        current_order = order
        replace_count = 0
        while replace_count <= self._config.max_retries:
            try:
                result = await self._place_and_await(current_order, timeout=wait_seconds)
            except _PermanentError as exc:
                logger.error("order_permanent_rejection", symbol=order.symbol, error=str(exc))
                return self._make_result(
                    current_order,
                    "rejected",
                    0.0,
                    current_order.price or current_order.stop_price or 0.0,
                    0.0,
                    0.0,
                    str(exc),
                    remaining_qty=current_order.lots,
                )
            except _TransientError as exc:
                if replace_count >= self._config.max_retries:
                    return self._make_result(
                        current_order,
                        "rejected",
                        0.0,
                        current_order.price or current_order.stop_price or 0.0,
                        0.0,
                        0.0,
                        str(exc),
                        remaining_qty=current_order.lots,
                    )
                delay = self._config.retry_base_delay * (2 ** replace_count)
                await asyncio.sleep(delay)
                replace_count += 1
                continue
            if result.status in {"filled", "rejected"}:
                return result
            if result.status == "partial" and result.remaining_qty > 0:
                current_order = self._next_order_from_partial(current_order, result, replace_count)
                replace_count += 1
                continue
            if result.status == "cancelled" and result.rejection_reason == "timeout":
                if replace_count >= self._config.max_retries:
                    return result
                current_order = self._next_order_from_timeout(current_order, replace_count)
                replace_count += 1
                continue
            return result
        return self._make_result(
            current_order,
            "rejected",
            0.0,
            current_order.price or current_order.stop_price or 0.0,
            0.0,
            0.0,
            "max_retries_exceeded",
            remaining_qty=current_order.lots,
        )

    async def _place_and_await(self, order: Order, timeout: float | None = None) -> ExecutionResult:
        contract = self._resolve_contract(order)
        sj_order = self._build_sj_order(order)
        expected_price = order.price or order.stop_price or 0.0

        dispatch_ns = monotonic_ns()
        trade = self._api.place_order(contract, sj_order)
        trade_id = trade.order.id
        logger.info(
            "order_placed", trade_id=trade_id,
            symbol=order.symbol, side=order.side, lots=order.lots,
        )
        self._record_state(
            "placement",
            order_id=trade_id, order=order,
        )

        future: asyncio.Future[dict[str, Any]] = self._loop.create_future()
        self._pending[trade_id] = future

        try:
            deal = await asyncio.wait_for(
                future,
                timeout=timeout if timeout is not None else self._config.fill_timeout,
            )
        except TimeoutError:
            logger.warning("order_timeout", trade_id=trade_id, timeout=self._config.fill_timeout)
            try:
                self._api.cancel_order(trade)
            except Exception:
                logger.error("cancel_failed", trade_id=trade_id)
            result = self._make_result(
                order, "cancelled", 0.0, expected_price, 0.0, order.lots, "timeout",
            )
            result.metadata["order_dispatch_ns"] = dispatch_ns
            self._record_state("cancelled", order_id=trade_id, reason="timeout")
            return result
        finally:
            self._pending.pop(trade_id, None)

        if deal.get("error"):
            msg = deal.get("op_msg", "broker_rejection")
            self._record_state("rejected", order_id=trade_id, reason=msg)
            raise _TransientError(msg) if self._is_transient(deal) else _PermanentError(msg)

        fill_price = float(deal.get("price", 0.0))
        fill_qty = float(deal.get("quantity", 0.0))
        remaining = order.lots - fill_qty
        slippage = fill_price - expected_price
        status = "filled" if remaining <= 0 else "partial"

        logger.info(
            "order_filled", trade_id=trade_id,
            fill_price=fill_price, slippage=slippage, status=status,
        )
        self._record_state(
            "fill", order_id=trade_id, status=status,
            fill_price=fill_price, fill_qty=fill_qty,
        )
        result = self._make_result(
            order, status, fill_price, expected_price,
            slippage, fill_qty, remaining_qty=remaining,
        )
        result.metadata["order_dispatch_ns"] = dispatch_ns
        result.metadata["broker_ack_ns"] = int(deal.get("ack_ns", monotonic_ns()))
        return result

    def _record_state(self, event: str, **kwargs: Any) -> None:
        """Write-through to the persistent OrderStateStore (no-op when unwired).

        Centralised so the call sites stay terse and the store stays an
        optional dependency. Failures are logged and swallowed: a DB
        write should never block an in-flight live order.
        """
        store = self._order_store
        if store is None:
            return
        try:
            if event == "placement":
                order: Order = kwargs["order"]
                store.record_placement(
                    order_id=kwargs["order_id"],
                    symbol=order.symbol,
                    side=order.side,
                    lots=float(order.lots),
                    price=order.price,
                    parent_position_id=order.parent_position_id,
                    reason=order.reason,
                )
            elif event == "fill":
                fn = (
                    store.record_filled
                    if kwargs["status"] == "filled"
                    else store.record_partial
                )
                fn(
                    order_id=kwargs["order_id"],
                    fill_price=kwargs["fill_price"],
                    fill_qty=kwargs["fill_qty"],
                )
            elif event == "cancelled":
                store.record_cancelled(
                    order_id=kwargs["order_id"],
                    reason=kwargs.get("reason"),
                )
            elif event == "rejected":
                store.record_rejected(
                    order_id=kwargs["order_id"],
                    reason=kwargs.get("reason", "unspecified"),
                )
        except Exception:
            logger.exception(
                "order_state_write_failed", event=event, **{k: v for k, v in kwargs.items() if k != "order"},
            )

    # ------------------------------------------------------------------
    # Order translation
    # ------------------------------------------------------------------

    def _resolve_contract(self, order: Order) -> Any:
        return self._api.Contracts.Futures.TXF.TXF202504  # TODO: dynamic month resolution

    def _build_sj_order(self, order: Order) -> Any:
        try:
            import shioaji as sj
        except ImportError:
            action = "Buy" if order.side == "buy" else "Sell"
            return self._api.Order(
                action=action,
                price=order.price or order.stop_price or 0.0,
                quantity=int(order.lots),
                price_type="MKT" if order.order_type == "market" else "LMT",
                order_type="IOC" if order.order_type in {"market", "stop"} else "ROD",
                octype="DayTrade" if order.daytrade else "Auto",
                account=getattr(self._api, "futopt_account", None),
            )

        action = sj.constant.Action.Buy if order.side == "buy" else sj.constant.Action.Sell
        octype = (
            sj.constant.FuturesOCType.DayTrade if order.daytrade
            else sj.constant.FuturesOCType.Auto
        )

        if order.order_type == "stop":
            return self._api.Order(
                action=action,
                price=order.stop_price or 0.0,
                quantity=int(order.lots),
                price_type=sj.constant.FuturesPriceType.LMT,
                order_type=sj.constant.OrderType.IOC,
                octype=octype,
                account=self._api.futopt_account,
            )

        if order.order_type == "market":
            return self._api.Order(
                action=action,
                price=0,
                quantity=int(order.lots),
                price_type=sj.constant.FuturesPriceType.MKT,
                order_type=sj.constant.OrderType.IOC,
                octype=octype,
                account=self._api.futopt_account,
            )

        return self._api.Order(
            action=action,
            price=order.price or 0.0,
            quantity=int(order.lots),
            price_type=sj.constant.FuturesPriceType.LMT,
            order_type=sj.constant.OrderType.ROD,
            octype=octype,
            account=self._api.futopt_account,
        )

    # ------------------------------------------------------------------
    # Rollout guard
    # ------------------------------------------------------------------

    def _check_rollout(self, order: Order) -> ExecutionResult | None:
        if order.lots > self._rollout.max_contracts_per_order:
            logger.warning(
                "rollout_rejected", reason="exceeds_per_order",
                lots=order.lots, limit=self._rollout.max_contracts_per_order,
            )
            return self._make_result(
                order, "rejected", 0.0, 0.0, 0.0,
                order.lots, "exceeds_rollout_limit",
            )

        total_open = sum(
            r.fill_qty for r in self._fill_history if r.status == "filled"
        )
        if total_open + order.lots > self._rollout.max_total_contracts:
            logger.warning(
                "rollout_rejected", reason="exceeds_total",
                total=total_open, lots=order.lots,
                limit=self._rollout.max_total_contracts,
            )
            return self._make_result(
                order, "rejected", 0.0, 0.0, 0.0,
                order.lots, "exceeds_rollout_limit",
            )

        return None

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _execute_shadow(self, order: Order) -> ExecutionResult:
        expected_price = float(order.price or order.stop_price or order.metadata.get("reference_price", 0.0))
        dispatch_ns = monotonic_ns()
        result = self._make_result(
            order=order,
            status="cancelled",
            fill_price=0.0,
            expected_price=expected_price,
            slippage=0.0,
            fill_qty=0.0,
            rejection_reason="shadow_mode",
            remaining_qty=order.lots,
        )
        result.metadata["order_dispatch_ns"] = dispatch_ns
        result.metadata["broker_ack_ns"] = dispatch_ns
        return result

    def _effective_run_mode(self) -> Literal["shadow", "micro_live"]:
        if self._config.run_mode == "shadow":
            return "shadow"
        if self._forced_shadow_mode and not self._config.allow_slo_override:
            return "shadow"
        return "micro_live"

    def _classify_volatility(self, order: Order) -> Literal["calm", "normal", "high"]:
        volatility = float(order.metadata.get("volatility", 0.5))
        if volatility <= self._config.calm_vol_threshold:
            return "calm"
        if volatility >= self._config.high_vol_threshold:
            return "high"
        return "normal"

    def _wait_budget_seconds(self, regime: Literal["calm", "normal", "high"]) -> float:
        if regime == "calm":
            return self._config.calm_wait_ms / 1000.0
        if regime == "high":
            return self._config.high_wait_ms / 1000.0
        return self._config.normal_wait_ms / 1000.0

    def _next_order_from_partial(
        self,
        order: Order,
        result: ExecutionResult,
        replace_count: int,
    ) -> Order:
        next_price = self._more_aggressive_price(order)
        metadata = dict(order.metadata)
        metadata["replace_count"] = replace_count + 1
        metadata["parent_order_id"] = metadata.get("parent_order_id", metadata.get("order_id"))
        return replace(order, lots=result.remaining_qty, price=next_price, metadata=metadata)

    def _next_order_from_timeout(self, order: Order, replace_count: int) -> Order:
        next_price = self._more_aggressive_price(order)
        metadata = dict(order.metadata)
        metadata["replace_count"] = replace_count + 1
        metadata["parent_order_id"] = metadata.get("parent_order_id", metadata.get("order_id"))
        return replace(order, price=next_price, metadata=metadata)

    @staticmethod
    def _more_aggressive_price(order: Order) -> float:
        base = float(order.price or order.stop_price or 0.0)
        if base <= 0:
            return base
        tick = 1.0
        return base + tick if order.side == "buy" else max(base - tick, 0.0)

    def _enrich_result_metrics(self, order: Order, result: ExecutionResult) -> None:
        expected_price = result.expected_price
        result.slippage_bps = 0.0
        if expected_price != 0:
            result.slippage_bps = (result.slippage / expected_price) * 10_000.0
        stage = StageTimestamps(
            quote_ingest_ns=self._metadata_int(order.metadata.get("quote_ingest_ns")),
            signal_emit_ns=self._metadata_int(order.metadata.get("signal_emit_ns")),
            order_dispatch_ns=self._metadata_int(result.metadata.get("order_dispatch_ns")),
            broker_ack_ns=self._metadata_int(result.metadata.get("broker_ack_ns")),
        )
        tick_to_order = stage.tick_to_order_ms()
        if tick_to_order is not None and tick_to_order >= 0:
            self._latency_window.add(tick_to_order)
            if self._latency_window.p99() > self._config.p99_alert_threshold_ms:
                logger.warning(
                    "latency_slo_breach",
                    p99_ms=self._latency_window.p99(),
                    threshold_ms=self._config.p99_alert_threshold_ms,
                )
                self._forced_shadow_mode = True
        result.metadata["tick_to_order_ms"] = tick_to_order
        result.metadata["tick_to_order_p99_ms"] = self._latency_window.p99()
        if result.status in {"filled", "partial"}:
            self._quality_monitor.add(result.slippage_bps)
            if self._quality_monitor.degraded():
                logger.warning(
                    "execution_quality_degraded",
                    pct_over_threshold=self._quality_monitor.pct_over_threshold(),
                    threshold_bps=self._config.quality_slippage_bps,
                )

    @staticmethod
    def _metadata_int(value: Any) -> int | None:
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _is_transient(deal: dict[str, Any]) -> bool:
        code = str(deal.get("op_code", ""))
        return code in _TRANSIENT_CODES

    @staticmethod
    def _make_result(
        order: Order, status: str, fill_price: float, expected_price: float,
        slippage: float, fill_qty: float, rejection_reason: str | None = None,
        remaining_qty: float = 0.0,
    ) -> ExecutionResult:
        bt_price = order.metadata.get("backtest_expected_price")
        normalized_fill_qty = fill_qty
        if status in {"rejected", "cancelled"}:
            normalized_fill_qty = 0.0
        return ExecutionResult(
            order=order, status=status, fill_price=fill_price,
            expected_price=expected_price, slippage=slippage,
            fill_qty=normalized_fill_qty,
            remaining_qty=(
                remaining_qty if remaining_qty
                else order.lots if status in ("rejected", "cancelled")
                else 0.0
            ),
            rejection_reason=rejection_reason,
            backtest_expected_price=float(bt_price) if bt_price is not None else None,
        )


class _TransientError(Exception):
    pass


class _PermanentError(Exception):
    pass
