"""Single-host runtime orchestrator for isolated live-trading processes."""

from __future__ import annotations

import signal
import time
import multiprocessing as mp
from dataclasses import dataclass, field
from collections.abc import Callable
from typing import Literal

import structlog

from src.runtime.ipc import QueueBackpressureGuard, SignalIntent

logger = structlog.get_logger(__name__)

ProcessTarget = Callable[[mp.Event], None]


def _idle_worker(stop_event: mp.Event) -> None:
    while not stop_event.is_set():
        time.sleep(0.05)


@dataclass
class RuntimeOrchestratorConfig:
    run_mode: Literal["shadow", "micro_live"] = "shadow"
    startup_frozen: bool = True
    quote_capacity: int = 10_000
    execution_capacity: int = 2_000


@dataclass
class RuntimeOrchestrator:
    """Supervisor managing market-data, strategy, and execution processes."""

    config: RuntimeOrchestratorConfig = field(default_factory=RuntimeOrchestratorConfig)
    market_data_target: ProcessTarget = _idle_worker
    strategy_target: ProcessTarget = _idle_worker
    execution_target: ProcessTarget = _idle_worker

    def __post_init__(self) -> None:
        self._ctx = mp.get_context("spawn")
        self._stop_event = self._ctx.Event()
        self._processes: dict[str, mp.Process] = {}
        self._frozen = self.config.startup_frozen
        self._guard = QueueBackpressureGuard(
            quote_capacity=self.config.quote_capacity,
            execution_capacity=self.config.execution_capacity,
        )

    def start(self) -> None:
        if self._processes:
            return
        self._processes = {
            "market_data": self._spawn("market_data", self.market_data_target),
            "strategy": self._spawn("strategy", self.strategy_target),
            "execution": self._spawn("execution", self.execution_target),
        }
        logger.info("runtime_orchestrator_started", run_mode=self.config.run_mode)

    def stop(self, timeout: float = 5.0) -> None:
        self._stop_event.set()
        for proc in self._processes.values():
            proc.join(timeout=timeout)
            if proc.is_alive():
                proc.terminate()
                proc.join(timeout=1.0)
        self._processes.clear()
        logger.info("runtime_orchestrator_stopped")

    def freeze(self) -> None:
        self._frozen = True

    def confirm_resume(self) -> None:
        self._frozen = False

    def can_emit_signals(self) -> bool:
        return not self._frozen and not self._guard.halted

    def submit_execution_backlog(self, backlog_size: int) -> bool:
        return self._guard.check_execution_backlog(backlog_size)

    def filter_quote_backlog(self, events: list) -> list:
        return self._guard.trim_quote_backlog(events)

    def submit_signal_intent(self, _intent: SignalIntent) -> bool:
        return self.can_emit_signals()

    def status(self) -> dict[str, str]:
        status: dict[str, str] = {}
        for name, proc in self._processes.items():
            status[name] = "alive" if proc.is_alive() else "dead"
        return status

    def _spawn(self, name: str, target: ProcessTarget) -> mp.Process:
        proc = self._ctx.Process(
            name=f"runtime-{name}",
            target=target,
            args=(self._stop_event,),
            daemon=True,
        )
        proc.start()
        return proc


def run_supervisor_until_signal() -> None:
    orchestrator = RuntimeOrchestrator()
    orchestrator.start()

    def _shutdown(_sig: int, _frame: object | None) -> None:
        orchestrator.stop()
        raise SystemExit(0)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)
    while True:
        time.sleep(0.5)


if __name__ == "__main__":
    run_supervisor_until_signal()
