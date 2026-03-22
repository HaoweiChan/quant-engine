"""Session-scoped optimization history tracking."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any


class OptimizationHistory:
    """In-memory log of all simulation runs within a session."""

    def __init__(self) -> None:
        self._runs: list[dict[str, Any]] = []

    def append(
        self,
        tool: str,
        params: dict[str, Any],
        metrics: dict[str, Any],
        scenario: str,
        strategy: str = "pyramid",
    ) -> None:
        self._runs.append({
            "tool": tool,
            "params": params,
            "metrics": metrics,
            "scenario": scenario,
            "strategy": strategy,
            "timestamp": datetime.now(UTC).isoformat(),
        })

    def get_all(self, sort_by: str = "sharpe") -> list[dict[str, Any]]:
        if not self._runs:
            return []
        return sorted(
            self._runs,
            key=lambda r: r.get("metrics", {}).get(sort_by, float("-inf")),
            reverse=True,
        )

    @property
    def count(self) -> int:
        return len(self._runs)
