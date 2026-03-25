"""SinopacGateway — live account state + market data from shioaji (TAIFEX futures)."""
from __future__ import annotations

import asyncio
import threading
from datetime import datetime
from typing import Any

import structlog

from src.broker_gateway.abc import BrokerGateway
from src.broker_gateway.types import AccountSnapshot, Fill, LivePosition

logger = structlog.get_logger(__name__)

sj: Any = None
_SUBSCRIBED_CONTRACTS: list[str] = []


def _ensure_shioaji() -> Any:
    """Lazy-import shioaji so the gateway class can register without it installed."""
    global sj
    if sj is None:
        try:
            import shioaji as _sj
            sj = _sj
        except ImportError as exc:
            raise ImportError(
                "shioaji is required for SinopacGateway. "
                "Install with: uv sync --extra taifex"
            ) from exc
    return sj


def _get_or_create_loop() -> asyncio.AbstractEventLoop:
    """Get the running asyncio event loop or create one for bridging."""
    try:
        return asyncio.get_running_loop()
    except RuntimeError:
        pass
    try:
        loop = asyncio.get_event_loop()
        if not loop.is_closed():
            return loop
    except RuntimeError:
        pass
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    return loop


class SinopacGateway(BrokerGateway):
    """Read-only account state + live market data from Sinopac via shioaji."""

    def __init__(self, cache_ttl: float = 10.0) -> None:
        super().__init__(cache_ttl=cache_ttl)
        self._api: Any = None
        self._connected = False
        self._connect_error: str | None = None
        self._tick_loop: asyncio.AbstractEventLoop | None = None

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
        try:
            _sj = _ensure_shioaji()
        except ImportError as exc:
            self._connect_error = str(exc)
            logger.warning("sinopac_shioaji_missing", error=str(exc))
            return
        if api_key is None or api_secret is None:
            from src.broker_gateway.registry import load_credentials
            from src.secrets.manager import get_secret_manager
            sm = get_secret_manager()
            if account_id:
                creds = load_credentials(account_id)
                api_key = creds.get("api_key") or api_key
                api_secret = creds.get("api_secret") or api_secret
            if not api_key or not api_secret:
                try:
                    group = sm.get_group("sinopac")
                    api_key = api_key or group.get("api_key")
                    api_secret = api_secret or group.get("secret_key")
                except Exception:
                    pass
        if not api_key or not api_secret:
            self._connect_error = (
                f"No credentials found for account '{account_id}'. "
                "Enter them in Trading → Accounts."
            )
            logger.warning("sinopac_no_credentials", account_id=account_id)
            return
        try:
            self._api = _sj.Shioaji()
            self._api.login(api_key=api_key, secret_key=api_secret)
            self._connected = True
            self._connect_error = None
            logger.info("sinopac_gateway_connected", account_id=account_id)
            self._subscribe_market_data()
        except Exception as exc:
            self._connect_error = f"Login failed: {exc}"
            logger.warning("sinopac_login_failed", account_id=account_id, error=str(exc))

    def _subscribe_market_data(self) -> None:
        """Subscribe to near-month TX tick data and bridge to WebSocket broadcaster."""
        import time
        global _SUBSCRIBED_CONTRACTS
        if not self._api:
            return
        try:
            from src.api.ws.live_feed import push_tick
        except ImportError:
            logger.warning("sinopac_push_tick_unavailable")
            return
        try:
            from src.api.main import get_main_loop
            loop = get_main_loop()
            if loop and not loop.is_closed():
                self._tick_loop = loop
                logger.info("sinopac_main_loop_captured")
            else:
                logger.warning("sinopac_no_event_loop")
        except Exception:
            pass
        # Register tick callback BEFORE subscribing
        def _on_tick(exchange: Any, tick: Any) -> None:
            code = getattr(tick, "code", "")
            price = float(getattr(tick, "close", 0))
            volume = int(getattr(tick, "volume", 0))
            if price <= 0:
                return
            symbol = "TX" if code.startswith("TXF") else "MTX" if code.startswith("MXF") else code
            try:
                loop = self._tick_loop
                if not loop or loop.is_closed():
                    from src.api.main import get_main_loop
                    loop = get_main_loop()
                    self._tick_loop = loop
                if loop and loop.is_running():
                    asyncio.run_coroutine_threadsafe(push_tick(symbol, price, volume), loop)
            except Exception as exc:
                logger.debug("sinopac_tick_push_error", error=str(exc))
        try:
            self._api.quote.set_on_tick_fop_v1_callback(_on_tick)
            logger.info("sinopac_tick_callback_registered")
        except Exception as exc:
            logger.warning("sinopac_tick_callback_failed", error=str(exc))
        # Register event handler to capture subscribe confirmations
        @self._api.on_event
        def _on_event(resp_code: int, event_code: int, info: str, event: str) -> None:
            logger.info("sinopac_event", resp_code=resp_code, event_code=event_code, info=info, msg=event)
        # Wait for contracts to be fully loaded
        time.sleep(2)
        futures_groups = [
            ("TX", "TXF"),
            ("MTX", "MXF"),
        ]
        for symbol, group_name in futures_groups:
            if symbol in _SUBSCRIBED_CONTRACTS:
                continue
            try:
                group = getattr(self._api.Contracts.Futures, group_name)
                candidates = [c for c in group if getattr(c, "code", "")[-2:] not in ("R1", "R2")]
                if not candidates:
                    logger.warning("sinopac_no_contracts_found", symbol=symbol)
                    continue
                contract = min(candidates, key=lambda c: getattr(c, "delivery_date", "9999"))
                code = getattr(contract, "code", "?")
                self._api.quote.subscribe(
                    contract,
                    quote_type=sj.constant.QuoteType.Tick,
                    version=sj.constant.QuoteVersion.v1,
                )
                _SUBSCRIBED_CONTRACTS.append(symbol)
                logger.info("sinopac_tick_subscribed", symbol=symbol, code=code)
            except Exception as exc:
                logger.warning("sinopac_tick_subscribe_failed", symbol=symbol, error=str(exc))

    def disconnect(self) -> None:
        global _SUBSCRIBED_CONTRACTS
        if self._api:
            try:
                self._api.logout()
            except Exception:
                pass
        self._connected = False
        _SUBSCRIBED_CONTRACTS.clear()

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
        _sj = _ensure_shioaji()
        self._api = _sj.Shioaji()
        self.connect()
        logger.info("sinopac_reconnected")


def _point_value_for(code: str) -> float:
    """Quick point value lookup. Full logic in TaifexAdapter.get_point_value()."""
    _PV = {"TXF": 200.0, "MXF": 50.0, "TEF": 4000.0, "TFF": 1000.0, "XIF": 100.0}
    for prefix, pv in _PV.items():
        if code.startswith(prefix):
            return pv
    return 1.0
