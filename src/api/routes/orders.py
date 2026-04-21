"""Manual order placement and fill polling for simulation/live accounts."""
from __future__ import annotations

import asyncio
import time
from typing import Any

import structlog
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/api/orders", tags=["orders"])
logger = structlog.get_logger(__name__)

_fill_poller_task: asyncio.Task | None = None
_FILL_POLL_INTERVAL = 5.0


class PlaceOrderRequest(BaseModel):
    account_id: str
    symbol: str  # futures group: TXF, MXF, TMF
    side: str  # buy or sell
    quantity: int = 1
    order_type: str = "market"  # market or limit
    price: float = 0.0


@router.post("/place")
async def place_order(req: PlaceOrderRequest) -> dict[str, Any]:
    """Place an order through the broker gateway (simulation or live)."""
    from src.api.helpers import get_gateway_registry
    registry = get_gateway_registry()
    if registry is None:
        raise HTTPException(status_code=503, detail="Gateway registry not initialized")
    gateway = registry.get_gateway(req.account_id)
    if gateway is None:
        raise HTTPException(status_code=404, detail=f"Account '{req.account_id}' not found")
    if not gateway.is_connected:
        raise HTTPException(status_code=503, detail=f"Account '{req.account_id}' is disconnected")
    if not hasattr(gateway, "place_order"):
        raise HTTPException(status_code=400, detail="Gateway does not support order placement")
    try:
        result = gateway.place_order(
            symbol=req.symbol,
            side=req.side,
            quantity=req.quantity,
            order_type=req.order_type,
            price=req.price,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None
    # Broadcast the submission event to blotter
    try:
        from src.api.ws.blotter import blotter_broadcaster
        await blotter_broadcaster.broadcast({
            "type": "submission",
            "timestamp": time.time(),
            "account_id": req.account_id,
            "symbol": result.get("symbol", req.symbol),
            "side": req.side,
            "price": req.price,
            "quantity": req.quantity,
            "order_id": result.get("order_id", ""),
            "source": "manual",
            "triggered": False,
        })
    except Exception:
        logger.debug("blotter submission broadcast failed", exc_info=True)
    _ensure_fill_poller(req.account_id)
    return {"status": "ok", "order": result}


@router.get("/fills")
async def get_recent_fills(account_id: str) -> dict[str, Any]:
    """Poll fills from the broker and return any new ones."""
    from src.api.helpers import get_gateway_registry
    registry = get_gateway_registry()
    if registry is None:
        raise HTTPException(status_code=503, detail="Gateway registry not initialized")
    gateway = registry.get_gateway(account_id)
    if gateway is None:
        raise HTTPException(status_code=404, detail=f"Account '{account_id}' not found")
    if not hasattr(gateway, "poll_fills"):
        return {"fills": []}
    fills = gateway.poll_fills()
    return {"fills": fills, "count": len(fills)}


@router.get("/positions")
async def get_positions(account_id: str) -> dict[str, Any]:
    """Get current broker positions (from simulation or live)."""
    from src.api.helpers import get_gateway_registry
    registry = get_gateway_registry()
    if registry is None:
        raise HTTPException(status_code=503, detail="Gateway registry not initialized")
    gateway = registry.get_gateway(account_id)
    if gateway is None:
        raise HTTPException(status_code=404, detail=f"Account '{account_id}' not found")
    snapshot = gateway.get_account_snapshot()
    positions = [
        {
            "symbol": p.symbol,
            "side": p.side,
            "quantity": p.quantity,
            "avg_entry_price": p.avg_entry_price,
            "current_price": p.current_price,
            "unrealized_pnl": p.unrealized_pnl,
        }
        for p in snapshot.positions
    ]
    return {"positions": positions, "count": len(positions)}


def _ensure_fill_poller(account_id: str) -> None:
    """Start the background fill poller if not already running."""
    global _fill_poller_task
    if _fill_poller_task is not None and not _fill_poller_task.done():
        return
    try:
        loop = asyncio.get_running_loop()
        _fill_poller_task = loop.create_task(_fill_poll_loop(account_id))
        logger.info("fill poller started for account=%s", account_id)
    except RuntimeError:
        pass


async def _fill_poll_loop(account_id: str) -> None:
    """Background task: poll for fills and broadcast to blotter."""
    polls_without_fills = 0
    max_idle_polls = 60  # stop after 5 minutes of no fills
    # First poll immediately (no sleep) to catch fills from orders just placed
    first_poll = True
    while polls_without_fills < max_idle_polls:
        if first_poll:
            await asyncio.sleep(2.0)  # short initial delay for simulation to process
            first_poll = False
        else:
            await asyncio.sleep(_FILL_POLL_INTERVAL)
        try:
            from src.api.helpers import get_gateway_registry
            registry = get_gateway_registry()
            if registry is None:
                continue
            gateway = registry.get_gateway(account_id)
            if gateway is None or not hasattr(gateway, "poll_fills"):
                continue
            fills = gateway.poll_fills()
            if not fills:
                polls_without_fills += 1
                continue
            polls_without_fills = 0
            from src.api.ws.blotter import blotter_broadcaster
            for fill in fills:
                fill["account_id"] = account_id
                fill["triggered"] = True
                await blotter_broadcaster.broadcast(fill)
                logger.info(
                    "fill_broadcasted_to_blotter",
                    side=fill.get("side"),
                    quantity=fill.get("quantity"),
                    symbol=fill.get("symbol"),
                    price=fill.get("price"),
                )
        except Exception:
            logger.exception("fill_poll_error")
    logger.info("fill_poller_stopped", account_id=account_id, reason="idle_timeout")
