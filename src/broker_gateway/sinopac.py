"""SinopacGateway — live account state from shioaji (TAIFEX futures)."""
from __future__ import annotations

from datetime import datetime
from typing import Any

import structlog

from src.broker_gateway.abc import BrokerGateway
from src.broker_gateway.types import AccountSnapshot, Fill, LivePosition

logger = structlog.get_logger(__name__)

try:
    import shioaji as sj
except ImportError as _exc:
    raise ImportError(
        "shioaji is required for SinopacGateway. Install with: uv sync --extra taifex"
    ) from _exc


class SinopacGateway(BrokerGateway):
    """Read-only account state from Sinopac via shioaji."""

    def __init__(self, cache_ttl: float = 10.0) -> None:
        super().__init__(cache_ttl=cache_ttl)
        self._api: Any = None
        self._connected = False

    @property
    def broker_name(self) -> str:
        return "Sinopac"

    @property
    def is_connected(self) -> bool:
        return self._connected

    def connect(  # type: ignore[override]
        self,
        account_id: str | None = None,
        api_key: str | None = None,
        api_secret: str | None = None,
    ) -> None:
        """Login to shioaji.

        Credential resolution order:
        1. Explicit api_key / api_secret arguments
        2. Account-ID-based GSM secrets  (ACCOUNT_ID_API_KEY, ACCOUNT_ID_API_SECRET)
        3. Legacy group-based GSM lookup via secrets.toml [sinopac] section
        """
        if api_key is None or api_secret is None:
            from src.broker_gateway.registry import load_credentials
            from src.secrets.manager import get_secret_manager
            sm = get_secret_manager()
            if account_id:
                # Primary path: per-account GSM secrets saved by the dashboard
                creds = load_credentials(account_id)
                api_key = creds.get("api_key") or api_key
                api_secret = creds.get("api_secret") or api_secret
            if not api_key or not api_secret:
                # Fallback: legacy group-based lookup (SHIOAJI_API_KEY etc.)
                try:
                    group = sm.get_group("sinopac")
                    api_key = api_key or group.get("api_key")
                    api_secret = api_secret or group.get("secret_key")
                except Exception:
                    pass
        if not api_key or not api_secret:
            raise ValueError(
                f"No credentials found for Sinopac account '{account_id}'. "
                "Enter them in Trading → Accounts."
            )
        self._api = sj.Shioaji()
        self._api.login(api_key=api_key, secret_key=api_secret)
        self._connected = True
        logger.info("sinopac_gateway_connected", account_id=account_id)

    def disconnect(self) -> None:
        if self._api:
            try:
                self._api.logout()
            except Exception:
                pass
        self._connected = False

    def _fetch_snapshot(self) -> AccountSnapshot:
        if not self._connected or not self._api:
            return AccountSnapshot.disconnected()
        try:
            return self._build_snapshot()
        except Exception as exc:
            logger.warning("sinopac_snapshot_failed", error=str(exc))
            if self._should_reconnect(exc):
                try:
                    self._reconnect()
                    return self._build_snapshot()
                except Exception:
                    pass
            return AccountSnapshot.disconnected()

    def _build_snapshot(self) -> AccountSnapshot:
        margin_data = self._api.margin()
        equity = float(getattr(margin_data, "equity", 0))
        margin_used = float(getattr(margin_data, "margin", 0))
        available = float(getattr(margin_data, "available_margin", 0))
        pnl_today = float(getattr(margin_data, "pnl", 0))

        positions = self._fetch_positions()
        unrealized = sum(p.unrealized_pnl for p in positions)
        fills = self._fetch_fills()

        return AccountSnapshot(
            connected=True,
            timestamp=datetime.now(),
            equity=equity,
            cash=equity - margin_used,
            unrealized_pnl=unrealized,
            realized_pnl_today=pnl_today,
            margin_used=margin_used,
            margin_available=available,
            positions=positions,
            recent_fills=fills,
        )

    def _fetch_positions(self) -> list[LivePosition]:
        try:
            raw_positions = self._api.list_positions(self._api.futopt_account)
        except Exception:
            return []
        result: list[LivePosition] = []
        for pos in raw_positions:
            code = getattr(pos, "code", "")
            direction = getattr(pos, "direction", "")
            qty = float(getattr(pos, "quantity", 0))
            entry = float(getattr(pos, "price", 0))
            last = float(getattr(pos, "last_price", entry))
            side = "long" if direction == "Buy" else "short"
            pv = _point_value_for(code)
            pnl_sign = 1.0 if side == "long" else -1.0
            unrealized = (last - entry) * qty * pv * pnl_sign
            result.append(LivePosition(
                symbol=code,
                side=side,
                quantity=qty,
                avg_entry_price=entry,
                current_price=last,
                unrealized_pnl=unrealized,
                margin_required=0.0,
            ))
        return result

    def _fetch_fills(self) -> list[Fill]:
        try:
            trades = self._api.list_trades()
        except Exception:
            return []
        result: list[Fill] = []
        for trade in trades:
            status = getattr(trade, "status", None)
            if status and getattr(status, "status", "") != "Filled":
                continue
            order = getattr(trade, "order", None)
            if not order:
                continue
            result.append(Fill(
                timestamp=datetime.now(),
                symbol=getattr(order, "code", ""),
                side="buy" if getattr(order, "action", "") == "Buy" else "sell",
                price=float(getattr(status, "deal_price", 0) if status else 0),
                quantity=float(getattr(order, "quantity", 0)),
                order_id=getattr(order, "id", ""),
                fee=0.0,
            ))
        return result

    def get_equity_history(self, days: int = 30) -> list[tuple[datetime, float]]:
        # shioaji doesn't provide historical equity directly — delegate to snapshot store
        return []

    def _should_reconnect(self, exc: Exception) -> bool:
        msg = str(exc).lower()
        return "session" in msg or "expired" in msg or "timeout" in msg

    def _reconnect(self) -> None:
        logger.info("sinopac_attempting_reconnect")
        self._api = sj.Shioaji()
        # Re-use the same connect logic (account_id unknown at this point, falls back to group)
        self.connect()
        logger.info("sinopac_reconnected")


def _point_value_for(code: str) -> float:
    """Quick point value lookup. Full logic in TaifexAdapter.get_point_value()."""
    _PV = {"TXF": 200.0, "MXF": 50.0, "TEF": 4000.0, "TFF": 1000.0, "XIF": 100.0}
    for prefix, pv in _PV.items():
        if code.startswith(prefix):
            return pv
    return 1.0
