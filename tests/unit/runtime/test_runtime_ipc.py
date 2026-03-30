"""Unit tests for runtime IPC contracts and orchestrator guards."""

from __future__ import annotations

import time

from src.runtime.ipc import QueueBackpressureGuard
from src.runtime.ipc import ExecutionCommand
from src.runtime.ipc import SequenceGuard
from src.runtime.ipc import SignalIntent
from src.runtime.ipc import QuoteEvent
from src.runtime.orchestrator import RuntimeOrchestrator
from src.runtime.orchestrator import RuntimeOrchestratorConfig


def _quote(seq: int, symbol: str = "TX") -> QuoteEvent:
    return QuoteEvent(
        stream_id="quote-stream",
        seq=seq,
        symbol=symbol,
        ts_ns=1_000_000 + seq,
        bid=20_000.0,
        ask=20_001.0,
        last=20_000.5,
    )


def test_ipc_round_trip() -> None:
    quote = _quote(1)
    intent = SignalIntent(
        stream_id="signal-stream",
        seq=2,
        symbol="TX",
        side="buy",
        quantity=1,
        ts_ns=2_000_000,
        reason="entry",
    )
    command = ExecutionCommand(
        intent_id="intent-1",
        symbol="TX",
        side="buy",
        quantity=1,
        ts_ns=3_000_000,
        policy="adaptive",
    )
    assert QuoteEvent.from_payload(quote.to_payload()) == quote
    assert SignalIntent.from_payload(intent.to_payload()) == intent
    assert ExecutionCommand.from_payload(command.to_payload()) == command


def test_sequence_guard_rejects_stale_and_duplicate() -> None:
    guard = SequenceGuard()
    assert guard.accept("quotes", 10)
    assert not guard.accept("quotes", 10)  # duplicate
    assert not guard.accept("quotes", 9)  # stale
    assert guard.accept("quotes", 11)


def test_queue_backpressure_trim_and_halt() -> None:
    guard = QueueBackpressureGuard(quote_capacity=2, execution_capacity=3)
    events = [_quote(1, "TX"), _quote(2, "TX"), _quote(3, "MTX")]
    trimmed = guard.trim_quote_backlog(events)
    assert len(trimmed) == 2
    assert {item.symbol for item in trimmed} == {"TX", "MTX"}
    assert guard.check_execution_backlog(backlog_size=4)
    assert guard.halted
    assert not guard.check_execution_backlog(backlog_size=1)
    assert not guard.halted


def test_runtime_orchestrator_start_stop_and_freeze_gate() -> None:
    orchestrator = RuntimeOrchestrator(
        RuntimeOrchestratorConfig(
            run_mode="shadow",
            startup_frozen=True,
            execution_capacity=5,
        ),
    )
    orchestrator.start()
    time.sleep(0.2)
    status = orchestrator.status()
    assert status["market_data"] == "alive"
    assert status["strategy"] == "alive"
    assert status["execution"] == "alive"
    assert not orchestrator.can_emit_signals()
    orchestrator.confirm_resume()
    assert orchestrator.can_emit_signals()
    assert orchestrator.submit_execution_backlog(backlog_size=3) is False
    assert orchestrator.submit_execution_backlog(backlog_size=10) is True
    assert not orchestrator.can_emit_signals()
    orchestrator.stop()
