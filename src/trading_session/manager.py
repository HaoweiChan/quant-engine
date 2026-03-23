"""SessionManager — orchestrates all trading sessions."""
from __future__ import annotations

import structlog

from src.broker_gateway.registry import GatewayRegistry
from src.broker_gateway.types import AccountSnapshot
from src.trading_session.session import SessionSnapshot, TradingSession
from src.trading_session.store import SnapshotStore

logger = structlog.get_logger(__name__)


class SessionManager:
    """Manages lifecycle of all TradingSession instances."""

    def __init__(
        self,
        registry: GatewayRegistry,
        store: SnapshotStore | None = None,
    ) -> None:
        self._registry = registry
        self._store = store or SnapshotStore()
        self._sessions: dict[str, TradingSession] = {}

    def restore_from_config(self) -> None:
        """Create sessions for each account+strategy pair from the account configs."""
        for config in self._registry.get_all_configs():
            for strat in config.strategies:
                slug = strat.get("slug", "")
                symbol = strat.get("symbol", "")
                if not slug:
                    continue
                session = TradingSession.create(
                    account_id=config.id,
                    strategy_slug=slug,
                    symbol=symbol,
                )
                self._sessions[session.session_id] = session
                logger.info("session_created", session_id=session.session_id,
                            account=config.id, strategy=slug, symbol=symbol)

    def create_session(
        self,
        account_id: str,
        strategy_slug: str,
        symbol: str,
    ) -> TradingSession:
        session = TradingSession.create(account_id, strategy_slug, symbol)
        self._sessions[session.session_id] = session
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
            # Filter positions for this session's symbol
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

    def get_all_sessions(self) -> list[TradingSession]:
        return list(self._sessions.values())

    def get_sessions_for_account(self, account_id: str) -> list[TradingSession]:
        return [s for s in self._sessions.values() if s.account_id == account_id]

    def get_session(self, session_id: str) -> TradingSession | None:
        return self._sessions.get(session_id)

    def get_equity_curve(self, session_id: str, days: int = 30) -> list[tuple]:
        return self._store.get_equity_curve(session_id, days)
