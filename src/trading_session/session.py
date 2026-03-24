"""TradingSession and SessionSnapshot dataclasses."""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime

from src.broker_gateway.types import LivePosition


@dataclass
class SessionSnapshot:
    timestamp: datetime
    equity: float
    unrealized_pnl: float
    realized_pnl: float
    drawdown_pct: float
    peak_equity: float
    positions: list[LivePosition] = field(default_factory=list)
    last_signal: dict | None = None
    trade_count: int = 0

    @classmethod
    def compute(
        cls,
        equity: float,
        peak_equity: float,
        unrealized_pnl: float,
        realized_pnl: float,
        positions: list[LivePosition] | None = None,
        last_signal: dict | None = None,
        trade_count: int = 0,
    ) -> SessionSnapshot:
        """Create a snapshot with auto-computed drawdown."""
        peak = max(peak_equity, equity)
        dd = (peak - equity) / peak * 100 if peak > 0 else 0.0
        return cls(
            timestamp=datetime.now(),
            equity=equity,
            unrealized_pnl=unrealized_pnl,
            realized_pnl=realized_pnl,
            drawdown_pct=dd,
            peak_equity=peak,
            positions=positions or [],
            last_signal=last_signal,
            trade_count=trade_count,
        )


@dataclass
class TradingSession:
    session_id: str
    account_id: str
    strategy_slug: str
    symbol: str
    status: str  # "active" | "paused" | "stopped"
    started_at: datetime
    initial_equity: float
    current_snapshot: SessionSnapshot | None = None
    peak_equity: float = 0.0
    deployed_candidate_id: int | None = None

    @classmethod
    def create(
        cls,
        account_id: str,
        strategy_slug: str,
        symbol: str,
        initial_equity: float = 0.0,
        status: str = "stopped",
    ) -> TradingSession:
        return cls(
            session_id=str(uuid.uuid4()),
            account_id=account_id,
            strategy_slug=strategy_slug,
            symbol=symbol,
            status=status,
            started_at=datetime.now(),
            initial_equity=initial_equity,
            peak_equity=initial_equity,
        )
