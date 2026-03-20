"""Tests for Risk Monitor: trigger conditions, staleness, module isolation."""
from __future__ import annotations

import ast
from datetime import UTC, datetime, timedelta
from pathlib import Path

from src.core.types import AccountState, Position, RiskAction
from src.pipeline.config import RiskConfig
from src.risk.monitor import RiskMonitor


def _make_account(
    equity: float = 2_000_000.0,
    drawdown_pct: float = 0.0,
    margin_ratio: float = 0.3,
    ts: datetime | None = None,
    positions: list[Position] | None = None,
) -> AccountState:
    return AccountState(
        equity=equity,
        unrealized_pnl=0.0,
        realized_pnl=0.0,
        margin_used=equity * margin_ratio,
        margin_available=equity * (1 - margin_ratio),
        margin_ratio=margin_ratio,
        drawdown_pct=drawdown_pct,
        positions=positions or [],
        timestamp=ts or datetime.now(UTC),
    )


class TestRiskMonitor:
    def test_normal_returns_normal(self) -> None:
        config = RiskConfig(max_loss=500_000)
        monitor = RiskMonitor(config)
        account = _make_account()
        assert monitor.check(account) == RiskAction.NORMAL

    def test_drawdown_triggers_close_all(self) -> None:
        config = RiskConfig(max_loss=500_000)
        mode_changes: list[str] = []
        monitor = RiskMonitor(config, on_mode_change=mode_changes.append)
        account = _make_account(drawdown_pct=0.30)
        action = monitor.check(account)
        assert action == RiskAction.CLOSE_ALL
        assert "halted" in mode_changes

    def test_low_margin_triggers_reduce(self) -> None:
        config = RiskConfig(margin_ratio_threshold=0.30)
        monitor = RiskMonitor(config)
        pos = Position(
            entry_price=20000, lots=2, contract_type="large",
            stop_level=19800, pyramid_level=0, entry_timestamp=datetime.now(UTC),
        )
        account = _make_account(margin_ratio=0.20, positions=[pos])
        action = monitor.check(account)
        assert action == RiskAction.REDUCE_HALF

    def test_signal_staleness_triggers_halt(self) -> None:
        config = RiskConfig(signal_staleness_hours=2.0)
        mode_changes: list[str] = []
        monitor = RiskMonitor(config, on_mode_change=mode_changes.append)
        now = datetime.now(UTC)
        monitor.update_signal_time(now - timedelta(hours=3))
        account = _make_account(ts=now)
        action = monitor.check(account)
        assert action == RiskAction.HALT_NEW_ENTRIES
        assert "rule_only" in mode_changes

    def test_feed_staleness_triggers_halt(self) -> None:
        config = RiskConfig(feed_staleness_minutes=5.0)
        monitor = RiskMonitor(config)
        now = datetime.now(UTC)
        monitor.update_feed_time(now - timedelta(minutes=10))
        account = _make_account(ts=now)
        action = monitor.check(account)
        assert action == RiskAction.HALT_NEW_ENTRIES

    def test_spread_spike_triggers_halt(self) -> None:
        config = RiskConfig(spread_spike_multiplier=10.0)
        monitor = RiskMonitor(config)
        monitor.update_spread(current=50.0, normal=2.0)
        account = _make_account()
        action = monitor.check(account)
        assert action == RiskAction.HALT_NEW_ENTRIES

    def test_events_recorded(self) -> None:
        config = RiskConfig(max_loss=100)
        monitor = RiskMonitor(config)
        account = _make_account(drawdown_pct=0.10)
        monitor.check(account)
        assert len(monitor.events) > 0
        assert monitor.events[0].action == RiskAction.CLOSE_ALL

    def test_module_isolation(self) -> None:
        """RiskMonitor must not import from position_engine, prediction, or execution."""
        risk_dir = Path(__file__).parent.parent / "src" / "risk"
        forbidden = {"position_engine", "prediction", "execution", "simulator"}
        for py_file in risk_dir.glob("*.py"):
            source = py_file.read_text()
            tree = ast.parse(source)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        parts = alias.name.split(".")
                        for f in forbidden:
                            assert f not in parts, f"{py_file.name} imports {alias.name}"
                elif isinstance(node, ast.ImportFrom) and node.module:
                    parts = node.module.split(".")
                    for f in forbidden:
                        assert f not in parts, f"{py_file.name} imports {node.module}"
