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
        data_source: str | None = None,
        source_label: str | None = None,
        termination_eligible: bool | None = None,
    ) -> None:
        run: dict[str, Any] = {
            "tool": tool,
            "params": params,
            "metrics": metrics,
            "scenario": scenario,
            "strategy": strategy,
            "timestamp": datetime.now(UTC).isoformat(),
        }
        if data_source is not None:
            run["data_source"] = data_source
        if source_label is not None:
            run["source_label"] = source_label
        if termination_eligible is not None:
            run["termination_eligible"] = termination_eligible
        self._runs.append(run)

    def get_all(self, sort_by: str = "sortino") -> list[dict[str, Any]]:
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
