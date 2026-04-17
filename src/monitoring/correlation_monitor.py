"""Live cross-strategy correlation drift monitor.

Tracks rolling pairwise correlations across strategies in the live book
and fires a drift event whenever:

1. Any pairwise correlation has moved more than ``drift_threshold`` from
   its backtest baseline (regime shift destroying diversification), or
2. Trailing combined Sharpe has fallen below
   ``sharpe_drift_trigger × backtest_sharpe`` (edge has collapsed).

The event is consumed by the disaster-stop kill-switch, which flattens
all runners in the live pipeline. Rolling window defaults to 12 hours
at 1-minute bars (720 observations) — adjust per signal timeframe.
"""
from __future__ import annotations

from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime

import numpy as np
import structlog

logger = structlog.get_logger(__name__)


@dataclass
class CorrelationDriftEvent:
    triggered: bool
    pairs_drifted: list[tuple[str, str, float, float]] = field(default_factory=list)
    max_delta: float = 0.0
    sharpe_ratio: float | None = None
    sharpe_triggered: bool = False
    detected_at: str | None = None


@dataclass
class CorrelationMonitorConfig:
    window_bars: int = 720          # default 12h @ 1m
    drift_threshold: float = 0.2    # absolute Δρ
    sharpe_drift_trigger: float | None = None  # e.g. 0.5 → trigger if
                                                # trailing < 0.5 × backtest
    min_observations: int = 60      # need ≥ N samples before reporting
    log_every_check: bool = False


class CorrelationMonitor:
    """Rolling cross-strategy correlation tracker with drift detection."""

    def __init__(
        self,
        strategy_slugs: Iterable[str],
        config: CorrelationMonitorConfig | None = None,
    ) -> None:
        self._slugs = list(strategy_slugs)
        if len(self._slugs) < 2:
            raise ValueError("Need at least 2 strategies to monitor correlation drift")
        self._cfg = config or CorrelationMonitorConfig()
        self._buffers: dict[str, deque[float]] = {
            s: deque(maxlen=self._cfg.window_bars) for s in self._slugs
        }

    # ------------------------------------------------------------ ingestion
    def update(self, strategy_slug: str, ret: float) -> None:
        """Append a return observation for ``strategy_slug``."""
        if strategy_slug not in self._buffers:
            logger.warning("correlation_monitor_unknown_strategy", slug=strategy_slug)
            return
        self._buffers[strategy_slug].append(float(ret))

    def update_all(self, returns: dict[str, float]) -> None:
        """Append returns for multiple strategies simultaneously."""
        for slug, ret in returns.items():
            self.update(slug, ret)

    # -------------------------------------------------------- correlations
    def current_correlation_matrix(self) -> list[list[float]]:
        """Compute rolling correlation matrix from latest aligned tails.

        Returns identity matrix when any buffer has fewer than
        ``min_observations`` samples.
        """
        n = len(self._slugs)
        lengths = [len(self._buffers[s]) for s in self._slugs]
        min_len = min(lengths) if lengths else 0
        if min_len < self._cfg.min_observations:
            return np.eye(n).tolist()
        tail = np.array(
            [list(self._buffers[s])[-min_len:] for s in self._slugs],
            dtype=np.float64,
        )
        with np.errstate(divide="ignore", invalid="ignore"):
            corr = np.corrcoef(tail)
        return np.nan_to_num(corr, nan=0.0).tolist()

    # ------------------------------------------------------------ trigger
    def check_drift(
        self,
        baseline_correlation: list[list[float]] | np.ndarray,
        trailing_sharpe: float | None = None,
        backtest_sharpe: float | None = None,
    ) -> CorrelationDriftEvent:
        """Compare current rolling correlations against ``baseline_correlation``.

        Fires a drift event if any pairwise correlation has moved by more
        than ``drift_threshold`` OR if the ratio
        ``trailing_sharpe / backtest_sharpe`` has fallen below
        ``sharpe_drift_trigger`` (when configured).
        """
        current = np.array(self.current_correlation_matrix())
        baseline = np.asarray(baseline_correlation)
        n = len(self._slugs)
        if baseline.shape != (n, n):
            raise ValueError(
                f"baseline correlation shape {baseline.shape} != ({n}, {n})",
            )

        pairs_drifted: list[tuple[str, str, float, float]] = []
        max_delta = 0.0
        for i in range(n):
            for j in range(i + 1, n):
                b_ij = float(baseline[i, j])
                c_ij = float(current[i, j])
                delta = abs(c_ij - b_ij)
                if delta > max_delta:
                    max_delta = delta
                if delta > self._cfg.drift_threshold:
                    pairs_drifted.append(
                        (self._slugs[i], self._slugs[j], b_ij, c_ij),
                    )

        sharpe_ratio: float | None = None
        sharpe_triggered = False
        if (
            self._cfg.sharpe_drift_trigger is not None
            and trailing_sharpe is not None
            and backtest_sharpe is not None
            and abs(backtest_sharpe) > 1e-9
        ):
            sharpe_ratio = trailing_sharpe / backtest_sharpe
            if sharpe_ratio < self._cfg.sharpe_drift_trigger:
                sharpe_triggered = True

        triggered = bool(pairs_drifted) or sharpe_triggered

        if triggered or self._cfg.log_every_check:
            logger.warning(
                "correlation_drift_check",
                triggered=triggered,
                n_pairs_drifted=len(pairs_drifted),
                max_delta=round(max_delta, 4),
                sharpe_ratio=(
                    round(sharpe_ratio, 4) if sharpe_ratio is not None else None
                ),
                sharpe_triggered=sharpe_triggered,
            )

        return CorrelationDriftEvent(
            triggered=triggered,
            pairs_drifted=pairs_drifted,
            max_delta=max_delta,
            sharpe_ratio=sharpe_ratio,
            sharpe_triggered=sharpe_triggered,
            detected_at=datetime.now().isoformat() if triggered else None,
        )

    def reset(self) -> None:
        """Clear all rolling buffers (e.g. on session reset)."""
        for slug in self._slugs:
            self._buffers[slug].clear()

    @property
    def slugs(self) -> list[str]:
        return list(self._slugs)
