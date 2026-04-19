"""Kill switch endpoints for emergency trading halt / flatten / resume."""
from __future__ import annotations

import structlog
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.api.helpers import get_live_pipeline, get_session_manager, sync_live_pipeline


router = APIRouter(prefix="/api/kill-switch", tags=["kill-switch"])
log = structlog.get_logger(__name__)


class ConfirmBody(BaseModel):
    confirm: str


def _require_confirm(body: ConfirmBody) -> None:
    if body.confirm != "CONFIRM":
        raise HTTPException(status_code=400, detail="Missing confirmation. Send {\"confirm\": \"CONFIRM\"}")


@router.post("/halt")
async def halt_all(body: ConfirmBody) -> dict:
    """Halt all trading sessions — reject new orders."""
    _require_confirm(body)
    mgr = get_session_manager()
    mgr.halt()
    sync_live_pipeline()
    log.warning("kill_switch.halt", action="halt_all")
    return {"status": "halted"}


@router.post("/flatten")
async def flatten_all(body: ConfirmBody) -> dict:
    """Flatten all positions by issuing market-close orders for every
    open position across every active runner in the live pipeline.

    Order emission is routed through each runner's executor (paper or
    live) so paper sessions get simulated fills and live sessions hit
    the broker. Previously the SessionManager tried to call a
    non-existent ``gw.close_all_positions(symbol)`` method on the
    broker gateway, which raised AttributeError silently — leaving
    every position open while the dashboard happily reported
    'flattening'.
    """
    _require_confirm(body)
    mgr = get_session_manager()
    mgr.flatten()  # marks sessions as 'flattening', sets halt flag

    pipeline = None
    try:
        pipeline = get_live_pipeline()
    except Exception:  # noqa: BLE001 — pipeline is optional during tests
        pipeline = None

    orders_issued = 0
    runners_affected: list[str] = []
    if pipeline is not None and hasattr(pipeline, "iter_runners"):
        from src.execution.portfolio_kill_switch import _flatten_orders_for_runner

        for session_id, runner in pipeline.iter_runners():
            orders = _flatten_orders_for_runner(runner)
            if not orders:
                continue
            executor = (
                getattr(runner, "_paper_engine", None)
                or getattr(runner, "_executor", None)
            )
            if executor is None or not hasattr(executor, "execute"):
                continue
            try:
                snapshot = getattr(runner, "_last_snapshot", None)
                if snapshot is not None:
                    await executor.execute(orders, snapshot)
                else:
                    await executor.execute(orders)
                orders_issued += len(orders)
                runners_affected.append(session_id)
            except Exception:
                log.exception(
                    "kill_switch.flatten_failed",
                    session_id=session_id,
                )
    sync_live_pipeline()
    log.warning(
        "kill_switch.flatten",
        action="flatten_all",
        orders=orders_issued,
        runners=runners_affected,
    )
    return {
        "status": "flattening",
        "orders_issued": orders_issued,
        "runners_affected": runners_affected,
    }


@router.post("/resume")
async def resume_all(body: ConfirmBody) -> dict:
    """Lift halt flag and resume normal trading."""
    _require_confirm(body)
    mgr = get_session_manager()
    mgr.resume()
    sync_live_pipeline()
    log.info("kill_switch.resume", action="resume_all")
    return {"status": "resumed"}
