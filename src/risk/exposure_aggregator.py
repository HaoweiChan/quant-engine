"""Aggregate open-position exposure across all sessions on an account.

The LivePortfolio feature lets paper and live sessions coexist on a
single account. To keep the account-level risk gates honest, paper
positions must be counted in margin and exposure calculations — a
paper strategy cannot silently consume margin headroom and cause a
live order to underestimate its risk.

This module is the read-side utility the pre-trade gates call. It
takes a `SessionExposure` snapshot per session (see
`ExposureProvider`) and folds them into one `AccountExposure`
keyed by account.

Capital isolation invariant remains intact: a paper session's P&L
and virtual_equity never flow through here. The aggregator deals
only with position lots + margin_per_unit so that paper exposure
contributes to risk but not to cash accounting.
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Protocol

from src.trading_session.session import TradingSession


@dataclass
class SessionExposure:
    """Per-session open-position exposure snapshot."""
    session_id: str
    mode: str  # "paper" | "live"
    lots: float
    margin_used: float
    position_count: int


@dataclass
class AccountExposure:
    """Summed exposure across every session on one account."""
    account_id: str
    total_lots: float = 0.0
    total_margin: float = 0.0
    position_count: int = 0
    paper_lots: float = 0.0
    live_lots: float = 0.0
    paper_margin: float = 0.0
    live_margin: float = 0.0
    per_session: list[SessionExposure] = field(default_factory=list)

    @property
    def has_positions(self) -> bool:
        return self.position_count > 0


class ExposureProvider(Protocol):
    """Supplies per-session exposure on demand.

    The orchestrator owns the concrete implementation — it knows how
    to read paper positions from each LiveStrategyRunner's
    PositionEngine and live positions from broker snapshots. This
    module only consumes the resulting `SessionExposure`.
    """

    def for_session(self, session: TradingSession) -> SessionExposure | None: ...


def aggregated_account_exposure(
    account_id: str,
    sessions: Iterable[TradingSession],
    provider: ExposureProvider,
) -> AccountExposure:
    """Fold per-session exposures into an account-level summary.

    Only sessions belonging to ``account_id`` are considered. Sessions
    the provider returns `None` for (e.g. not yet started, or the
    runner has no positions) contribute nothing.
    """
    result = AccountExposure(account_id=account_id)
    for session in sessions:
        if session.account_id != account_id:
            continue
        exposure = provider.for_session(session)
        if exposure is None:
            continue
        result.total_lots += exposure.lots
        result.total_margin += exposure.margin_used
        result.position_count += exposure.position_count
        if exposure.mode == "paper":
            result.paper_lots += exposure.lots
            result.paper_margin += exposure.margin_used
        else:
            result.live_lots += exposure.lots
            result.live_margin += exposure.margin_used
        result.per_session.append(exposure)
    return result
