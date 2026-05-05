"""SinopacGateway — trading-side gateway: account state + order placement.

Tick subscription was deliberately removed from this class. The data feed
(行情／資料) is owned by ``src.api.helpers._start_market_data_subscriber``,
which logs in with the data-only API key/secret pair stored in GSM as
``SHIOAJI_API_KEY`` / ``SHIOAJI_API_SECRET`` (resolved via the ``[sinopac]``
group mapping in ``config/secrets.toml``). Those credentials carry *only*
行情／資料 permission. Per-account trading credentials live under
``{ACCOUNT_ID}_API_KEY`` / ``{ACCOUNT_ID}_API_SECRET`` (e.g.
``1839302_API_KEY``) and need only 帳務 + 交易 permissions; they no
longer subscribe ticks. This separation makes a leaked trading key
unable to impersonate the data feed and a leaked data key unable to
place orders.
"""
from __future__ import annotations

import time
import asyncio
import structlog
from typing import Any
from datetime import datetime, timedelta, timezone

_TAIPEI_TZ = timezone(timedelta(hours=8))

from src.broker_gateway.abc import BrokerGateway
from src.broker_gateway.types import AccountSnapshot, Fill, LivePosition, OpenOrder, OrderEvent

logger = structlog.get_logger(__name__)

sj: Any = None


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
        self._sim_equity: float = 100_000.0
        # Background reconnect supervisor — when started, polls
        # ``is_connected`` every ``_reconnect_interval_secs`` and calls
        # ``_maybe_reconnect_disconnected`` proactively, so a silent
        # broker disconnect doesn't wait for the next account snapshot.
        self._reconnect_task: asyncio.Task | None = None
        self._reconnect_stopped: asyncio.Event | None = None

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
        """Login to shioaji with trading-only credentials.

        Credential resolution order:
        1. Explicit ``api_key`` / ``api_secret`` arguments (test / manual override)
        2. Account-specific GSM secrets (``{ACCOUNT_ID}_API_KEY`` / ``{ACCOUNT_ID}_API_SECRET``)

        The legacy group-level ``[sinopac]`` fallback was deliberately
        removed. Those credentials carry **only** market-data permission
        (行情／資料) and live in GSM as ``SINOPAC_API_KEY`` /
        ``SINOPAC_API_SECRET``, owned by the standalone subscriber in
        ``src.api.helpers``. Falling back to them on the trading path
        masks misconfiguration: the gateway would silently log in with
        a key that has no 交易 permission, then every order placement
        would fail at order time instead of at startup. The fail-fast
        behaviour below — refusing to connect when no per-account
        creds are present — surfaces the misconfiguration immediately.
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
        self._ip_blocked = False  # reset on each explicit connect() call
        candidates: list[tuple[str, str, str]] = []
        if api_key and api_secret:
            candidates.append(("explicit", api_key, api_secret))
        if api_key is None or api_secret is None:
            from src.broker_gateway.registry import load_credentials
            if account_id:
                creds = load_credentials(account_id)
                acct_key = creds.get("api_key")
                acct_secret = creds.get("api_secret")
                if acct_key and acct_secret:
                    candidates.append(("account_specific", acct_key, acct_secret))
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
                f"No trading credentials found for account '{account_id}'. "
                f"Set {account_id.upper().replace('-','_')}_API_KEY and "
                f"{account_id.upper().replace('-','_')}_API_SECRET in GSM "
                f"(via Trading → Accounts in the dashboard). The data-only "
                f"SHIOAJI_API_KEY fallback was removed — a key with only "
                f"行情 permission cannot place orders."
            ) if account_id else (
                "No trading credentials supplied and no account_id to look up."
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
                # NOTE: tick subscription is intentionally NOT done here —
                # the market-data feed is owned by the standalone subscriber
                # in ``src.api.helpers`` which uses a separate data-only
                # API key. Trading credentials shouldn't grant data access.
                return
            except Exception as exc:
                last_error = exc
                err_str = str(exc)
                # Detect permanent IP-block errors so we don't waste time
                # retrying in _maybe_reconnect_disconnected. The response
                # dict contains "not allow" when Sinopac rejects the login IP.
                if "not allow" in err_str or "ip" in err_str.lower() and "allow" in err_str.lower():
                    self._ip_blocked = True
                    logger.warning(
                        "sinopac_ip_blocked",
                        account_id=account_id,
                        ip_hint=err_str[:120],
                    )
                    break  # no point trying other creds with same IP
                logger.warning(
                    "sinopac_login_failed",
                    account_id=account_id,
                    credential_source=source,
                    error=err_str,
                )
        self._connect_error = f"Login failed: {last_error}" if last_error else "Login failed"

    def disconnect(self) -> None:
        if self._api:
            try:
                self._api.logout()
            except Exception:
                pass
        self._connected = False

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
        equity = 0.0
        margin_used = 0.0
        available = 0.0
        pnl_today = 0.0
        try:
            margin_data = self._api.margin()
            equity = float(getattr(margin_data, "equity", 0))
            margin_used = float(getattr(margin_data, "margin", 0))
            available = float(getattr(margin_data, "available_margin", 0))
            pnl_today = float(getattr(margin_data, "pnl", 0))
        except Exception:
            # Simulation mode doesn't support margin(); use configured equity
            if getattr(self, "_simulation", False):
                equity = getattr(self, "_sim_equity", 1_000_000.0)
                available = equity
            else:
                raise

        # Sinopac's simulation endpoint sometimes returns a margin payload
        # successfully but with equity=0 (no raise to trigger the fallback
        # above). Treat that as "no real paper balance yet" and seed the
        # display from _sim_equity so the war-room doesn't show $0 for a
        # connected paper account.
        if getattr(self, "_simulation", False) and equity <= 0:
            equity = getattr(self, "_sim_equity", 1_000_000.0)
            if available <= 0:
                available = equity

        positions = self._fetch_positions()
        unrealized = sum(p.unrealized_pnl for p in positions)
        fills = self._fetch_fills()
        open_orders = self._fetch_open_orders()
        continuity_cursor = str(int(time.time() * 1000))

        return AccountSnapshot(
            connected=True,
            timestamp=datetime.now(_TAIPEI_TZ),
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
                timestamp=datetime.now(_TAIPEI_TZ),
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
                    updated_at=datetime.now(_TAIPEI_TZ),
                )
            )
        return result

    def get_equity_history(self, days: int = 30) -> list[tuple[datetime, float]]:
        # shioaji doesn't provide historical equity directly — delegate to snapshot store
        return []

    def place_order(
        self,
        symbol: str,
        side: str,
        quantity: int,
        order_type: str = "market",
        price: float = 0.0,
        daytrade: bool = False,
    ) -> dict[str, Any]:
        """Place an order through the Shioaji API.

        Args:
            symbol: Contract group code (e.g. "TXF", "MXF", "TMF")
            side: "buy" or "sell"
            quantity: Number of lots
            order_type: "market" or "limit"
            price: Limit price (ignored for market orders)
            daytrade: When True, sets ``octype=FuturesOCType.DayTrade`` so
                Sinopac applies 當沖 half-margin BP (account must have 當沖
                pre-enabled). Default False keeps existing ``Auto`` behaviour.

        Returns dict with order_id, status, and contract info.
        """
        _sj = _ensure_shioaji()
        if not self._connected or not self._api:
            raise RuntimeError("Gateway not connected")
        group = getattr(self._api.Contracts.Futures, symbol, None)
        if group is None:
            raise ValueError(f"Unknown futures group: {symbol}")
        candidates = [c for c in group if not getattr(c, "code", "").endswith(("R1", "R2"))]
        if not candidates:
            raise ValueError(f"No contracts found for {symbol}")
        contract = min(candidates, key=lambda c: getattr(c, "delivery_date", "9999"))
        action = _sj.constant.Action.Buy if side == "buy" else _sj.constant.Action.Sell
        octype = (
            _sj.constant.FuturesOCType.DayTrade if daytrade
            else _sj.constant.FuturesOCType.Auto
        )
        if order_type == "market":
            sj_order = self._api.Order(
                action=action,
                price=0,
                quantity=quantity,
                price_type=_sj.constant.FuturesPriceType.MKT,
                order_type=_sj.constant.OrderType.IOC,
                octype=octype,
                account=self._api.futopt_account,
            )
        else:
            sj_order = self._api.Order(
                action=action,
                price=price,
                quantity=quantity,
                price_type=_sj.constant.FuturesPriceType.LMT,
                order_type=_sj.constant.OrderType.ROD,
                octype=octype,
                account=self._api.futopt_account,
            )
        trade = self._api.place_order(contract, sj_order)
        order_id = trade.order.id
        status = str(trade.status.status)
        code = getattr(contract, "code", "?")
        logger.info(
            "sinopac_order_placed",
            order_id=order_id, symbol=symbol, code=code,
            side=side, quantity=quantity, order_type=order_type,
            price=price, status=status, daytrade=daytrade,
        )
        return {
            "order_id": order_id,
            "code": code,
            "symbol": symbol,
            "side": side,
            "quantity": quantity,
            "order_type": order_type,
            "price": price,
            "status": status,
        }

    def place_option_order(
        self,
        contract_code: str,
        side: str,
        quantity: int,
        price: float,
        order_type: str = "limit",
    ) -> dict[str, Any]:
        """Place a TXO option order via Shioaji.

        Args:
            contract_code: Shioaji option contract code (e.g. "TXO22300J4")
            side: "buy" or "sell"
            quantity: Number of lots
            price: Limit price (required for limit orders)
            order_type: "limit" (default) or "market"
        """
        _sj = _ensure_shioaji()
        if not self._connected or not self._api:
            raise RuntimeError("Gateway not connected")
        txo_group = self._api.Contracts.Options.TXO
        contract = None
        for opt in txo_group:
            if opt.code == contract_code:
                contract = opt
                break
        if contract is None:
            raise ValueError(f"Option contract not found: {contract_code}")
        action = _sj.constant.Action.Buy if side == "buy" else _sj.constant.Action.Sell
        if order_type == "market":
            sj_order = self._api.Order(
                action=action,
                price=0,
                quantity=quantity,
                price_type=_sj.constant.FuturesPriceType.MKT,
                order_type=_sj.constant.OrderType.IOC,
                octype=_sj.constant.FuturesOCType.Auto,
                account=self._api.futopt_account,
            )
        else:
            sj_order = self._api.Order(
                action=action,
                price=price,
                quantity=quantity,
                price_type=_sj.constant.FuturesPriceType.LMT,
                order_type=_sj.constant.OrderType.ROD,
                octype=_sj.constant.FuturesOCType.Auto,
                account=self._api.futopt_account,
            )
        trade = self._api.place_order(contract, sj_order)
        order_id = trade.order.id
        status = str(trade.status.status)
        logger.info(
            "sinopac_option_order_placed",
            order_id=order_id, contract_code=contract_code,
            side=side, quantity=quantity, order_type=order_type,
            price=price, status=status,
        )
        return {
            "order_id": order_id,
            "contract_code": contract_code,
            "strike": float(contract.strike_price),
            "option_type": str(contract.option_right.value),
            "expiry": contract.delivery_date.replace("/", "-"),
            "side": side,
            "quantity": quantity,
            "order_type": order_type,
            "price": price,
            "status": status,
        }

    def poll_fills(self) -> list[dict[str, Any]]:
        """Poll for new fills since the last check. Returns list of new fill dicts."""
        if not self._connected or not self._api:
            return []
        try:
            self._api.update_status(self._api.futopt_account)
        except Exception as exc:
            logger.debug("poll_fills_update_status_failed", error=str(exc))
        try:
            trades = self._api.list_trades()
        except Exception as exc:
            logger.debug("poll_fills_list_trades_failed", error=str(exc))
            return []
        if not hasattr(self, "_seen_deal_ids"):
            self._seen_deal_ids: set[str] = set()
        new_fills: list[dict[str, Any]] = []
        for trade in trades:
            status = getattr(trade, "status", None)
            if not status:
                continue
            deals = getattr(status, "deals", [])
            for deal in deals:
                deal_seq = getattr(deal, "seq", None) or str(id(deal))
                order_id = trade.order.id
                deal_key = f"{order_id}:{deal_seq}"
                if deal_key in self._seen_deal_ids:
                    continue
                self._seen_deal_ids.add(deal_key)
                code = getattr(trade.contract, "code", "") or getattr(trade.order, "code", "")
                action = str(getattr(trade.order, "action", ""))
                fill = {
                    "type": "fill",
                    "order_id": order_id,
                    "code": code,
                    "symbol": self._code_to_db_symbol(code),
                    "side": "buy" if "Buy" in action else "sell",
                    "price": float(getattr(deal, "price", 0)),
                    "quantity": int(getattr(deal, "quantity", 0)),
                    "timestamp": time.time(),
                    "source": "simulation" if getattr(self, "_simulation", False) else "live",
                }
                new_fills.append(fill)
                logger.info(
                    "poll_fills_new_deal",
                    order_id=order_id, code=code,
                    side=fill["side"], price=fill["price"],
                    quantity=fill["quantity"],
                )
        return new_fills

    @staticmethod
    def _code_to_db_symbol(code: str) -> str:
        if code.startswith("TXF"):
            return "TX"
        if code.startswith("MXF"):
            return "MTX"
        if code.startswith("TMF"):
            return "TMF"
        return code

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
                    timestamp=datetime.now(_TAIPEI_TZ),
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

    def start_reconnect_loop(
        self,
        loop: asyncio.AbstractEventLoop | None = None,
        interval_secs: float | None = None,
    ) -> None:
        """Start a background task that proactively reconnects on disconnect.

        The on-demand path in ``_fetch_snapshot`` remains as a defensive
        check, but waiting for the next account snapshot is too slow
        when a long-running session has no other reason to hit the
        broker for minutes at a time. This loop closes the gap.
        """
        if self._reconnect_task is not None and not self._reconnect_task.done():
            return
        target_loop = loop or asyncio.get_event_loop()
        if interval_secs is not None and interval_secs > 0:
            self._reconnect_interval_secs = interval_secs
        self._reconnect_stopped = asyncio.Event()
        self._reconnect_task = target_loop.create_task(self._reconnect_loop_body())
        logger.info(
            "sinopac_reconnect_loop_started",
            interval_secs=self._reconnect_interval_secs,
        )

    def stop_reconnect_loop(self) -> None:
        if self._reconnect_task is None:
            return
        if self._reconnect_stopped is not None:
            self._reconnect_stopped.set()
        if not self._reconnect_task.done():
            self._reconnect_task.cancel()
        self._reconnect_task = None
        self._reconnect_stopped = None
        logger.info("sinopac_reconnect_loop_stopped")

    async def _reconnect_loop_body(self) -> None:
        try:
            while True:
                stopped = self._reconnect_stopped
                if stopped is not None and stopped.is_set():
                    return
                if not self._connected and not getattr(self, "_ip_blocked", False):
                    try:
                        self._maybe_reconnect_disconnected()
                    except Exception:
                        logger.exception("sinopac_background_reconnect_failed")
                # Sleep responsively: wake up if stop is requested.
                if stopped is not None:
                    try:
                        await asyncio.wait_for(
                            stopped.wait(), timeout=self._reconnect_interval_secs,
                        )
                        return
                    except asyncio.TimeoutError:
                        continue
                else:
                    await asyncio.sleep(self._reconnect_interval_secs)
        except asyncio.CancelledError:
            pass

    def _maybe_reconnect_disconnected(self) -> None:
        if self._connected:
            return
        # Skip retry when the last failure was an IP block — retrying won't help
        # until the operator whitelists the new IP on Sinopac's side.
        if getattr(self, "_ip_blocked", False):
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
    _PV = {"TXF": 200.0, "MXF": 50.0, "TMF": 10.0}
    for prefix, pv in _PV.items():
        if code.startswith(prefix):
            return pv
    return 1.0
