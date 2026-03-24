"""Deploy strategy params to live trading sessions."""
from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/api/deploy", tags=["deploy"])


class DeployRequest(BaseModel):
    strategy_slug: str
    symbol: str
    candidate_id: int


def _get_managers():
    from src.api.helpers import get_gateway_registry, get_session_manager
    from src.trading_session.session_db import SessionDB
    registry = get_gateway_registry()
    session_mgr = get_session_manager()
    return registry, session_mgr


def _resolve_candidate(candidate_id: int) -> dict[str, Any]:
    from src.strategies.param_registry import ParamRegistry
    reg = ParamRegistry()
    row = reg._conn.execute(
        "SELECT id, strategy, params FROM param_candidates WHERE id = ?",
        (candidate_id,),
    ).fetchone()
    reg.close()
    if not row:
        raise HTTPException(status_code=404, detail="Candidate not found")
    return {"id": row["id"], "strategy": row["strategy"], "params": json.loads(row["params"])}


@router.post("/{account_id}")
async def deploy_to_account(account_id: str, body: DeployRequest) -> dict:
    gw_registry, session_mgr = _get_managers()
    configs = gw_registry.get_all_configs()
    if not any(c.id == account_id for c in configs):
        raise HTTPException(status_code=404, detail="Account not found")
    candidate = _resolve_candidate(body.candidate_id)
    session = session_mgr.create_session(account_id, body.strategy_slug, body.symbol)
    session_mgr.deploy(
        session.session_id,
        body.candidate_id,
        candidate["params"],
        source="dashboard",
    )
    return {
        "session_id": session.session_id,
        "deployed_candidate_id": body.candidate_id,
        "params": candidate["params"],
        "status": session.status,
    }


@router.get("/history/{account_id}")
async def deploy_history_for_account(account_id: str, limit: int = 20) -> list[dict]:
    from src.trading_session.session_db import SessionDB
    db = SessionDB()
    history = db.get_deploy_history(account_id, limit=limit)
    db.close()
    return history


@router.get("/history")
async def deploy_history_all(limit: int = 20) -> list[dict]:
    from src.trading_session.session_db import SessionDB
    db = SessionDB()
    history = db.get_deploy_history(limit=limit)
    db.close()
    return history
