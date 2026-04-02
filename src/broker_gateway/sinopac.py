"""SinopacGateway — live account state + market data from shioaji (TAIFEX futures)."""
from __future__ import annotations

import time
import asyncio
import structlog
import threading
from typing import Any
from zoneinfo import ZoneInfo
from datetime import datetime, timezone

from src.broker_gateway.abc import BrokerGateway
from src.broker_gateway.live_bar_store import LiveMinuteBarStore
from src.broker_gateway.types import AccountSnapshot, Fill, LivePosition, OpenOrder, OrderEvent

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
        self._account_id: str | None = None
        self._connected = False
        self._connect_error: str | None = None
        self._last_connect_attempt_ts = 0.0
        self._reconnect_interval_secs = 20.0
        self._tick_loop: asyncio.AbstractEventLoop | None = None
        self._live_bar_store = LiveMinuteBarStore()

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
        simulation: bool = False,
    ) -> None:
        """Login to shioaji.

        Credential resolution order:
        1. Explicit api_key / api_secret arguments
        2. Account-ID-based GSM secrets  (ACCOUNT_ID_API_KEY, ACCOUNT_ID_API_SECRET)
        3. Legacy group-based GSM lookup via secrets.toml [sinopac] section
        """
        self._account_id = account_id or self._account_id
        self._simulation = simulation
        self._last_connect_attempt_ts = time.monotonic()
        try:
            _sj = _ensure_shioaji()
        except ImportError as exc:
            self._connect_error = str(exc)
            logger.warning("sinopac_shioaji_missing", error=str(exc))
            return
        self._connected = False
        self._connect_error = None
        candidates: list[tuple[str, str, str]] = []
        if api_key and api_secret:
            candidates.append(("explicit", api_key, api_secret))
        if api_key is None or api_secret is None:
            from src.broker_gateway.registry import load_credentials
            from src.secrets.manager import get_secret_manager
            sm = get_secret_manager()
            if account_id:
                creds = load_credentials(account_id)
                acct_key = creds.get("api_key")
                acct_secret = creds.get("api_secret")
                if acct_key and acct_secret:
                    candidates.append(("account_specific", acct_key, acct_secret))
            try:
                group = sm.get_group("sinopac")
                group_key = group.get("api_key")
                group_secret = group.get("secret_key")
                if group_key and group_secret:
                    candidates.append(("group_fallback", group_key, group_secret))
            except Exception:
                pass
        unique_candidates: list[tuple[str, str, str]] = []
        seen_pairs: set[tuple[str, str]] = set()
        for source, key, secret in candidates:
            pair = (key, secret)
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)
            unique_candidates.append((source, key, secret))
        if not unique_candidates:
            self._connect_error = (
                f"No credentials found for account '{account_id}'. "
                "Enter them in Trading → Accounts."
            )
            logger.warning("sinopac_no_credentials", account_id=account_id)
            return
        last_error: Exception | None = None
        for source, key, secret in unique_candidates:
            try:
                self._api = _sj.Shioaji(simulation=simulation)
                self._api.login(api_key=key, secret_key=secret)
                self._connected = True
                self._connect_error = None
                logger.info(
                    "sinopac_gateway_connected",
                    account_id=account_id,
                    credential_source=source,
                    simulation=simulation,
                )
                self._subscribe_market_data()
                return
            except Exception as exc:
                last_error = exc
                logger.warning(
                    "sinopac_login_failed",
                    account_id=account_id,
                    credential_source=source,
                    error=str(exc),
                )
        self._connect_error = f"Login failed: {last_error}" if last_error else "Login failed"

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
            raw_ts = getattr(tick, "datetime", None)
            if isinstance(raw_ts, datetime):
                tick_timestamp = raw_ts if raw_ts.tzinfo else raw_ts.replace(tzinfo=ZoneInfo("Asia/Taipei"))
            else:
                tick_timestamp = datetime.now(timezone.utc).astimezone(ZoneInfo("Asia/Taipei"))
            try:
                self._live_bar_store.ingest_tick(symbol, price, volume, tick_timestamp)
            except Exception as exc:
                logger.debug("sinopac_live_bar_upsert_error", symbol=symbol, error=str(exc))
            try:
                loop = self._tick_loop
                if not loop or loop.is_closed():
                    from src.api.main import get_main_loop
                    loop = get_main_loop()
                    self._tick_loop = loop
                if loop and loop.is_running():
                    asyncio.run_coroutine_threadsafe(push_tick(symbol, price, volume, tick_timestamp), loop)
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
            self._maybe_reconnect_disconnected()
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
        open_orders = self._fetch_open_orders()
        continuity_cursor = str(int(time.time() * 1000))

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
            open_orders=open_orders,
            continuity_cursor=continuity_cursor,
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

    def _fetch_open_orders(self) -> list[OpenOrder]:
        try:
            trades = self._api.list_trades()
        except Exception:
            return []
        result: list[OpenOrder] = []
        for trade in trades:
            order = getattr(trade, "order", None)
            if order is None:
                continue
            status = getattr(trade, "status", None)
            status_value = str(getattr(status, "status", "Submitted"))
            if status_value in {"Filled", "Cancelled"}:
                continue
            quantity = float(getattr(order, "quantity", 0.0))
            deal_quantity = float(getattr(status, "deal_quantity", 0.0)) if status else 0.0
            remaining = max(quantity - deal_quantity, 0.0)
            result.append(
                OpenOrder(
                    order_id=str(getattr(order, "id", "")),
                    symbol=str(getattr(order, "code", "")),
                    side="buy" if getattr(order, "action", "") == "Buy" else "sell",
                    quantity=quantity,
                    remaining_quantity=remaining,
                    limit_price=float(getattr(order, "price", 0.0) or 0.0),
                    status=status_value,
                    updated_at=datetime.now(),
                )
            )
        return result

    def get_equity_history(self, days: int = 30) -> list[tuple[datetime, float]]:
        # shioaji doesn't provide historical equity directly — delegate to snapshot store
        return []

    def get_order_events_since(self, cursor: str | None) -> tuple[list[OrderEvent], str | None]:
        try:
            trades = self._api.list_trades() if self._api else []
        except Exception:
            return [], cursor
        cursor_ts = 0
        if cursor is not None:
            try:
                cursor_ts = int(cursor)
            except ValueError:
                cursor_ts = 0
        events: list[OrderEvent] = []
        next_cursor = cursor_ts
        for trade in trades:
            order = getattr(trade, "order", None)
            if order is None:
                continue
            status = getattr(trade, "status", None)
            status_text = str(getattr(status, "status", "Submitted"))
            event_ts = int(time.time() * 1000)
            if event_ts <= cursor_ts:
                continue
            next_cursor = max(next_cursor, event_ts)
            events.append(
                OrderEvent(
                    broker_event_id=f"{getattr(order, 'id', 'unknown')}:{event_ts}",
                    order_id=str(getattr(order, "id", "")),
                    event_type=status_text.lower(),
                    price=float(getattr(status, "deal_price", 0.0) or 0.0) if status else None,
                    quantity=float(getattr(order, "quantity", 0.0)),
                    timestamp=datetime.now(),
                )
            )
        events.sort(key=lambda item: item.timestamp)
        return events, str(next_cursor) if next_cursor else cursor

    def _should_reconnect(self, exc: Exception) -> bool:
        msg = str(exc).lower()
        return "session" in msg or "expired" in msg or "timeout" in msg

    def _reconnect(self) -> None:
        logger.info("sinopac_attempting_reconnect")
        _sj = _ensure_shioaji()
        self._api = _sj.Shioaji(simulation=getattr(self, "_simulation", False))
        self.connect(account_id=self._account_id, simulation=getattr(self, "_simulation", False))
        logger.info("sinopac_reconnected")

    def _maybe_reconnect_disconnected(self) -> None:
        if self._connected:
            return
        now = time.monotonic()
        if now - self._last_connect_attempt_ts < self._reconnect_interval_secs:
            return
        logger.info("sinopac_disconnected_retry", account_id=self._account_id)
        try:
            self.connect(account_id=self._account_id)
        except Exception as exc:
            self._connect_error = f"Reconnect failed: {exc}"
            logger.warning("sinopac_reconnect_failed", account_id=self._account_id, error=str(exc))


def _point_value_for(code: str) -> float:
    """Quick point value lookup. Full logic in TaifexAdapter.get_point_value()."""
    _PV = {"TXF": 200.0, "MXF": 50.0, "TEF": 4000.0, "TFF": 1000.0, "XIF": 100.0}
    for prefix, pv in _PV.items():
        if code.startswith(prefix):
            return pv
    return 1.0
