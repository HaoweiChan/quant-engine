"""Position reconciler: periodic comparison of engine vs broker state."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import structlog

from src.alerting.dispatcher import NotificationDispatcher

logger = structlog.get_logger(__name__)


@dataclass
class Mismatch:
    kind: str  # "quantity", "ghost", "orphan", "equity", "margin", "disaster_stop"
    symbol: str
    engine_value: float
    broker_value: float
    details: str = ""


@dataclass
class ReconciliationConfig:
    interval_seconds: float = 60.0
    equity_threshold_pct: float = 0.02
    policy: str = "alert_only"  # "alert_only" or "halt_on_mismatch"


@dataclass
class ResumeAuditRecord:
    operator_id: str
    confirmed_at: datetime
    snapshot_id: str


class PositionReconciler:
    """Compare engine positions against broker positions on a timer."""

    def __init__(
        self,
        api: Any,
        get_engine_positions: Any,
        get_engine_equity: Any,
        config: ReconciliationConfig | None = None,
        dispatcher: NotificationDispatcher | None = None,
        on_halt: Any | None = None,
        on_disaster_stop_fill: Any | None = None,
    ) -> None:
        self._api = api
        self._get_positions = get_engine_positions
        self._get_equity = get_engine_equity
        self._config = config or ReconciliationConfig()
        self._dispatcher = dispatcher
        self._on_halt = on_halt
        self._on_disaster_stop_fill = on_disaster_stop_fill
        self._task: asyncio.Task[None] | None = None
        self._mismatches = []
        self._disaster_order_ids: set[str] = set()
        self._startup_frozen = True
        self._startup_safe = False
        self._startup_snapshot_id = ""
        self._resume_audit: list[ResumeAuditRecord] = []
        self._startup_unsafe_reasons: list[str] = []

    async def start_loop(self, interval: float | None = None) -> None:
        """Run reconciliation on a timer until cancelled."""
        wait = interval or self._config.interval_seconds
        try:
            while True:
                await self._reconcile()
                await asyncio.sleep(wait)
        except asyncio.CancelledError:
            logger.info("reconciler_stopped")

    def start(self, interval: float | None = None) -> asyncio.Task[None]:
        self._task = asyncio.create_task(self.start_loop(interval))
        return self._task

    def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            self._task = None

    @property
    def mismatches(self) -> list[Mismatch]:
        return list(self._mismatches)

    @property
    def startup_frozen(self) -> bool:
        return self._startup_frozen

    @property
    def startup_safe(self) -> bool:
        return self._startup_safe

    @property
    def resume_audit(self) -> list[ResumeAuditRecord]:
        return list(self._resume_audit)

    def can_emit_orders(self) -> bool:
        return self._startup_safe and not self._startup_frozen

    def confirm_resume(self, operator_id: str) -> bool:
        if not self._startup_safe or not self._startup_snapshot_id:
            return False
        self._startup_frozen = False
        self._resume_audit.append(
            ResumeAuditRecord(
                operator_id=operator_id,
                confirmed_at=datetime.now(),
                snapshot_id=self._startup_snapshot_id,
            )
        )
        logger.info(
            "reconciler_resume_confirmed",
            operator_id=operator_id,
            snapshot_id=self._startup_snapshot_id,
        )
        return True

    async def run_startup_reconciliation(self) -> bool:
        self._startup_frozen = True
        self._startup_safe = False
        self._startup_unsafe_reasons = []
        self._startup_snapshot_id = datetime.now().isoformat()

        _, _, _, open_orders, continuity_ok = self._fetch_broker_state()
        if not continuity_ok:
            self._startup_unsafe_reasons.append("continuity_unavailable")
        if open_orders:
            cancelled = self._cancel_open_orders(open_orders)
            logger.info("startup_open_orders_cancelled", count=cancelled)

        mismatches = await self._reconcile()
        has_critical = any(item.kind in ("ghost", "orphan", "quantity") for item in mismatches)
        if has_critical:
            self._startup_unsafe_reasons.append("critical_mismatch")

        self._startup_safe = continuity_ok and not has_critical
        logger.info(
            "startup_reconciliation_completed",
            startup_safe=self._startup_safe,
            mismatch_count=len(mismatches),
            reasons=self._startup_unsafe_reasons,
            snapshot_id=self._startup_snapshot_id,
        )
        return self._startup_safe

    def register_disaster_order(self, order_id: str) -> None:
        """Register a disaster stop order ID for tracking."""
        self._disaster_order_ids.add(order_id)

    def deregister_disaster_order(self, order_id: str) -> None:
        """Deregister a disaster stop order ID when it's no longer active."""
        self._disaster_order_ids.discard(order_id)

    async def _reconcile(self) -> list[Mismatch]:
        broker_positions, broker_margin, broker_fills, _, _ = self._fetch_broker_state()
        if broker_margin is None:
            logger.exception("reconciler_broker_fetch_failed")
            return []

        engine_positions = self._get_positions()
        found: list[Mismatch] = []

        broker_map = self._build_broker_map(broker_positions)
        engine_map = {(p.symbol, p.direction): p.lots for p in engine_positions}

        for key, engine_qty in engine_map.items():
            broker_qty = broker_map.pop(key, 0.0)
            if abs(engine_qty - broker_qty) > 0.001:
                kind = "ghost" if broker_qty == 0.0 else "quantity"
                found.append(
                    Mismatch(
                        kind=kind,
                        symbol=f"{key[0]}:{key[1]}",
                        engine_value=engine_qty,
                        broker_value=broker_qty,
                    )
                )

        for key, broker_qty in list(broker_map.items()):
            symbol, direction = key
            disaster_fill = self._check_disaster_fill(symbol, broker_fills)
            if disaster_fill:
                found.append(
                    Mismatch(
                        kind="disaster_stop",
                        symbol=f"{symbol}:{direction}",
                        engine_value=0.0,
                        broker_value=broker_qty,
                        details=f"fill_price={disaster_fill['price']}",
                    )
                )
                if self._on_disaster_stop_fill:
                    try:
                        await self._on_disaster_stop_fill(
                            symbol=symbol,
                            direction=direction,
                            fill_price=disaster_fill["price"],
                            fill_time=disaster_fill.get("time"),
                        )
                    except Exception:
                        logger.exception("disaster_fill_handler_failed")
                self._disaster_order_ids.discard(disaster_fill.get("order_id", ""))
            else:
                found.append(
                    Mismatch(
                        kind="orphan",
                        symbol=f"{symbol}:{direction}",
                        engine_value=0.0,
                        broker_value=broker_qty,
                    )
                )

        found.extend(self._check_account(broker_margin))
        self._mismatches = found

        if found:
            logger.warning(
                "reconciliation_mismatches",
                count=len(found),
                kinds=[m.kind for m in found],
            )
            await self._handle_mismatches(found)
        else:
            logger.debug("reconciliation_ok")
        return found

    def _check_account(self, broker_margin: Any) -> list[Mismatch]:
        result: list[Mismatch] = []
        engine_equity = self._get_equity()
        broker_equity = float(getattr(broker_margin, "equity", 0.0))
        if broker_equity > 0:
            deviation = abs(engine_equity - broker_equity) / broker_equity
            if deviation > self._config.equity_threshold_pct:
                result.append(
                    Mismatch(
                        kind="equity",
                        symbol="account",
                        engine_value=engine_equity,
                        broker_value=broker_equity,
                        details=f"deviation={deviation:.2%}",
                    )
                )
        margin_ratio = float(getattr(broker_margin, "margin_ratio", 0.0))
        if margin_ratio > 0:
            result.append(
                Mismatch(
                    kind="margin",
                    symbol="account",
                    engine_value=0.0,
                    broker_value=margin_ratio,
                    details="broker_margin_ratio",
                )
            ) if margin_ratio < 0.25 else None
        return result

    async def _handle_mismatches(self, mismatches: list[Mismatch]) -> None:
        if self._dispatcher:
            lines = ["<b>RECONCILIATION ALERT</b>"]
            for m in mismatches:
                lines.append(
                    f"  {m.kind}: {m.symbol} engine={m.engine_value} broker={m.broker_value}"
                )
            try:
                await self._dispatcher.dispatch("\n".join(lines))
            except Exception:
                logger.exception("reconciler_alert_failed")

        if self._config.policy == "halt_on_mismatch" and self._on_halt:
            has_critical = any(m.kind in ("ghost", "orphan", "quantity") for m in mismatches)
            if has_critical:
                logger.error("reconciler_halt_triggered")
                self._on_halt()

    @staticmethod
    def _build_broker_map(
        positions: Any,
    ) -> dict[tuple[str, str], float]:
        result: dict[tuple[str, str], float] = {}
        for p in positions:
            symbol = getattr(p, "code", getattr(p, "symbol", "unknown"))
            direction = "long" if getattr(p, "direction", "") == "Buy" else "short"
            qty = abs(float(getattr(p, "quantity", 0)))
            key = (symbol, direction)
            result[key] = result.get(key, 0.0) + qty
        return result

    def _fetch_broker_state(
        self,
    ) -> tuple[list[Any], Any | None, list[Any], list[Any], bool]:
        continuity_ok = True
        try:
            broker_positions = self._api.list_positions(self._api.futopt_account)
            broker_margin = self._api.margin(self._api.futopt_account)
        except Exception:
            return [], None, [], [], False
        try:
            broker_fills = self._api.list_recent_fills(self._api.futopt_account)
        except Exception:
            broker_fills = []
            continuity_ok = False
            logger.exception("reconciler_fill_fetch_failed")
        try:
            open_orders = self._list_open_orders()
        except Exception:
            open_orders = []
            continuity_ok = False
            logger.exception("reconciler_open_order_fetch_failed")
        return broker_positions, broker_margin, broker_fills, open_orders, continuity_ok

    def _list_open_orders(self) -> list[Any]:
        if hasattr(self._api, "list_open_orders"):
            return list(self._api.list_open_orders(self._api.futopt_account))
        if not hasattr(self._api, "list_trades"):
            return []
        open_orders: list[Any] = []
        for trade in self._api.list_trades():
            status = getattr(getattr(trade, "status", None), "status", "")
            if status in ("Filled", "Cancelled"):
                continue
            order = getattr(trade, "order", None)
            if order is not None:
                open_orders.append(order)
        return open_orders

    def _cancel_open_orders(self, open_orders: list[Any]) -> int:
        cancelled = 0
        if not hasattr(self._api, "cancel_order"):
            return 0
        for order in open_orders:
            try:
                self._api.cancel_order(order)
                cancelled += 1
            except Exception:
                logger.exception("startup_open_order_cancel_failed")
        return cancelled

    def _check_disaster_fill(
        self, symbol: str, broker_fills: list[dict[str, Any]]
    ) -> dict[str, Any] | None:
        if not self._disaster_order_ids:
            return None
        for fill in broker_fills:
            fill_symbol = getattr(fill, "symbol", fill.get("symbol", ""))
            fill_order_id = getattr(fill, "order_id", fill.get("order_id", ""))
            if fill_symbol == symbol and fill_order_id in self._disaster_order_ids:
                return {
                    "price": float(getattr(fill, "price", fill.get("price", 0.0))),
                    "quantity": float(getattr(fill, "quantity", fill.get("quantity", 0.0))),
                    "order_id": fill_order_id,
                    "time": getattr(fill, "time", fill.get("time")),
                }
        return None
