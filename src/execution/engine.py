"""Execution Engine: abstract interface and result types for order execution."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from src.core.types import Order


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


class ExecutionEngine(ABC):
    """Abstract execution engine interface."""

    @abstractmethod
    async def execute(self, orders: list[Order]) -> list[ExecutionResult]: ...

    @abstractmethod
    def get_fill_stats(self) -> dict[str, float]: ...
