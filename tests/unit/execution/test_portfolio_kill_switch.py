"""Unit tests for PortfolioKillSwitch (US-014)."""
from __future__ import annotations

from typing import Any

import numpy as np
import pytest

from src.execution.portfolio_kill_switch import (
    KillSwitchTrigger,
    PortfolioKillSwitch,
    _flatten_orders_for_runner,
)
from src.monitoring.correlation_monitor import (
    CorrelationMonitor,
    CorrelationMonitorConfig,
)


class _FakePos:
    def __init__(
        self,
        position_id: str,
        direction: str,
        lots: float,
        contract_type: str = "large",
    ) -> None:
        self.position_id = position_id
        self.direction = direction
        self.lots = lots
        self.contract_type = contract_type


class _FakeRunner:
    def __init__(
        self,
        session_id: str,
        strategy_slug: str,
        positions: list[_FakePos],
        symbol: str = "TX",
    ) -> None:
        self.session_id = session_id
        self.strategy_slug = strategy_slug
        self.symbol = symbol
        self.positions = positions


class _FakePipelineManager:
    def __init__(self, runners: dict[str, _FakeRunner]) -> None:
        self._runners = runners


class _RecordingExecutor:
    def __init__(self) -> None:
        self.calls: list[list[Any]] = []

    async def __call__(self, orders: list[Any]) -> None:
        self.calls.append(orders)


class TestFlattenOrdersForRunner:
    def test_empty_runner_yields_no_orders(self) -> None:
        runner = _FakeRunner("s1", "alpha", positions=[])
        assert _flatten_orders_for_runner(runner) == []

    def test_long_position_becomes_sell(self) -> None:
        runner = _FakeRunner(
            "s1", "alpha",
            positions=[_FakePos("p1", "long", 3.0)],
        )
        orders = _flatten_orders_for_runner(runner)
        assert len(orders) == 1
        assert orders[0].side == "sell"
        assert orders[0].lots == 3.0
        assert orders[0].order_type == "market"
        assert orders[0].reason == "portfolio_kill_switch"
        assert orders[0].metadata["strategy_slug"] == "alpha"

    def test_short_position_becomes_buy(self) -> None:
        runner = _FakeRunner(
            "s1", "beta",
            positions=[_FakePos("p1", "short", 2.0)],
        )
        orders = _flatten_orders_for_runner(runner)
        assert orders[0].side == "buy"

    def test_zero_lots_skipped(self) -> None:
        runner = _FakeRunner(
            "s1", "alpha",
            positions=[_FakePos("p1", "long", 0.0)],
        )
        assert _flatten_orders_for_runner(runner) == []

    def test_multiple_positions_all_flattened(self) -> None:
        runner = _FakeRunner(
            "s1", "alpha",
            positions=[
                _FakePos("p1", "long", 2.0),
                _FakePos("p2", "long", 1.0),
            ],
        )
        orders = _flatten_orders_for_runner(runner)
        assert len(orders) == 2
        assert {o.metadata["position_id"] for o in orders} == {"p1", "p2"}


class TestTrigger:
    @pytest.mark.asyncio
    async def test_trigger_flattens_every_runner(self) -> None:
        pm = _FakePipelineManager({
            "s1": _FakeRunner(
                "s1", "alpha",
                positions=[_FakePos("p1", "long", 2.0)],
            ),
            "s2": _FakeRunner(
                "s2", "beta",
                positions=[_FakePos("p2", "short", 1.0)],
            ),
            "s3": _FakeRunner("s3", "gamma", positions=[]),  # no positions
        })
        exec_fn = _RecordingExecutor()
        kill = PortfolioKillSwitch(pm, exec_fn)  # type: ignore[arg-type]
        record = await kill.trigger(reason="correlation_drift")
        assert isinstance(record, KillSwitchTrigger)
        assert record.orders_issued == 2
        assert set(record.runners_affected) == {"s1", "s2"}
        assert len(exec_fn.calls) == 1
        assert len(exec_fn.calls[0]) == 2

    @pytest.mark.asyncio
    async def test_disarmed_skips_trigger(self) -> None:
        pm = _FakePipelineManager({
            "s1": _FakeRunner(
                "s1", "alpha",
                positions=[_FakePos("p1", "long", 2.0)],
            ),
        })
        exec_fn = _RecordingExecutor()
        kill = PortfolioKillSwitch(pm, exec_fn)  # type: ignore[arg-type]
        kill.disarm()
        record = await kill.trigger(reason="test")
        assert record.orders_issued == 0
        assert record.reason.startswith("ignored:")
        assert exec_fn.calls == []

    @pytest.mark.asyncio
    async def test_trigger_auto_disarms(self) -> None:
        pm = _FakePipelineManager({
            "s1": _FakeRunner(
                "s1", "alpha",
                positions=[_FakePos("p1", "long", 2.0)],
            ),
        })
        exec_fn = _RecordingExecutor()
        kill = PortfolioKillSwitch(pm, exec_fn)  # type: ignore[arg-type]
        assert kill.armed is True
        await kill.trigger(reason="test")
        # Auto-disarms so we don't keep firing
        assert kill.armed is False

    @pytest.mark.asyncio
    async def test_arm_re_enables(self) -> None:
        pm = _FakePipelineManager({})
        kill = PortfolioKillSwitch(pm, _RecordingExecutor())  # type: ignore[arg-type]
        kill.disarm()
        assert kill.armed is False
        kill.arm()
        assert kill.armed is True

    @pytest.mark.asyncio
    async def test_arm_resets_attached_monitor(self) -> None:
        """arm() clears the CorrelationMonitor's rolling buffers so a lingering
        drift condition has to re-accumulate before the switch can re-fire."""
        pm = _FakePipelineManager({})
        kill = PortfolioKillSwitch(pm, _RecordingExecutor())  # type: ignore[arg-type]
        cfg = CorrelationMonitorConfig(min_observations=10)
        monitor = CorrelationMonitor(["a", "b"], cfg)
        kill.attach_monitor(monitor)
        # Prime buffer
        for _ in range(50):
            monitor.update_all({"a": 0.01, "b": 0.01})
        assert len(monitor._buffers["a"]) == 50
        kill.arm()
        assert len(monitor._buffers["a"]) == 0
        assert kill.armed is True

    @pytest.mark.asyncio
    async def test_execute_fn_exception_doesnt_break(self) -> None:
        pm = _FakePipelineManager({
            "s1": _FakeRunner(
                "s1", "alpha",
                positions=[_FakePos("p1", "long", 2.0)],
            ),
        })

        async def exploding_exec(_orders: list[Any]) -> None:
            raise RuntimeError("broker down")

        kill = PortfolioKillSwitch(pm, exploding_exec)  # type: ignore[arg-type]
        # Should not raise — exceptions get logged
        record = await kill.trigger(reason="test")
        assert record.orders_issued == 1
        assert len(kill.triggers) == 1


class TestCorrelationDriftIntegration:
    @pytest.mark.asyncio
    async def test_attach_monitor_and_drift_triggers_kill(self) -> None:
        pm = _FakePipelineManager({
            "s1": _FakeRunner(
                "s1", "alpha",
                positions=[_FakePos("p1", "long", 2.0)],
            ),
        })
        exec_fn = _RecordingExecutor()
        kill = PortfolioKillSwitch(pm, exec_fn)  # type: ignore[arg-type]

        cfg = CorrelationMonitorConfig(min_observations=50, drift_threshold=0.2)
        monitor = CorrelationMonitor(["a", "b"], cfg)
        kill.attach_monitor(monitor)

        # Feed strongly-correlated returns
        rng = np.random.default_rng(7)
        for _ in range(200):
            base = float(rng.normal(0, 0.01))
            monitor.update_all({"a": base, "b": base + float(rng.normal(0, 0.001))})

        event = await kill.check_correlation_drift(
            baseline_correlation=np.eye(2),
        )
        assert event is not None and event.triggered is True
        # Kill-switch should have fired
        assert len(exec_fn.calls) == 1
        assert kill.armed is False

    @pytest.mark.asyncio
    async def test_no_monitor_check_is_noop(self) -> None:
        pm = _FakePipelineManager({})
        kill = PortfolioKillSwitch(pm, _RecordingExecutor())  # type: ignore[arg-type]
        event = await kill.check_correlation_drift(
            baseline_correlation=[[1.0, 0.0], [0.0, 1.0]],
        )
        assert event is None
