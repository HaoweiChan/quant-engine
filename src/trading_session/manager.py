"""SessionManager — orchestrates all trading sessions."""
from __future__ import annotations

import threading
from typing import Any

import structlog

from src.broker_gateway.registry import GatewayRegistry
from src.broker_gateway.types import AccountSnapshot
from src.trading_session.session import SessionSnapshot, TradingSession
from src.trading_session.session_db import SessionDB
from src.trading_session.store import SnapshotStore

logger = structlog.get_logger(__name__)


class SessionManager:
    """Manages lifecycle of all TradingSession instances."""

    def __init__(
        self,
        registry: GatewayRegistry,
        store: SnapshotStore | None = None,
        session_db: SessionDB | None = None,
    ) -> None:
        self._registry = registry
        self._store = store or SnapshotStore()
        self._session_db = session_db
        self._sessions: dict[str, TradingSession] = {}
        self.halt_active: bool = False
        # Serializes writes that race across FastAPI worker threads —
        # specifically the equity_share allocation path where two concurrent
        # PATCH requests could otherwise see a stale sum-of-shares and both
        # succeed, landing the account over-allocated.
        self._allocation_lock = threading.Lock()

    def restore_from_db(self) -> None:
        """Load persisted sessions from DB, then supplement from account configs."""
        if self._session_db:
            for s in self._session_db.load_all():
                self._sessions[s.session_id] = s
                logger.info("session_restored", session_id=s.session_id,
                            account=s.account_id, strategy=s.strategy_slug)
        # Supplement with config-based strategies not yet in DB
        existing_keys = {
            (s.account_id, s.strategy_slug, s.symbol)
            for s in self._sessions.values()
        }
        for config in self._registry.get_all_configs():
            for strat in config.strategies:
                slug = strat.get("slug", "")
                symbol = strat.get("symbol", "")
                if not slug:
                    continue
                key = (config.id, slug, symbol)
                if key in existing_keys:
                    continue
                session = TradingSession.create(
                    account_id=config.id, strategy_slug=slug,
                    symbol=symbol, status="stopped",
                )
                self._sessions[session.session_id] = session
                if self._session_db:
                    self._session_db.save(session)
                logger.info("session_created_from_config", session_id=session.session_id,
                            account=config.id, strategy=slug, symbol=symbol)

    def restore_from_config(self) -> None:
        """Legacy: create sessions from config only (no DB)."""
        self.restore_from_db()

    def create_session(
        self,
        account_id: str,
        strategy_slug: str,
        symbol: str,
        equity_share: float = 1.0,
    ) -> TradingSession:
        if self._session_db:
            existing = self._session_db.find_session(account_id, strategy_slug, symbol)
            if existing:
                self._sessions[existing.session_id] = existing
                return existing
        session = TradingSession.create(
            account_id, strategy_slug, symbol,
            status="stopped", equity_share=equity_share,
        )
        self._sessions[session.session_id] = session
        if self._session_db:
            self._session_db.save(session)
        return session

    def set_equity_shares_batch(
        self, allocations: list[tuple[str, float]]
    ) -> list[TradingSession]:
        """Atomically update equity_shares for multiple sessions.

        Unlike set_equity_share(), this validates the *final* sum across all
        sessions being updated, allowing reallocation from an invalid state
        (e.g., 3 sessions at 100% each) to a valid one (e.g., 40/30/30).

        Args:
            allocations: List of (session_id, share) tuples. All sessions
                must belong to the same account.

        Returns:
            List of updated TradingSession objects.

        Raises:
            ValueError: If sessions not found, belong to different accounts,
                share out of range, or final sum exceeds 1.0.
        """
        if not allocations:
            return []

        with self._allocation_lock:
            # Resolve all sessions and validate they exist
            sessions: list[TradingSession] = []
            for session_id, share in allocations:
                session = self._sessions.get(session_id)
                if not session:
                    raise ValueError(f"Session not found: {session_id}")
                if not (0.0 < share <= 1.0):
                    raise ValueError(f"equity_share must be in (0, 1], got {share!r}")
                sessions.append(session)

            # Validate all sessions belong to the same account
            account_ids = {s.account_id for s in sessions}
            if len(account_ids) > 1:
                raise ValueError(
                    f"All sessions must belong to the same account, got: {account_ids}"
                )
            account_id = sessions[0].account_id

            # Get session IDs being updated
            updating_ids = {sid for sid, _ in allocations}

            # Calculate sum of shares NOT being updated (use in-memory sessions)
            other_sum = sum(
                s.equity_share
                for s in self._sessions.values()
                if s.account_id == account_id and s.session_id not in updating_ids
            )

            # Calculate new total
            new_shares_sum = sum(share for _, share in allocations)
            total = other_sum + new_shares_sum

            if total > 1.0 + 1e-6:
                raise ValueError(
                    f"Allocation overflow for account {account_id}: "
                    f"other={other_sum:.4f} + new={new_shares_sum:.4f} = {total:.4f} > 1.0"
                )

            # Apply all updates
            updated: list[TradingSession] = []
            for (session_id, share), session in zip(allocations, sessions):
                session.equity_share = share
                if self._session_db:
                    self._session_db.update_equity_share(session_id, share)
                logger.info(
                    "session_equity_share_updated",
                    session_id=session_id,
                    equity_share=share,
                )
                updated.append(session)

            return updated

    def set_equity_share(self, session_id: str, share: float) -> TradingSession:
        """Update a session's equity_share and persist it.

        Enforces the per-account invariant that the sum of equity_shares
        across all sessions on that account does not exceed 1.0 (with a
        1e-6 epsilon for floating-point tolerance).

        Holds self._allocation_lock for the full read-compute-write so
        concurrent PATCH requests from two FastAPI worker threads cannot
        race each other into an over-allocated state.
        """
        with self._allocation_lock:
            session = self._sessions.get(session_id)
            if not session:
                raise ValueError(f"Session not found: {session_id}")
            if not (0.0 < share <= 1.0):
                raise ValueError(f"equity_share must be in (0, 1], got {share!r}")

            if self._session_db:
                other_sum = self._session_db.sum_equity_share_for_account(
                    session.account_id, exclude_session_id=session_id
                )
            else:
                other_sum = sum(
                    s.equity_share
                    for s in self._sessions.values()
                    if s.account_id == session.account_id and s.session_id != session_id
                )
            if other_sum + share > 1.0 + 1e-6:
                raise ValueError(
                    f"Allocation overflow for account {session.account_id}: "
                    f"existing sum={other_sum:.4f} + new={share:.4f} > 1.0"
                )

            session.equity_share = share
            if self._session_db:
                self._session_db.update_equity_share(session_id, share)
            logger.info(
                "session_equity_share_updated",
                session_id=session_id,
                equity_share=share,
            )
            return session

    def get_effective_equity(self, session_id: str) -> float | None:
        """Return the equity-share-adjusted equity budget for a session.

        **Status (2026-04-13)**: defined but NOT yet called from any live
        sizing path. The live strategy worker in
        `src/runtime/orchestrator.py` is still an `_idle_worker`
        placeholder, so this helper has no in-tree callers today. It
        exists as the documented injection point the worker will use
        once wired. Do not remove — it's the contract between the
        equity_share plumbing (done in this Ralph run) and the future
        multi-strategy live worker.

        Fetches the parent account's current equity snapshot via the
        broker gateway and multiplies by the session's equity_share.
        Callers that don't have a gateway (tests, offline paths) can
        call `TradingSession.effective_equity()` directly. Returns None
        when the account is disconnected or unknown.
        """
        session = self._sessions.get(session_id)
        if session is None:
            return None
        gw = self._registry.get_gateway(session.account_id)
        if gw is None:
            return None
        acct_snap = gw.get_account_snapshot()
        if not acct_snap.connected:
            return None
        return session.effective_equity(acct_snap.equity)

    def set_execution_mode(
        self, session_id: str, mode: str | None,
    ) -> TradingSession:
        """Set the per-session execution_mode override.

        Rejects the change when the session is bound to a portfolio —
        portfolio-bound sessions inherit the portfolio's mode, so a
        per-session override would be invisible anyway. The War Room
        UI should disable the control in that case; this server-side
        check is the safety net.

        Args:
            session_id: Target session.
            mode: "paper", "live", or None. None clears the override
                and restores inheritance.
        """
        if mode is not None and mode not in ("paper", "live"):
            raise ValueError(f"mode must be 'paper', 'live', or None, got {mode!r}")
        session = self._sessions.get(session_id)
        if not session:
            raise ValueError(f"Session not found: {session_id}")
        if session.portfolio_id:
            raise ValueError(
                f"Session {session_id} is bound to portfolio "
                f"{session.portfolio_id!r}; change the portfolio mode instead"
            )
        session.execution_mode = mode  # type: ignore[assignment]
        if self._session_db:
            self._session_db.update_execution_mode(session_id, mode)
        logger.info(
            "session_execution_mode_changed",
            session_id=session_id,
            mode=mode,
        )
        return session

    def set_status(self, session_id: str, target_status: str) -> TradingSession:
        """Validate transition and update session status."""
        session = self._sessions.get(session_id)
        if not session:
            raise ValueError(f"Session not found: {session_id}")
        if not SessionDB.validate_transition(session.status, target_status):
            raise ValueError(
                f"Invalid transition: {session.status} → {target_status}"
            )
        session.status = target_status
        if self._session_db:
            self._session_db.update_status(session_id, target_status)
        logger.info("session_status_changed", session_id=session_id, status=target_status)
        return session

    def deploy(
        self,
        session_id: str,
        candidate_id: int,
        params: dict[str, Any],
        source: str = "dashboard",
    ) -> TradingSession:
        """Set deployed candidate and log deployment."""
        session = self._sessions.get(session_id)
        if not session:
            raise ValueError(f"Session not found: {session_id}")
        session.deployed_candidate_id = candidate_id
        if self._session_db:
            self._session_db.update_deployed(session_id, candidate_id)
            self._session_db.log_deployment(
                account_id=session.account_id,
                session_id=session_id,
                strategy=session.strategy_slug,
                symbol=session.symbol,
                candidate_id=candidate_id,
                params=params,
                source=source,
            )
        logger.info("session_deployed", session_id=session_id, candidate_id=candidate_id)
        return session

    def poll_all(self) -> None:
        """Fetch account snapshots and update each session's state."""
        account_snapshots: dict[str, AccountSnapshot] = {}
        for session in self._sessions.values():
            if session.status != "active":
                continue
            if session.account_id not in account_snapshots:
                gw = self._registry.get_gateway(session.account_id)
                if gw:
                    account_snapshots[session.account_id] = gw.get_account_snapshot()
                else:
                    account_snapshots[session.account_id] = AccountSnapshot.disconnected()
            acct_snap = account_snapshots[session.account_id]
            if not acct_snap.connected:
                continue
            positions = [p for p in acct_snap.positions if p.symbol.startswith(session.symbol)]
            unrealized = sum(p.unrealized_pnl for p in positions)
            snap = SessionSnapshot.compute(
                equity=acct_snap.equity,
                peak_equity=session.peak_equity,
                unrealized_pnl=unrealized,
                realized_pnl=acct_snap.realized_pnl_today,
                positions=positions,
                trade_count=len(acct_snap.recent_fills),
            )
            session.current_snapshot = snap
            session.peak_equity = snap.peak_equity
            self._store.write_snapshot(session.session_id, snap)

    def delete_session(self, session_id: str) -> None:
        """Remove a session. Must be stopped first."""
        session = self._sessions.get(session_id)
        if not session:
            raise ValueError(f"Session not found: {session_id}")
        if session.status == "active":
            raise ValueError("Cannot delete an active session — stop it first")
        del self._sessions[session_id]
        if self._session_db:
            self._session_db.delete_session(session_id)
        logger.info("session_deleted", session_id=session_id)

    def get_all_sessions(self) -> list[TradingSession]:
        return list(self._sessions.values())

    def get_sessions_for_account(self, account_id: str) -> list[TradingSession]:
        return [s for s in self._sessions.values() if s.account_id == account_id]

    def get_session(self, session_id: str) -> TradingSession | None:
        return self._sessions.get(session_id)

    def get_equity_curve(self, session_id: str, days: int = 30) -> list[tuple]:
        return self._store.get_equity_curve(session_id, days)

    def halt(self) -> None:
        """Set global halt flag — reject all new orders."""
        self.halt_active = True
        for session in self._sessions.values():
            if session.status == "active":
                session.status = "halted"
                if self._session_db:
                    self._session_db.update_status(session.session_id, "halted")
        logger.warning("global_halt_activated", sessions_halted=len(self._sessions))

    def flatten(self) -> None:
        """Send market-close orders for all positions and halt."""
        self.halt_active = True
        for session in self._sessions.values():
            if session.status in ("active", "halted"):
                gw = self._registry.get_gateway(session.account_id)
                if gw:
                    try:
                        gw.close_all_positions(session.symbol)
                    except Exception:
                        logger.exception("flatten_failed", session_id=session.session_id)
                session.status = "flattening"
                if self._session_db:
                    self._session_db.update_status(session.session_id, "flattening")
        logger.warning("global_flatten_activated")

    def flatten_session(self, session_id: str) -> "TradingSession":
        """Flatten (liquidate) positions for a specific session.

        Sends market close orders for the session's symbol and sets status to 'flattening'.
        Does not affect global halt state or other sessions.
        """
        session = self._sessions.get(session_id)
        if not session:
            raise ValueError(f"Session '{session_id}' not found")

        if session.status in ("active", "paused", "halted"):
            gw = self._registry.get_gateway(session.account_id)
            if gw:
                try:
                    gw.close_all_positions(session.symbol)
                except Exception:
                    logger.exception("flatten_session_failed", session_id=session_id)
            session.status = "flattening"
            if self._session_db:
                self._session_db.update_status(session_id, "flattening")
            logger.warning("session_flatten_activated", session_id=session_id)
        return session

    def resume(self) -> None:
        """Lift the global halt flag and restore halted sessions to active."""
        self.halt_active = False
        for session in self._sessions.values():
            if session.status == "halted":
                session.status = "active"
                if self._session_db:
                    self._session_db.update_status(session.session_id, "active")
            elif session.status == "flattening":
                session.status = "stopped"
                if self._session_db:
                    self._session_db.update_status(session.session_id, "stopped")
        logger.info("global_halt_lifted")
