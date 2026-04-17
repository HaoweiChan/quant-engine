"""TradingSession and SessionSnapshot dataclasses."""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Literal

_TAIPEI_TZ = timezone(timedelta(hours=8))

from src.broker_gateway.types import LivePosition

ExecutionMode = Literal["paper", "live"]


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
            timestamp=datetime.now(_TAIPEI_TZ),
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
    # Fraction of the parent account's equity this session is allowed to
    # size positions against. 1.0 = whole account (default, backward
    # compatible). Multiple active sessions on the same account should sum
    # to <= 1.0. See SessionManager.effective_equity() for the read path.
    equity_share: float = 1.0
    # Per-session execution mode override. None = inherit from portfolio (if
    # bound) or fall back to account.sandbox_mode. Set via mode_resolver.
    execution_mode: ExecutionMode | None = None
    # Virtual equity for paper sessions running on a live account. Isolated
    # from account.equity — a paper fill only mutates this field, never the
    # real account balance. None for live sessions.
    virtual_equity: float | None = None
    # Foreign key to a LivePortfolio. When set, the portfolio's mode
    # overrides execution_mode (see mode_resolver.resolve_session_mode).
    portfolio_id: str | None = None

    def __post_init__(self) -> None:
        if not (0.0 < self.equity_share <= 1.0):
            raise ValueError(
                f"equity_share must be in (0, 1], got {self.equity_share!r}"
            )
        if self.execution_mode is not None and self.execution_mode not in ("paper", "live"):
            raise ValueError(
                f"execution_mode must be 'paper', 'live', or None, got {self.execution_mode!r}"
            )

    def effective_equity(self, account_equity: float) -> float:
        """Return the equity budget this session is allowed to size against.

        This is the single injection point for the 60/40-style allocation —
        every live sizing code path that needs the account's capital should
        pass account_equity through this helper so the strategy sees a
        virtual equity base scaled by the session's allocation share.
        """
        return max(0.0, account_equity) * self.equity_share

    @classmethod
    def create(
        cls,
        account_id: str,
        strategy_slug: str,
        symbol: str,
        initial_equity: float = 0.0,
        status: str = "stopped",
        equity_share: float = 1.0,
        execution_mode: ExecutionMode | None = None,
        virtual_equity: float | None = None,
        portfolio_id: str | None = None,
    ) -> TradingSession:
        return cls(
            session_id=str(uuid.uuid4()),
            account_id=account_id,
            strategy_slug=strategy_slug,
            symbol=symbol,
            status=status,
            started_at=datetime.now(_TAIPEI_TZ),
            initial_equity=initial_equity,
            peak_equity=initial_equity,
            equity_share=equity_share,
            execution_mode=execution_mode,
            virtual_equity=virtual_equity,
            portfolio_id=portfolio_id,
        )
