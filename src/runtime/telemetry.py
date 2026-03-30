"""Execution telemetry for latency SLO and fill-quality monitoring."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field


@dataclass
class StageTimestamps:
    quote_ingest_ns: int | None = None
    signal_emit_ns: int | None = None
    order_dispatch_ns: int | None = None
    broker_ack_ns: int | None = None

    def tick_to_order_ms(self) -> float | None:
        if self.quote_ingest_ns is None or self.order_dispatch_ns is None:
            return None
        return (self.order_dispatch_ns - self.quote_ingest_ns) / 1_000_000.0


@dataclass
class RollingP99:
    window_size: int = 256
    _values_ms: deque[float] = field(default_factory=deque)

    def add(self, value_ms: float) -> None:
        if self.window_size <= 0:
            return
        if len(self._values_ms) >= self.window_size:
            self._values_ms.popleft()
        self._values_ms.append(value_ms)

    def p99(self) -> float:
        if not self._values_ms:
            return 0.0
        values = sorted(self._values_ms)
        index = min(int(len(values) * 0.99), len(values) - 1)
        return values[index]


@dataclass
class FillQualityMonitor:
    threshold_bps: float = 2.0
    degrade_ratio: float = 0.20
    window_size: int = 256
    _slippage_bps: deque[float] = field(default_factory=deque)

    def add(self, slippage_bps: float) -> None:
        if self.window_size <= 0:
            return
        if len(self._slippage_bps) >= self.window_size:
            self._slippage_bps.popleft()
        self._slippage_bps.append(abs(slippage_bps))

    def pct_over_threshold(self) -> float:
        if not self._slippage_bps:
            return 0.0
        breaches = sum(1 for value in self._slippage_bps if value > self.threshold_bps)
        return breaches / len(self._slippage_bps)

    def degraded(self) -> bool:
        return self.pct_over_threshold() > self.degrade_ratio
