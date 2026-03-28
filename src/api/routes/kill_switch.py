"""Kill switch endpoints for emergency trading halt / flatten / resume."""
from __future__ import annotations

import structlog
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.api.helpers import get_session_manager


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
    log.warning("kill_switch.halt", action="halt_all")
    return {"status": "halted"}


@router.post("/flatten")
async def flatten_all(body: ConfirmBody) -> dict:
    """Flatten all positions by sending market close orders."""
    _require_confirm(body)
    mgr = get_session_manager()
    mgr.flatten()
    log.warning("kill_switch.flatten", action="flatten_all")
    return {"status": "flattening"}


@router.post("/resume")
async def resume_all(body: ConfirmBody) -> dict:
    """Lift halt flag and resume normal trading."""
    _require_confirm(body)
    mgr = get_session_manager()
    mgr.resume()
    log.info("kill_switch.resume", action="resume_all")
    return {"status": "resumed"}
