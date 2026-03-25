"""Live executor: place real orders via shioaji with callback→asyncio bridge."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

import structlog

from src.core.types import Order
from src.execution.engine import ExecutionEngine, ExecutionResult

logger = structlog.get_logger(__name__)

_TRANSIENT_CODES = {"ECONNRESET", "ETIMEDOUT", "EAI_AGAIN"}


@dataclass
class LiveExecutorConfig:
    fill_timeout: float = 30.0
    max_retries: int = 3
    retry_base_delay: float = 1.0
    simulation: bool = False


class LiveExecutor(ExecutionEngine):
    """Place real TAIFEX futures orders via shioaji and await fill confirmations."""

    def __init__(
        self,
        api: Any,
        loop: asyncio.AbstractEventLoop,
        config: LiveExecutorConfig | None = None,
        rollout_config: Any | None = None,
    ) -> None:
        super().__init__()
        self._api = api
        self._loop = loop
        self._config = config or LiveExecutorConfig()
        self._rollout = rollout_config
        self._pending: dict[str, asyncio.Future[dict[str, Any]]] = {}
        self._fill_history: list[ExecutionResult] = []
        self._api.set_order_callback(self._on_callback)

    async def execute(self, orders: list[Order]) -> list[ExecutionResult]:
        if not orders:
            return []
        results: list[ExecutionResult] = []
        for order in orders:
            result = await self._execute_single(order)
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
            normalized = {"trade_id": order_id, "price": price, "quantity": qty}
            self._loop.call_soon_threadsafe(future.set_result, normalized)

    # ------------------------------------------------------------------
    # Single order execution
    # ------------------------------------------------------------------

    async def _execute_single(self, order: Order) -> ExecutionResult:
        if self._rollout and self._rollout.enabled:
            rejection = self._check_rollout(order)
            if rejection:
                return rejection

        for attempt in range(self._config.max_retries):
            try:
                return await self._place_and_await(order)
            except _PermanentError as exc:
                logger.error(
                    "order_permanent_rejection",
                    symbol=order.symbol, error=str(exc),
                )
                return self._make_result(
                    order, "rejected", 0.0, 0.0, 0.0, order.lots, str(exc),
                )
            except _TransientError as exc:
                if attempt == self._config.max_retries - 1:
                    logger.error(
                        "order_failed_all_retries",
                        symbol=order.symbol, attempts=self._config.max_retries,
                    )
                    return self._make_result(
                        order, "rejected", 0.0, 0.0, 0.0, order.lots, str(exc),
                    )
                delay = self._config.retry_base_delay * (2 ** attempt)
                logger.warning(
                    "order_retry", symbol=order.symbol,
                    attempt=attempt + 1, delay=delay, error=str(exc),
                )
                await asyncio.sleep(delay)

        return self._make_result(
            order, "rejected", 0.0, 0.0, 0.0, order.lots, "max_retries_exceeded",
        )

    async def _place_and_await(self, order: Order) -> ExecutionResult:
        contract = self._resolve_contract(order)
        sj_order = self._build_sj_order(order)
        expected_price = order.price or order.stop_price or 0.0

        trade = self._api.place_order(contract, sj_order)
        trade_id = trade.order.id
        logger.info(
            "order_placed", trade_id=trade_id,
            symbol=order.symbol, side=order.side, lots=order.lots,
        )

        future: asyncio.Future[dict[str, Any]] = self._loop.create_future()
        self._pending[trade_id] = future

        try:
            deal = await asyncio.wait_for(future, timeout=self._config.fill_timeout)
        except TimeoutError:
            logger.warning("order_timeout", trade_id=trade_id, timeout=self._config.fill_timeout)
            try:
                self._api.cancel_order(trade)
            except Exception:
                logger.error("cancel_failed", trade_id=trade_id)
            return self._make_result(
                order, "cancelled", 0.0, expected_price, 0.0, order.lots, "timeout",
            )
        finally:
            self._pending.pop(trade_id, None)

        if deal.get("error"):
            msg = deal.get("op_msg", "broker_rejection")
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
        return self._make_result(
            order, status, fill_price, expected_price,
            slippage, fill_qty, remaining_qty=remaining,
        )

    # ------------------------------------------------------------------
    # Order translation
    # ------------------------------------------------------------------

    def _resolve_contract(self, order: Order) -> Any:
        return self._api.Contracts.Futures.TXF.TXF202504  # TODO: dynamic month resolution

    def _build_sj_order(self, order: Order) -> Any:
        import shioaji as sj

        action = sj.constant.Action.Buy if order.side == "buy" else sj.constant.Action.Sell

        if order.order_type == "stop":
            return self._api.Order(
                action=action,
                price=order.stop_price or 0.0,
                quantity=int(order.lots),
                price_type=sj.constant.FuturesPriceType.LMT,
                order_type=sj.constant.OrderType.IOC,
                octype=sj.constant.FuturesOCType.Auto,
                account=self._api.futopt_account,
            )

        if order.order_type == "market":
            return self._api.Order(
                action=action,
                price=0,
                quantity=int(order.lots),
                price_type=sj.constant.FuturesPriceType.MKT,
                order_type=sj.constant.OrderType.IOC,
                octype=sj.constant.FuturesOCType.Auto,
                account=self._api.futopt_account,
            )

        return self._api.Order(
            action=action,
            price=order.price or 0.0,
            quantity=int(order.lots),
            price_type=sj.constant.FuturesPriceType.LMT,
            order_type=sj.constant.OrderType.ROD,
            octype=sj.constant.FuturesOCType.Auto,
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
        return ExecutionResult(
            order=order, status=status, fill_price=fill_price,
            expected_price=expected_price, slippage=slippage,
            fill_qty=fill_qty if status != "rejected" else 0.0,
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
