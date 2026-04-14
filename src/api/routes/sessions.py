"""Session lifecycle endpoints — start, stop, pause, allocate."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/sessions", tags=["sessions"])


class EquityShareUpdate(BaseModel):
    share: float = Field(
        ...,
        gt=0.0,
        le=1.0,
        description=(
            "Fraction of the parent account's equity this session may size "
            "against. Must be in (0, 1]. Total across active sessions on the "
            "same account must not exceed 1.0."
        ),
    )


class BatchAllocation(BaseModel):
    session_id: str
    share: float = Field(..., gt=0.0, le=1.0)


class BatchEquityShareUpdate(BaseModel):
    allocations: list[BatchAllocation] = Field(
        ...,
        description=(
            "List of session allocations. All sessions must belong to the same "
            "account. The sum of shares must not exceed 1.0."
        ),
    )


def _get_session_manager():
    from src.api.helpers import get_session_manager
    return get_session_manager()


@router.post("/{session_id}/start")
async def start_session(session_id: str) -> dict:
    mgr = _get_session_manager()
    try:
        session = mgr.set_status(session_id, "active")
    except ValueError as exc:
        msg = str(exc)
        if "not found" in msg:
            raise HTTPException(status_code=404, detail=msg)
        raise HTTPException(status_code=409, detail=msg)
    return {"session_id": session.session_id, "status": session.status}


@router.post("/{session_id}/stop")
async def stop_session(session_id: str) -> dict:
    mgr = _get_session_manager()
    try:
        session = mgr.set_status(session_id, "stopped")
    except ValueError as exc:
        msg = str(exc)
        if "not found" in msg:
            raise HTTPException(status_code=404, detail=msg)
        raise HTTPException(status_code=409, detail=msg)
    return {"session_id": session.session_id, "status": session.status}


@router.post("/{session_id}/pause")
async def pause_session(session_id: str) -> dict:
    mgr = _get_session_manager()
    try:
        session = mgr.set_status(session_id, "paused")
    except ValueError as exc:
        msg = str(exc)
        if "not found" in msg:
            raise HTTPException(status_code=404, detail=msg)
        raise HTTPException(status_code=409, detail=msg)
    return {"session_id": session.session_id, "status": session.status}


@router.post("/{session_id}/flatten")
async def flatten_session(session_id: str) -> dict:
    """Flatten (liquidate) all positions for a specific session.

    Sends market close orders for the session's symbol and sets status to 'flattening'.
    """
    mgr = _get_session_manager()
    try:
        session = mgr.flatten_session(session_id)
    except ValueError as exc:
        msg = str(exc)
        if "not found" in msg:
            raise HTTPException(status_code=404, detail=msg)
        raise HTTPException(status_code=409, detail=msg)
    return {"session_id": session.session_id, "status": session.status}


@router.delete("/{session_id}")
async def delete_session(session_id: str) -> dict:
    mgr = _get_session_manager()
    try:
        mgr.delete_session(session_id)
    except ValueError as exc:
        msg = str(exc)
        if "not found" in msg:
            raise HTTPException(status_code=404, detail=msg)
        raise HTTPException(status_code=409, detail=msg)
    return {"session_id": session_id, "status": "deleted"}


@router.get("")
async def list_sessions() -> list[dict]:
    mgr = _get_session_manager()
    sessions = mgr.get_all_sessions()
    return [
        {
            "session_id": s.session_id,
            "account_id": s.account_id,
            "strategy_slug": s.strategy_slug,
            "symbol": s.symbol,
            "status": s.status,
            "deployed_candidate_id": s.deployed_candidate_id,
            "equity_share": s.equity_share,
        }
        for s in sessions
    ]


@router.patch("/{session_id}/equity-share")
async def update_equity_share(session_id: str, body: EquityShareUpdate) -> dict:
    """Update the margin allocation fraction for a session.

    The SessionManager enforces the per-account invariant that the sum of
    equity_shares across all sessions on that account must not exceed 1.0.
    Overflow attempts are rejected with HTTP 409.
    """
    mgr = _get_session_manager()
    try:
        session = mgr.set_equity_share(session_id, body.share)
    except ValueError as exc:
        msg = str(exc)
        if "not found" in msg:
            raise HTTPException(status_code=404, detail=msg) from None
        if "overflow" in msg.lower():
            raise HTTPException(status_code=409, detail=msg) from None
        raise HTTPException(status_code=400, detail=msg) from None
    return {
        "session_id": session.session_id,
        "account_id": session.account_id,
        "equity_share": session.equity_share,
    }


@router.patch("/batch-equity-share")
async def batch_update_equity_share(body: BatchEquityShareUpdate) -> dict:
    """Atomically update equity shares for multiple sessions.

    Unlike the single-session endpoint, this validates the *final* sum across
    all sessions being updated, allowing reallocation from an invalid state
    (e.g., 3 sessions at 100% each) to a valid one (e.g., 40/30/30).

    All sessions must belong to the same account.
    """
    mgr = _get_session_manager()
    allocations = [(a.session_id, a.share) for a in body.allocations]
    try:
        updated = mgr.set_equity_shares_batch(allocations)
    except ValueError as exc:
        msg = str(exc)
        if "not found" in msg:
            raise HTTPException(status_code=404, detail=msg) from None
        if "overflow" in msg.lower():
            raise HTTPException(status_code=409, detail=msg) from None
        raise HTTPException(status_code=400, detail=msg) from None
    # Invalidate war room cache so the next poll returns fresh session data
    try:
        from src.api.routes.war_room import invalidate_warroom_cache
        invalidate_warroom_cache()
    except Exception:
        pass
    return {
        "updated": [
            {
                "session_id": s.session_id,
                "account_id": s.account_id,
                "equity_share": s.equity_share,
            }
            for s in updated
        ]
    }
