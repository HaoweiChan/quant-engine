"""Runtime IPC contracts, sequence guards, and queue backpressure helpers."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class QuoteEvent:
    stream_id: str
    seq: int
    symbol: str
    ts_ns: int
    bid: float
    ask: float
    last: float
    version: int = 1

    def to_payload(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "QuoteEvent":
        return cls(**payload)


@dataclass(frozen=True)
class SignalIntent:
    stream_id: str
    seq: int
    symbol: str
    side: str
    quantity: int
    ts_ns: int
    reason: str
    version: int = 1

    def to_payload(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "SignalIntent":
        return cls(**payload)


@dataclass(frozen=True)
class ExecutionCommand:
    intent_id: str
    symbol: str
    side: str
    quantity: int
    ts_ns: int
    policy: str
    version: int = 1

    def to_payload(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "ExecutionCommand":
        return cls(**payload)


@dataclass
class SequenceGuard:
    """Accept only monotonic, idempotent sequence updates per stream."""

    _last_seq_by_stream: dict[str, int] = field(default_factory=dict)
    _seen: set[tuple[str, int]] = field(default_factory=set)

    def accept(self, stream_id: str, seq: int) -> bool:
        key = (stream_id, seq)
        if key in self._seen:
            logger.warning("duplicate_sequence", stream_id=stream_id, seq=seq)
            return False
        last = self._last_seq_by_stream.get(stream_id)
        if last is not None and seq < last:
            logger.warning("stale_sequence", stream_id=stream_id, seq=seq, last_seq=last)
            return False
        self._seen.add(key)
        if last is None or seq > last:
            self._last_seq_by_stream[stream_id] = seq
        return True


@dataclass
class QueueBackpressureGuard:
    """Backpressure controls for quote and execution queues."""

    quote_capacity: int = 10_000
    execution_capacity: int = 2_000
    halted: bool = False

    def trim_quote_backlog(self, events: list[QuoteEvent]) -> list[QuoteEvent]:
        if len(events) <= self.quote_capacity:
            return events
        latest_by_symbol: dict[str, QuoteEvent] = {}
        for event in events:
            existing = latest_by_symbol.get(event.symbol)
            if existing is None or event.ts_ns >= existing.ts_ns:
                latest_by_symbol[event.symbol] = event
        trimmed = sorted(latest_by_symbol.values(), key=lambda item: item.ts_ns)
        logger.warning(
            "quote_queue_saturation",
            backlog=len(events),
            capacity=self.quote_capacity,
            trimmed=len(trimmed),
        )
        return trimmed

    def check_execution_backlog(self, backlog_size: int) -> bool:
        if backlog_size <= self.execution_capacity:
            self.halted = False
            return False
        self.halted = True
        logger.error(
            "execution_queue_saturation",
            backlog=backlog_size,
            capacity=self.execution_capacity,
        )
        return True
