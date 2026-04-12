"""Tests for RuntimeOrchestrator multi-strategy fan-out."""
from __future__ import annotations

import multiprocessing as mp
import time

import pytest

from src.runtime.orchestrator import RuntimeOrchestrator, RuntimeOrchestratorConfig


def _no_op_worker(stop_event: mp.Event) -> None:
    while not stop_event.is_set():
        time.sleep(0.02)


class TestMultiStrategyFanOut:
    def test_default_single_strategy_backcompat(self) -> None:
        """Passing only strategy_target produces a single 'default' session."""
        orch = RuntimeOrchestrator(
            config=RuntimeOrchestratorConfig(startup_frozen=False),
            market_data_target=_no_op_worker,
            strategy_target=_no_op_worker,
            execution_target=_no_op_worker,
        )
        assert orch.strategy_targets == {"default": _no_op_worker}

    def test_multi_strategy_dict_preserved(self) -> None:
        targets = {
            "session-a": _no_op_worker,
            "session-b": _no_op_worker,
        }
        orch = RuntimeOrchestrator(
            config=RuntimeOrchestratorConfig(startup_frozen=False),
            strategy_targets=targets,
            market_data_target=_no_op_worker,
            execution_target=_no_op_worker,
        )
        assert orch.strategy_targets == targets

    @pytest.mark.timeout(10)
    def test_start_spawns_one_process_per_session(self) -> None:
        orch = RuntimeOrchestrator(
            config=RuntimeOrchestratorConfig(startup_frozen=False),
            strategy_targets={
                "vol_managed_bnh": _no_op_worker,
                "night_session_long": _no_op_worker,
            },
            market_data_target=_no_op_worker,
            execution_target=_no_op_worker,
        )
        try:
            orch.start()
            status = orch.status()
            # market_data + 2 strategies + execution = 4 processes
            assert len(status) == 4
            assert "market_data" in status
            assert "execution" in status
            assert "strategy-vol_managed_bnh" in status
            assert "strategy-night_session_long" in status
            # All should be alive immediately after spawn
            for name, st in status.items():
                assert st == "alive", f"{name} not alive: {st}"
            # get_strategy_processes returns the per-session mapping with
            # the "strategy-" prefix stripped
            strat_procs = orch.get_strategy_processes()
            assert set(strat_procs.keys()) == {
                "vol_managed_bnh", "night_session_long",
            }
        finally:
            orch.stop()

    def test_start_is_idempotent(self) -> None:
        orch = RuntimeOrchestrator(
            config=RuntimeOrchestratorConfig(startup_frozen=False),
            strategy_targets={"a": _no_op_worker},
            market_data_target=_no_op_worker,
            execution_target=_no_op_worker,
        )
        try:
            orch.start()
            initial = orch.status()
            orch.start()  # second call should be a no-op
            second = orch.status()
            assert initial.keys() == second.keys()
        finally:
            orch.stop()
