"""LivePortfolioManager — CRUD and mode-flip lifecycle for LivePortfolios.

This manager is the sibling of `SessionManager` — it owns the portfolio
store and the binding/unbinding of sessions to a portfolio, and it
implements the all-or-nothing mode flip with precondition checks
(members flat + stopped/paused) as spelled out in
`.claude/plans/in-our-war-room-squishy-squirrel.md`.
"""
from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Literal

import structlog

from src.trading_session.manager import SessionManager
from src.trading_session.portfolio_db import LivePortfolio, LivePortfolioStore
from src.trading_session.session import TradingSession

logger = structlog.get_logger(__name__)

ExecutionMode = Literal["paper", "live"]

# Tolerance for floating-point sum-of-shares comparisons. Matches the
# epsilon used by SessionManager.set_equity_shares_batch.
_SUM_EPS = 1e-6


class PortfolioFlipError(Exception):
    """Raised when a portfolio mode flip fails its precondition check.

    The `reasons` field lists, per offending session, why the flip is
    unsafe so the War Room UI can surface actionable diagnostics
    instead of a generic 'cannot flip' message.
    """

    def __init__(self, portfolio_id: str, reasons: list[dict]) -> None:
        self.portfolio_id = portfolio_id
        self.reasons = reasons
        summary = ", ".join(
            f"{r.get('session_id', '?')}: {r.get('reason', '?')}" for r in reasons
        ) or "no reasons"
        super().__init__(
            f"Portfolio {portfolio_id!r} flip rejected — {summary}"
        )


class LivePortfolioManager:
    """Manages LivePortfolio lifecycle and member binding.

    Thread-safety: the `_flip_lock` serializes `flip_mode` calls across
    FastAPI worker threads so two concurrent POST /flip-mode requests
    cannot race past the precondition scan.
    """

    def __init__(
        self,
        store: LivePortfolioStore,
        session_manager: SessionManager,
        on_mode_changed: Callable[[LivePortfolio], None] | None = None,
    ) -> None:
        """Construct a manager.

        Args:
            store: Persistence for portfolios.
            session_manager: Source of truth for member sessions —
                used for precondition scans and for cascading writes
                of `portfolio_id` onto sessions.
            on_mode_changed: Optional callback fired after a successful
                flip. Receives the updated portfolio. The orchestrator
                subscribes here to respawn member runners.
        """
        self._store = store
        self._sessions = session_manager
        self._on_mode_changed = on_mode_changed
        self._flip_lock = threading.Lock()

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def create_portfolio(
        self,
        name: str,
        account_id: str,
        mode: ExecutionMode = "paper",
        initial_equity: float | None = None,
    ) -> LivePortfolio:
        portfolio = LivePortfolio.create(
            name=name,
            account_id=account_id,
            mode=mode,
            initial_equity=initial_equity,
        )
        self._store.save(portfolio)
        logger.info(
            "portfolio_created",
            portfolio_id=portfolio.portfolio_id,
            name=name,
            account_id=account_id,
            mode=mode,
            initial_equity=initial_equity,
        )
        return portfolio

    def get_portfolio(self, portfolio_id: str) -> LivePortfolio | None:
        return self._store.get(portfolio_id)

    def list_portfolios(self, account_id: str | None = None) -> list[LivePortfolio]:
        if account_id is not None:
            return self._store.load_for_account(account_id)
        return self._store.load_all()

    def list_members(self, portfolio_id: str) -> list[TradingSession]:
        return [
            s for s in self._sessions.get_all_sessions()
            if s.portfolio_id == portfolio_id
        ]

    def delete_portfolio(self, portfolio_id: str) -> None:
        """Delete a portfolio. Detaches all member sessions first."""
        members = self.list_members(portfolio_id)
        for session in members:
            self.detach_session(session.session_id)
        if not self._store.delete(portfolio_id):
            raise ValueError(f"Portfolio not found: {portfolio_id}")
        logger.info("portfolio_deleted", portfolio_id=portfolio_id)

    # ------------------------------------------------------------------
    # Membership
    # ------------------------------------------------------------------

    def attach_session(self, portfolio_id: str, session_id: str) -> TradingSession:
        """Attach a session to a portfolio.

        Validates the session's account matches the portfolio's account
        (portfolios are account-scoped; cross-account membership would
        break the equity_share invariant).
        """
        portfolio = self._store.get(portfolio_id)
        if portfolio is None:
            raise ValueError(f"Portfolio not found: {portfolio_id}")
        session = self._sessions.get_session(session_id)
        if session is None:
            raise ValueError(f"Session not found: {session_id}")
        if session.account_id != portfolio.account_id:
            raise ValueError(
                f"Session account {session.account_id!r} does not match "
                f"portfolio account {portfolio.account_id!r}"
            )
        if session.portfolio_id and session.portfolio_id != portfolio_id:
            raise ValueError(
                f"Session {session_id} is already bound to portfolio "
                f"{session.portfolio_id!r}"
            )
        session.portfolio_id = portfolio_id
        if self._sessions._session_db:  # pyright: ignore[reportPrivateUsage]
            self._sessions._session_db.update_portfolio_id(session_id, portfolio_id)
        logger.info(
            "portfolio_member_attached",
            portfolio_id=portfolio_id,
            session_id=session_id,
        )
        # Restore sum(equity_share)==1.0 for the portfolio. Callers wanting
        # explicit weights (load-saved-portfolio flow) override afterwards
        # via batchUpdateEquityShare.
        self._rebalance_to_equal_weights(portfolio_id)
        return session

    def detach_session(self, session_id: str) -> TradingSession:
        session = self._sessions.get_session(session_id)
        if session is None:
            raise ValueError(f"Session not found: {session_id}")
        if session.portfolio_id is None:
            return session
        old = session.portfolio_id
        session.portfolio_id = None
        if self._sessions._session_db:  # pyright: ignore[reportPrivateUsage]
            self._sessions._session_db.update_portfolio_id(session_id, None)
        logger.info(
            "portfolio_member_detached",
            portfolio_id=old,
            session_id=session_id,
        )
        return session

    # ------------------------------------------------------------------
    # Mode flip
    # ------------------------------------------------------------------

    def flip_mode(
        self,
        portfolio_id: str,
        new_mode: ExecutionMode,
    ) -> LivePortfolio:
        """Atomically flip portfolio mode after precondition scan.

        Precondition: every member session must be in 'stopped' or
        'paused' status AND have zero open positions in its current
        snapshot. Violations are accumulated and raised as
        `PortfolioFlipError` with per-session reasons.

        Runtime effect: after the flip is persisted, `on_mode_changed`
        fires so the orchestrator can respawn member runners with the
        new executor. Runners always re-resolve mode at build time, so
        the respawn picks up the new mode cleanly.
        """
        if new_mode not in ("paper", "live"):
            raise ValueError(f"new_mode must be 'paper' or 'live', got {new_mode!r}")

        with self._flip_lock:
            portfolio = self._store.get(portfolio_id)
            if portfolio is None:
                raise ValueError(f"Portfolio not found: {portfolio_id}")

            if portfolio.mode == new_mode:
                # No-op: idempotent flip.
                logger.info(
                    "portfolio_flip_noop",
                    portfolio_id=portfolio_id,
                    mode=new_mode,
                )
                return portfolio

            members = self.list_members(portfolio_id)
            reasons = self._precondition_reasons(members)
            if reasons:
                raise PortfolioFlipError(portfolio_id, reasons)

            self._store.update_mode(portfolio_id, new_mode)
            portfolio.mode = new_mode
            logger.info(
                "portfolio_flipped",
                portfolio_id=portfolio_id,
                new_mode=new_mode,
                member_count=len(members),
            )

        if self._on_mode_changed is not None:
            try:
                self._on_mode_changed(portfolio)
            except Exception:
                logger.exception(
                    "portfolio_mode_change_callback_failed",
                    portfolio_id=portfolio_id,
                )
        return portfolio

    # ------------------------------------------------------------------
    # Allocation invariant
    # ------------------------------------------------------------------

    def rebalance_equal_weights(self, portfolio_id: str) -> list[TradingSession]:
        """Set every portfolio member's equity_share to 1/n.

        Idempotent — already-equal portfolios skip the DB write. The last
        share absorbs rounding remainder so the sum is exactly 1.0.

        Raises:
            ValueError: if portfolio_id is unknown.
        """
        portfolio = self._store.get(portfolio_id)
        if portfolio is None:
            raise ValueError(f"Portfolio not found: {portfolio_id}")
        return self._rebalance_to_equal_weights(portfolio_id)

    def repair_invalid_portfolios(self) -> list[dict]:
        """Scan all portfolios and rebalance those whose member shares are invalid.

        A portfolio is considered invalid when:
          * sum(equity_share) > 1.0 + _SUM_EPS, OR
          * len(members) > 1 and every member's equity_share == 1.0
            (legacy default-share state — sessions were attached without a
            follow-up batch update)

        Returns one dict per repaired portfolio with portfolio_id, name,
        before-shares, after-shares. Valid portfolios are left untouched.
        """
        repaired: list[dict] = []
        for portfolio in self._store.load_all():
            members = self.list_members(portfolio.portfolio_id)
            if len(members) < 2:
                continue
            shares = [m.equity_share for m in members]
            total = sum(shares)
            all_one = all(abs(s - 1.0) < _SUM_EPS for s in shares)
            if total <= 1.0 + _SUM_EPS and not all_one:
                continue
            before = {m.session_id: m.equity_share for m in members}
            updated = self._rebalance_to_equal_weights(portfolio.portfolio_id)
            after = {m.session_id: m.equity_share for m in updated}
            repaired.append({
                "portfolio_id": portfolio.portfolio_id,
                "name": portfolio.name,
                "before": before,
                "after": after,
            })
            logger.warning(
                "portfolio_allocation_repaired",
                portfolio_id=portfolio.portfolio_id,
                name=portfolio.name,
                before=before,
                after=after,
            )
        return repaired

    def _rebalance_to_equal_weights(
        self, portfolio_id: str,
    ) -> list[TradingSession]:
        """Internal: rebalance helper used by attach + repair paths.

        Bypasses SessionManager.set_equity_shares_batch's account-level sum
        guard because rebalancing AWAY from an invalid state (e.g. 3×1.0)
        would otherwise be rejected by the very invariant we are trying
        to restore. The portfolio-local sum is exactly 1.0 after the
        rebalance, so the global account invariant remains satisfied for
        any account whose only oversubscribed portfolio is this one.
        """
        members = self.list_members(portfolio_id)
        n = len(members)
        if n == 0:
            logger.warning(
                "portfolio_rebalance_empty",
                portfolio_id=portfolio_id,
            )
            return []
        # Equal-weight shares with last-absorbs-remainder so sum is exact.
        base_share = round(1.0 / n, 4)
        shares = [base_share] * (n - 1)
        shares.append(round(1.0 - base_share * (n - 1), 4))
        # Idempotency: skip the write if every member is already at target.
        already_equal = all(
            abs(member.equity_share - target) < _SUM_EPS
            for member, target in zip(members, shares)
        )
        if already_equal:
            return members
        session_db = self._sessions._session_db  # pyright: ignore[reportPrivateUsage]
        for member, share in zip(members, shares):
            member.equity_share = share
            if session_db is not None:
                session_db.update_equity_share(member.session_id, share)
        logger.info(
            "portfolio_rebalanced_equal_weights",
            portfolio_id=portfolio_id,
            n=n,
            shares={m.session_id: s for m, s in zip(members, shares)},
        )
        return members

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _precondition_reasons(members: list[TradingSession]) -> list[dict]:
        """Return one reason dict per member that would block a flip.

        A member blocks the flip if:
          * status is not in {'stopped', 'paused'}, OR
          * its current_snapshot reports any open positions.
        """
        reasons: list[dict] = []
        for session in members:
            if session.status not in ("stopped", "paused"):
                reasons.append({
                    "session_id": session.session_id,
                    "strategy_slug": session.strategy_slug,
                    "reason": "session_not_stopped_or_paused",
                    "current_status": session.status,
                })
                continue
            snapshot = session.current_snapshot
            if snapshot is not None and snapshot.positions:
                reasons.append({
                    "session_id": session.session_id,
                    "strategy_slug": session.strategy_slug,
                    "reason": "session_has_open_positions",
                    "position_count": len(snapshot.positions),
                })
        return reasons
