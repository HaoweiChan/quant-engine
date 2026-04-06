"""Session lifecycle endpoints — start, stop, pause."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/api/sessions", tags=["sessions"])


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
        }
        for s in sessions
    ]
