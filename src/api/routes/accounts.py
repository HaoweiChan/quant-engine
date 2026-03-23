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
    demo_trading: bool = False
    guards: dict | None = None
    strategies: list[dict] | None = None
    api_key: str | None = None
    api_secret: str | None = None
    password: str | None = None


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
        entry: dict = {
            "id": a.id,
            "broker": a.broker,
            "display_name": a.display_name,
            "guards": a.guards,
            "strategies": a.strategies,
            "credential_status": _check_credentials(a.id),
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
        demo_trading=req.demo_trading,
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


def _check_credentials(account_id: str) -> dict[str, bool]:
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
