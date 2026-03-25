"""Execution Engine: abstract interface and result types for order execution."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from src.core.types import Order

if TYPE_CHECKING:
    from src.core.types import SlicedOrder
    from src.simulator.fill_model import ImpactCalibrator


@dataclass
class ExecutionResult:
    order: Order
    status: str  # "filled", "partial", "rejected", "cancelled"
    fill_price: float
    expected_price: float
    slippage: float
    fill_qty: float
    remaining_qty: float
    rejection_reason: str | None = None
    backtest_expected_price: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ParentFillSummary:
    """Aggregated fill stats for a parent order executed via OMS child orders."""
    parent_order: Order
    algorithm: str
    estimated_impact: float
    actual_vwap: float
    total_fill_qty: float
    total_remaining: float
    child_results: list[ExecutionResult]
    predicted_impact: float = 0.0
    actual_impact: float = 0.0

    @property
    def status(self) -> str:
        if self.total_remaining <= 0:
            return "filled"
        if self.total_fill_qty > 0:
            return "partial"
        return "rejected"


class ExecutionEngine(ABC):
    """Abstract execution engine interface with parent-child tracking."""

    def __init__(self) -> None:
        self._parent_summaries: list[ParentFillSummary] = []
        self._calibrator: ImpactCalibrator | None = None

    def set_calibrator(self, calibrator: ImpactCalibrator) -> None:
        self._calibrator = calibrator

    @abstractmethod
    async def execute(self, orders: list[Order]) -> list[ExecutionResult]: ...

    async def execute_sliced(
        self,
        sliced_orders: list[SlicedOrder],
        mid_price: float = 0.0,
    ) -> list[ExecutionResult]:
        """Execute OMS-sliced orders, tracking parent-child relationships."""
        all_results: list[ExecutionResult] = []
        for sliced in sliced_orders:
            child_orders = [c.order for c in sliced.child_orders]
            results = await self.execute(child_orders)
            all_results.extend(results)
            summary = self._build_parent_summary(sliced, results, mid_price)
            self._parent_summaries.append(summary)
            if self._calibrator and summary.actual_impact != 0.0:
                self._calibrator.record(summary.predicted_impact, summary.actual_impact)
        return all_results

    def get_fill_stats(self) -> dict[str, float]:
        """Base implementation — subclasses extend with their own stats."""
        return {}

    def get_extended_stats(self) -> dict[str, Any]:
        """Fill stats extended with impact accuracy and per-algorithm performance."""
        base = self.get_fill_stats()
        base["predicted_impact_accuracy"] = self._compute_impact_accuracy()
        base["oms_algorithm_performance"] = self._compute_algo_performance()
        return base

    @property
    def parent_summaries(self) -> list[ParentFillSummary]:
        return list(self._parent_summaries)

    def _build_parent_summary(
        self,
        sliced: SlicedOrder,
        results: list[ExecutionResult],
        mid_price: float,
    ) -> ParentFillSummary:
        total_qty = 0.0
        total_cost = 0.0
        total_remaining = 0.0
        for r in results:
            if r.status in ("filled", "partial"):
                total_qty += r.fill_qty
                total_cost += r.fill_price * r.fill_qty
            total_remaining += r.remaining_qty
        vwap = total_cost / total_qty if total_qty > 0 else 0.0
        actual_impact = abs(vwap - mid_price) if mid_price > 0 and total_qty > 0 else 0.0
        return ParentFillSummary(
            parent_order=sliced.parent_order,
            algorithm=sliced.algorithm,
            estimated_impact=sliced.estimated_impact,
            actual_vwap=vwap,
            total_fill_qty=total_qty,
            total_remaining=total_remaining,
            child_results=results,
            predicted_impact=sliced.estimated_impact,
            actual_impact=actual_impact,
        )

    def _compute_impact_accuracy(self) -> float:
        """Pearson correlation between predicted and actual impact."""
        pairs = [
            (s.predicted_impact, s.actual_impact)
            for s in self._parent_summaries
            if s.actual_impact > 0
        ]
        if len(pairs) < 2:
            return 0.0
        pred = [p[0] for p in pairs]
        actual = [p[1] for p in pairs]
        mean_p = sum(pred) / len(pred)
        mean_a = sum(actual) / len(actual)
        cov = sum((p - mean_p) * (a - mean_a) for p, a in zip(pred, actual, strict=True))
        var_p = sum((p - mean_p) ** 2 for p in pred)
        var_a = sum((a - mean_a) ** 2 for a in actual)
        denom = (var_p * var_a) ** 0.5
        return cov / denom if denom > 0 else 0.0

    def _compute_algo_performance(self) -> dict[str, dict[str, float]]:
        """Fill quality per OMS algorithm."""
        algo_data: dict[str, list[ParentFillSummary]] = {}
        for s in self._parent_summaries:
            algo_data.setdefault(s.algorithm, []).append(s)
        result: dict[str, dict[str, float]] = {}
        for algo, summaries in algo_data.items():
            filled = [s for s in summaries if s.total_fill_qty > 0]
            if not filled:
                result[algo] = {
                    "count": float(len(summaries)), "fill_rate": 0.0, "avg_slippage": 0.0,
                }
                continue
            slippages = [abs(s.actual_impact) for s in filled]
            result[algo] = {
                "count": float(len(summaries)),
                "fill_rate": len(filled) / len(summaries),
                "avg_slippage": sum(slippages) / len(slippages),
                "impact_error": (
                    sum(abs(s.predicted_impact - s.actual_impact) for s in filled) / len(filled)
                ),
            }
        return result
