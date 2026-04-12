"""Single-host runtime orchestrator for isolated live-trading processes.

Multi-strategy support: a single account can host N active trading sessions,
each running as its own spawned subprocess. The orchestrator fans out by
session_id — one strategy process per TradingSession — and leaves the
market_data and execution processes shared across sessions.

This is the "spawn-N-processes" option from the plan; it keeps per-strategy
blast radius small (a crash in one strategy process does not take down the
others) at the cost of some process overhead. The strategy worker target
function is the injection point where a future PositionEngine + live-bar
pipeline will be wired; today the default is still an idle sleep so this
module does not yet drive real trading by itself.
"""

from __future__ import annotations

import multiprocessing as mp
import signal
import time
from collections.abc import Callable
from dataclasses import dataclass, field
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
    """Supervisor managing market-data, strategy, and execution processes.

    `strategy_targets` maps session_id → worker target so multiple
    strategies can run concurrently. Passing a single `strategy_target` is
    still supported for backward compatibility and is treated as a
    single-session named "default".
    """

    config: RuntimeOrchestratorConfig = field(default_factory=RuntimeOrchestratorConfig)
    market_data_target: ProcessTarget = _idle_worker
    strategy_target: ProcessTarget = _idle_worker
    strategy_targets: dict[str, ProcessTarget] | None = None
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
        # Normalize strategy targets into the fan-out dict form
        if self.strategy_targets is None:
            self.strategy_targets = {"default": self.strategy_target}

    def start(self) -> None:
        if self._processes:
            return
        processes: dict[str, mp.Process] = {
            "market_data": self._spawn("market_data", self.market_data_target),
        }
        for session_id, target in (self.strategy_targets or {}).items():
            name = f"strategy-{session_id}"
            processes[name] = self._spawn(name, target)
        processes["execution"] = self._spawn("execution", self.execution_target)
        self._processes = processes
        logger.info(
            "runtime_orchestrator_started",
            run_mode=self.config.run_mode,
            strategy_sessions=list((self.strategy_targets or {}).keys()),
        )

    def get_strategy_processes(self) -> dict[str, mp.Process]:
        """Return session_id → Process mapping for the live strategy workers.

        Used by supervisors that want to restart a single crashed strategy
        without touching the market-data or execution processes.
        """
        return {
            name.removeprefix("strategy-"): proc
            for name, proc in self._processes.items()
            if name.startswith("strategy-")
        }

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
