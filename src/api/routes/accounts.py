"""Account management endpoints."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/api", tags=["accounts"])

_GATEWAY_CLASSES = {
    "sinopac": "src.broker_gateway.sinopac.SinopacGateway",
    "binance": "src.broker_gateway.mock.MockGateway",
    "schwab": "src.broker_gateway.mock.MockGateway",
    "ccxt": "src.broker_gateway.mock.MockGateway",
    "mock": "src.broker_gateway.mock.MockGateway",
}


class AccountCreateRequest(BaseModel):
    id: str | None = None
    broker: str
    display_name: str | None = None
    sandbox_mode: bool = False
    guards: dict | None = None
    strategies: list[dict] | None = None
    api_key: str | None = None
    api_secret: str | None = None
    password: str | None = None


class UpdateStrategiesRequest(BaseModel):
    strategies: list[dict]


def _get_db():
    from src.broker_gateway.account_db import AccountDB
    return AccountDB()


@router.get("/accounts")
async def list_accounts() -> list[dict]:
    try:
        accounts = _get_db().load_all_accounts()
    except Exception:
        return []
    result = []
    for a in accounts:
        try:
            cred_status = _check_credentials(a.id)
        except Exception:
            cred_status = {}
        entry: dict = {
            "id": a.id,
            "broker": a.broker,
            "display_name": a.display_name,
            "sandbox_mode": a.sandbox_mode,
            "default_mode": "paper" if a.sandbox_mode else "live",
            "guards": a.guards,
            "strategies": a.strategies,
            "credential_status": cred_status,
        }
        result.append(entry)
    return result


@router.get("/accounts/{account_id}")
async def get_account(account_id: str) -> dict:
    acct = _get_db().load_account(account_id)
    if not acct:
        raise HTTPException(status_code=404, detail=f"Account '{account_id}' not found")
    cred_status = _check_credentials(account_id)
    return {
        "id": acct.id,
        "broker": acct.broker,
        "display_name": acct.display_name,
        "sandbox_mode": acct.sandbox_mode,
        "default_mode": "paper" if acct.sandbox_mode else "live",
        "guards": acct.guards,
        "strategies": acct.strategies,
        "credential_status": cred_status,
    }


@router.post("/accounts", status_code=201)
async def create_account(req: AccountCreateRequest) -> dict:
    from src.broker_gateway.types import AccountConfig
    account_id = req.id or f"{req.broker}-main"
    config = AccountConfig(
        id=account_id,
        broker=req.broker,
        display_name=req.display_name or f"{req.broker.title()} ({account_id})",
        gateway_class=_GATEWAY_CLASSES.get(req.broker, _GATEWAY_CLASSES["mock"]),
        sandbox_mode=req.sandbox_mode,
        guards=req.guards or {
            "max_drawdown_pct": 15,
            "max_margin_pct": 80,
            "max_daily_loss": 100_000,
        },
        strategies=req.strategies or [],
    )
    try:
        _get_db().save_account(config)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"DB error: {exc}")
    # Save credentials (best-effort)
    creds = {}
    if req.api_key:
        creds["api_key"] = req.api_key
    if req.api_secret:
        creds["api_secret"] = req.api_secret
    if req.password:
        creds["password"] = req.password
    cred_msg = ""
    if creds:
        try:
            from src.broker_gateway.registry import save_credentials
            save_credentials(account_id, creds)
        except Exception as exc:
            cred_msg = f"Credentials save failed: {exc}"
    return {
        "id": account_id,
        "broker": req.broker,
        "display_name": config.display_name,
        "credential_warning": cred_msg or None,
    }


@router.patch("/accounts/{account_id}/strategies")
async def update_strategies(account_id: str, req: UpdateStrategiesRequest) -> dict:
    db = _get_db()
    config = db.load_account(account_id)
    if not config:
        raise HTTPException(status_code=404, detail=f"Account '{account_id}' not found")
    config.strategies = req.strategies
    db.save_account(config)
    # Invalidate war room cache so the next poll returns fresh session data
    try:
        from src.api.routes.war_room import invalidate_warroom_cache
        invalidate_warroom_cache()
    except Exception:
        pass
    try:
        from src.api.helpers import get_session_manager
        mgr = get_session_manager()
        # Create sessions for new bindings
        for entry in req.strategies:
            slug = entry.get("slug", "")
            symbol = entry.get("symbol", "")
            if slug and symbol:
                mgr.create_session(account_id, slug, symbol)
        # Delete orphaned sessions: any session not in the new strategies list
        # (This handles sessions that exist but weren't in the old stored strategies)
        new_keys = {(e.get("slug", ""), e.get("symbol", "")) for e in req.strategies}
        for session in mgr.get_sessions_for_account(account_id):
            if (session.strategy_slug, session.symbol) not in new_keys:
                if session.status != "stopped":
                    mgr.set_status(session.session_id, "stopped")
                mgr.delete_session(session.session_id)
    except Exception:
        pass
    return {"id": account_id, "strategies": req.strategies}


def _check_credentials(account_id: str) -> dict[str, bool]:
    import os
    # Skip GSM lookups when no GCP credentials are configured to avoid
    # blocking the endpoint with a hanging gRPC channel initialization.
    if not os.environ.get("GOOGLE_APPLICATION_CREDENTIALS") and not os.environ.get("GOOGLE_CLOUD_PROJECT"):
        return {"api_key": False, "api_secret": False, "password": False}
    from src.broker_gateway.registry import _gsm_key
    from src.secrets.manager import get_secret_manager
    fields = {"api_key": "API_KEY", "api_secret": "API_SECRET", "password": "PASSWORD"}
    result: dict[str, bool] = {}
    try:
        sm = get_secret_manager()
        for logical, gsm_field in fields.items():
            try:
                result[logical] = sm.exists(_gsm_key(account_id, gsm_field))
            except Exception:
                result[logical] = False
    except Exception:
        for lk in fields:
            result[lk] = False
    return result
