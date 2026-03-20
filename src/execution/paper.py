"""Paper trading executor: simulate fills with configurable slippage."""
from __future__ import annotations

import numpy as np
import structlog

from src.core.types import Order
from src.execution.engine import ExecutionEngine, ExecutionResult

logger = structlog.get_logger(__name__)


class PaperExecutor(ExecutionEngine):
    """Simulate order fills at current price with configurable slippage."""

    def __init__(
        self,
        slippage_points: float = 1.0,
        current_price: float = 0.0,
        available_margin: float = float("inf"),
        margin_per_lot: float = 184_000.0,
    ) -> None:
        self._slippage_points = slippage_points
        self._current_price = current_price
        self._available_margin = available_margin
        self._margin_per_lot = margin_per_lot
        self._fill_history: list[ExecutionResult] = []

    def set_market_state(
        self, price: float, available_margin: float | None = None,
    ) -> None:
        self._current_price = price
        if available_margin is not None:
            self._available_margin = available_margin

    async def execute(self, orders: list[Order]) -> list[ExecutionResult]:
        if not orders:
            return []
        results: list[ExecutionResult] = []
        for order in orders:
            result = self._execute_single(order)
            self._fill_history.append(result)
            logger.info(
                "paper_fill",
                side=order.side, qty=order.lots, price=result.fill_price,
                slippage=result.slippage, status=result.status,
            )
            results.append(result)
        return results

    def get_fill_stats(self) -> dict[str, float]:
        if not self._fill_history:
            return {"mean": 0.0, "median": 0.0, "p95": 0.0, "max": 0.0, "count": 0.0}
        slippages = [abs(r.slippage) for r in self._fill_history if r.status == "filled"]
        if not slippages:
            return {"mean": 0.0, "median": 0.0, "p95": 0.0, "max": 0.0, "count": 0.0}
        arr = np.array(slippages)
        return {
            "mean": float(np.mean(arr)),
            "median": float(np.median(arr)),
            "p95": float(np.percentile(arr, 95)),
            "max": float(np.max(arr)),
            "count": float(len(slippages)),
        }

    @property
    def fill_history(self) -> list[ExecutionResult]:
        return list(self._fill_history)

    def _execute_single(self, order: Order) -> ExecutionResult:
        # Margin check for buy orders
        if order.side == "buy":
            required_margin = order.lots * self._margin_per_lot
            if required_margin > self._available_margin:
                return ExecutionResult(
                    order=order, status="rejected",
                    fill_price=0.0, expected_price=self._current_price,
                    slippage=0.0, fill_qty=0.0, remaining_qty=order.lots,
                    rejection_reason="insufficient_margin",
                )

        # Simulate fill with adverse slippage
        expected = self._current_price
        if order.side == "buy":
            fill_price = expected + self._slippage_points
        else:
            fill_price = expected - self._slippage_points
        slippage = fill_price - expected

        return ExecutionResult(
            order=order, status="filled",
            fill_price=fill_price, expected_price=expected,
            slippage=slippage, fill_qty=order.lots, remaining_qty=0.0,
        )
