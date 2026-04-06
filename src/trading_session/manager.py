"""SessionManager — orchestrates all trading sessions."""
from __future__ import annotations

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
    ) -> TradingSession:
        if self._session_db:
            existing = self._session_db.find_session(account_id, strategy_slug, symbol)
            if existing:
                self._sessions[existing.session_id] = existing
                return existing
        session = TradingSession.create(account_id, strategy_slug, symbol, status="stopped")
        self._sessions[session.session_id] = session
        if self._session_db:
            self._session_db.save(session)
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

    def resume(self) -> None:
        """Lift the global halt flag."""
        self.halt_active = False
        for session in self._sessions.values():
            if session.status in ("halted", "flattening"):
                session.status = "stopped"
                if self._session_db:
                    self._session_db.update_status(session.session_id, "stopped")
        logger.info("global_halt_lifted")
