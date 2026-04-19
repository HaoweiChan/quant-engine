"""Paper trading executor: simulate fills with configurable slippage."""
from __future__ import annotations

import numpy as np
import structlog

from src.core.types import Order
from src.execution.engine import ExecutionEngine, ExecutionResult

logger = structlog.get_logger(__name__)


class PaperExecutor(ExecutionEngine):
    """Simulate order fills at current price with configurable slippage and
    per-side commission.

    Slippage is applied as a price adjustment (adverse to the order side).
    Commission is recorded as ``ExecutionResult.metadata['commission']`` in
    NT dollars so downstream PnL accounting (live_strategy_runner,
    trading_session.store) can deduct it consistently with the backtester's
    MarketImpactFillModel. The previous implementation applied slippage
    only, producing paper-trade PnL that overstated by ~NT$50/leg vs the
    backtest cost model on MTX.
    """

    def __init__(
        self,
        slippage_points: float = 1.0,
        current_price: float = 0.0,
        available_margin: float = float("inf"),
        margin_per_lot: float = 184_000.0,
        commission_per_contract_per_side: float = 0.0,
    ) -> None:
        super().__init__()
        self._slippage_points = slippage_points
        self._current_price = current_price
        self._available_margin = available_margin
        self._margin_per_lot = margin_per_lot
        # Stored as NT dollars per contract per side. Caller passes
        # `instrument_cost_config.commission_per_contract / 2` to convert
        # the round-trip number to a per-side number, since each fill is
        # one side of a round trip.
        self._commission_per_contract_per_side = commission_per_contract_per_side
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
        # Per-fill commission in NT dollars. Recorded under metadata so
        # callers can sum it across results without re-deriving the cost
        # config — and so backtest/paper PnL drift detectors can compare
        # this directly to MarketImpactFillModel's commission.
        commission_nt = order.lots * self._commission_per_contract_per_side

        return ExecutionResult(
            order=order, status="filled",
            fill_price=fill_price, expected_price=expected,
            slippage=slippage, fill_qty=order.lots, remaining_qty=0.0,
            metadata={"commission": commission_nt},
        )
