"""Unit tests for combined position limit in RiskMonitor."""
from __future__ import annotations

from datetime import datetime, timezone

from src.core.types import AccountState, Position, RiskAction
from src.pipeline.config import RiskConfig
from src.risk.monitor import RiskMonitor


def _make_account(n_positions: int) -> AccountState:
    now = datetime.now(timezone.utc)
    positions = [
        Position(
            entry_price=20000.0,
            lots=1.0,
            contract_type="TX",
            stop_level=19500.0,
            pyramid_level=0,
            entry_timestamp=now,
        )
        for _ in range(n_positions)
    ]
    return AccountState(
        equity=2_000_000.0,
        unrealized_pnl=0.0,
        realized_pnl=0.0,
        margin_used=500_000.0,
        margin_available=1_500_000.0,
        margin_ratio=0.5,
        drawdown_pct=0.0,
        positions=positions,
        timestamp=now,
    )


class TestCombinedPositionLimit:
    def test_limit_exceeded_halts(self) -> None:
        config = RiskConfig(max_combined_positions=3)
        monitor = RiskMonitor(config=config)
        account = _make_account(4)
        action = monitor.check(account)
        assert action == RiskAction.HALT_NEW_ENTRIES

    def test_within_limit_normal(self) -> None:
        config = RiskConfig(max_combined_positions=6)
        monitor = RiskMonitor(config=config)
        account = _make_account(3)
        action = monitor.check(account)
        assert action == RiskAction.NORMAL

    def test_at_limit_halts(self) -> None:
        config = RiskConfig(max_combined_positions=3)
        monitor = RiskMonitor(config=config)
        account = _make_account(3)
        action = monitor.check(account)
        assert action == RiskAction.HALT_NEW_ENTRIES

    def test_none_limit_skipped(self) -> None:
        config = RiskConfig(max_combined_positions=None)
        monitor = RiskMonitor(config=config)
        account = _make_account(100)
        action = monitor.check(account)
        assert action == RiskAction.NORMAL

    def test_default_config_no_limit(self) -> None:
        config = RiskConfig()
        assert config.max_combined_positions is None
