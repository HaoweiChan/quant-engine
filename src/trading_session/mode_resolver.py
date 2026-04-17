"""Effective execution mode resolver.

Pure function that answers: "what mode (paper/live) is this session
running in right now?" Applied at runner build time, by API handlers
for display, and by the risk exposure aggregator to bucket positions.

Precedence (highest first):
  1. Portfolio mode  — if session.portfolio_id is set, the portfolio
     owns the decision; session.execution_mode is ignored.
  2. Session override — session.execution_mode, if set.
  3. Account default  — account.sandbox_mode → "paper" else "live".

This ladder preserves current behaviour bit-for-bit for deployments
that predate the LivePortfolio feature: every session has NULL for
the three new fields, so the resolver falls through to the account
branch, which matches the old hardcoded PaperExecutor branch because
`sandbox_mode=True` is the default today.
"""
from __future__ import annotations

from typing import Literal, Protocol

from src.trading_session.session import TradingSession

ExecutionMode = Literal["paper", "live"]


class _AccountLike(Protocol):
    sandbox_mode: bool


class _PortfolioLike(Protocol):
    mode: ExecutionMode


class _PortfolioStoreLike(Protocol):
    def get(self, portfolio_id: str) -> _PortfolioLike | None: ...


class _AccountStoreLike(Protocol):
    def load_account(self, account_id: str) -> _AccountLike | None: ...


def resolve_session_mode(
    session: TradingSession,
    *,
    portfolio_store: _PortfolioStoreLike | None = None,
    account_store: _AccountStoreLike | None = None,
    default_mode: ExecutionMode = "paper",
) -> ExecutionMode:
    """Resolve a session's effective execution mode.

    Args:
        session: The TradingSession whose mode we need.
        portfolio_store: Optional portfolio store. Required when
            session.portfolio_id is set; otherwise unused.
        account_store: Optional account store. Required when the
            session inherits from the account (both explicit fields
            are None); otherwise unused.
        default_mode: Terminal fallback when neither portfolio nor
            session nor account provides a mode. Defaults to 'paper'
            so ambiguity never accidentally routes a strategy live.

    Returns:
        "paper" or "live".
    """
    if session.portfolio_id:
        if portfolio_store is None:
            raise ValueError(
                f"session {session.session_id} has portfolio_id={session.portfolio_id!r} "
                "but no portfolio_store was provided to resolve it"
            )
        portfolio = portfolio_store.get(session.portfolio_id)
        if portfolio is None:
            raise ValueError(
                f"session {session.session_id} references unknown portfolio "
                f"{session.portfolio_id!r}"
            )
        return portfolio.mode

    if session.execution_mode is not None:
        return session.execution_mode

    if account_store is not None:
        account = account_store.load_account(session.account_id)
        if account is not None:
            return "paper" if account.sandbox_mode else "live"

    return default_mode
