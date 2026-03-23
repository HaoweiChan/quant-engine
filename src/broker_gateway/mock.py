"""MockGateway — synthetic account data for dashboard development."""
from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np

from src.broker_gateway.abc import BrokerGateway
from src.broker_gateway.types import AccountSnapshot, Fill, LivePosition


class MockGateway(BrokerGateway):
    """Always-connected gateway returning synthetic data for dev/testing."""

    def __init__(
        self,
        initial_equity: float = 2_000_000.0,
        seed: int = 42,
        cache_ttl: float = 5.0,
    ) -> None:
        super().__init__(cache_ttl=cache_ttl)
        self._initial = initial_equity
        self._rng = np.random.default_rng(seed)
        self._equity_path: list[float] = [initial_equity]
        self._step = 0

    @property
    def broker_name(self) -> str:
        return "Mock"

    @property
    def is_connected(self) -> bool:
        return True

    def connect(self) -> None:
        pass

    def disconnect(self) -> None:
        pass

    def _fetch_snapshot(self) -> AccountSnapshot:
        self._step += 1
        ret = self._rng.normal(0.0003, 0.012)
        new_eq = self._equity_path[-1] * (1 + ret)
        self._equity_path.append(new_eq)
        peak = max(self._equity_path)
        dd = (peak - new_eq) / peak * 100 if peak > 0 else 0.0
        positions = [
            LivePosition("TX", "long", 3, 20150.0, 20150.0 + self._rng.normal(0, 100),
                         self._rng.normal(20000, 15000), 400_000.0),
            LivePosition("MTX", "long", 4, 20450.0, 20450.0 + self._rng.normal(0, 80),
                         self._rng.normal(8000, 5000), 50_000.0),
        ]
        unrealized = sum(p.unrealized_pnl for p in positions)
        margin_used = sum(p.margin_required for p in positions)
        fills = [
            Fill(datetime.now() - timedelta(minutes=int(self._rng.integers(5, 120))),
                 "TX", "buy", 20100.0 + self._rng.normal(0, 50), 1.0, f"mock-{self._step}", 25.0),
        ]
        return AccountSnapshot(
            connected=True,
            timestamp=datetime.now(),
            equity=new_eq,
            cash=new_eq - margin_used,
            unrealized_pnl=unrealized,
            realized_pnl_today=self._rng.normal(5000, 20000),
            margin_used=margin_used,
            margin_available=new_eq - margin_used,
            positions=positions,
            recent_fills=fills,
        )

    def get_equity_history(self, days: int = 30) -> list[tuple[datetime, float]]:
        rng = np.random.default_rng(99)
        eq = self._initial
        result: list[tuple[datetime, float]] = []
        now = datetime.now()
        for i in range(days):
            eq *= 1 + rng.normal(0.0003, 0.012)
            result.append((now - timedelta(days=days - i), eq))
        return result
