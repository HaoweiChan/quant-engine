"""TXO Options IV Screener API routes."""
from __future__ import annotations

import os
import asyncio
import logging
from datetime import date, timedelta

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from src.api.deps import DB_PATH
from src.data.db import Database

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/options", tags=["options"])


class OptionOrderRequest(BaseModel):
    account_id: str
    contract_code: str
    side: str  # "buy" or "sell"
    quantity: int = 1
    price: float
    order_type: str = "limit"


def _get_db() -> Database:
    return Database(f"sqlite:///{DB_PATH}")


@router.get("/screener")
async def options_screener() -> dict:
    """Full IV screener snapshot for all near-term expiries."""
    from src.analytics.options.screener import build_screener
    db = _get_db()
    result = await asyncio.to_thread(build_screener, db)
    return result.to_dict()


@router.get("/chain/{expiry}")
async def option_chain(expiry: str) -> dict:
    """Detailed chain for a specific expiry date (YYYY-MM-DD)."""
    from src.analytics.options.screener import build_screener
    db = _get_db()
    result = await asyncio.to_thread(build_screener, db)
    for exp_slice in result.expiries:
        if exp_slice.expiry == expiry:
            return {
                "expiry": exp_slice.expiry,
                "dte": exp_slice.dte,
                "atm_iv": exp_slice.atm_iv,
                "strikes": exp_slice.strikes,
            }
    raise HTTPException(status_code=404, detail=f"Expiry {expiry} not found")


@router.get("/iv-history")
async def iv_history(
    days: int = Query(default=60, ge=7, le=365),
) -> dict:
    """Historical ATM IV values for charting."""
    from sqlalchemy import select, func
    from src.data.db import OptionQuote, OptionContract
    from src.analytics.options.pricing import implied_vol

    db = _get_db()
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    r, q = 0.0175, 0.0

    def _compute() -> list[dict]:
        with db.session() as session:
            ts_rows = session.execute(
                select(OptionQuote.timestamp)
                .where(OptionQuote.timestamp >= cutoff)
                .group_by(OptionQuote.timestamp)
                .order_by(OptionQuote.timestamp)
            ).scalars().all()

        result = []
        for ts in ts_rows:
            with db.session() as session:
                rows = session.execute(
                    select(OptionQuote, OptionContract)
                    .join(OptionContract, OptionQuote.contract_code == OptionContract.contract_code)
                    .where(OptionQuote.timestamp == ts)
                ).all()
            if not rows:
                continue
            S = rows[0][0].underlying_price
            best_diff = float("inf")
            best_iv = None
            for oq, oc in rows:
                exp_date = date.fromisoformat(oc.expiry_date)
                ts_date = date.fromisoformat(ts[:10])
                dte = (exp_date - ts_date).days
                if dte <= 0:
                    continue
                T = dte / 365.0
                mid = (oq.bid + oq.ask) / 2 if oq.bid and oq.ask else (oq.last or 0)
                if mid <= 0:
                    continue
                diff = abs(oc.strike - S)
                if diff < best_diff:
                    best_diff = diff
                    iv_val = implied_vol(mid, S, oc.strike, T, r, q, oc.option_type)
                    import math
                    if not math.isnan(iv_val):
                        best_iv = iv_val
            if best_iv is not None:
                result.append({"timestamp": ts, "atm_iv": round(best_iv, 4)})
        return result

    data = await asyncio.to_thread(_compute)
    return {"days": days, "history": data}


@router.post("/crawl")
async def trigger_options_crawl() -> dict:
    """Trigger a one-shot TXO chain snapshot crawl."""
    try:
        import shioaji as sj
    except ImportError:
        raise HTTPException(status_code=503, detail="Broker not available (shioaji not installed)")

    from src.data.options_crawl import crawl_option_chain_snapshot

    api_key, secret_key = None, None
    # Try secrets manager first, then fall back to env vars
    try:
        from src.secrets.manager import get_secret_manager
        sm = get_secret_manager()
        creds = sm.get_group("sinopac")
        api_key = creds.get("api_key")
        secret_key = creds.get("secret_key")
    except Exception:
        pass
    if not api_key or not secret_key:
        api_key = os.environ.get("SHIOAJI_API_KEY")
        secret_key = os.environ.get("SHIOAJI_API_SECRET")
    if not api_key or not secret_key:
        raise HTTPException(status_code=503, detail="Broker credentials not configured (set SHIOAJI_API_KEY/SHIOAJI_API_SECRET or config/secrets.toml)")

    api = sj.Shioaji()
    try:
        api.login(api_key, secret_key)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Broker login failed: {exc}")

    db = _get_db()
    try:
        count = await asyncio.to_thread(crawl_option_chain_snapshot, api, db)
    finally:
        try:
            api.logout()
        except Exception:
            pass
    return {"status": "ok", "quotes_stored": count}


@router.get("/contracts")
async def list_option_contracts(
    active_only: bool = Query(default=True),
) -> list[dict]:
    """List known option contracts."""
    from sqlalchemy import select
    from src.data.db import OptionContract

    db = _get_db()

    def _query() -> list[dict]:
        with db.session() as session:
            q = select(OptionContract)
            if active_only:
                q = q.where(OptionContract.delisted_at.is_(None))
            rows = session.execute(q).scalars().all()
            return [
                {
                    "contract_code": r.contract_code,
                    "underlying": r.underlying_symbol,
                    "expiry": r.expiry_date,
                    "strike": r.strike,
                    "type": r.option_type,
                }
                for r in rows
            ]

    return await asyncio.to_thread(_query)


@router.get("/accounts")
async def list_trading_accounts() -> list[dict]:
    """List available trading accounts (from GatewayRegistry)."""
    try:
        from src.broker_gateway.registry import GatewayRegistry
        registry = GatewayRegistry.get_instance()
        accounts = []
        for gw_id, gw in registry.gateways.items():
            if not gw.is_connected:
                continue
            api = getattr(gw, "_api", None)
            if api is None:
                continue
            acct = getattr(api, "futopt_account", None)
            if acct is None:
                continue
            accounts.append({
                "gateway_id": gw_id,
                "account_id": acct.account_id if hasattr(acct, "account_id") else str(acct),
                "broker_id": acct.broker_id if hasattr(acct, "broker_id") else "",
                "label": f"{gw_id} ({acct.account_id})" if hasattr(acct, "account_id") else gw_id,
            })
        return accounts
    except Exception as exc:
        logger.warning("list_trading_accounts_failed", error=str(exc))
        return []


@router.post("/order")
async def place_option_order(req: OptionOrderRequest) -> dict:
    """Place a TXO option order through a specific trading account."""
    if req.quantity < 1 or req.quantity > 100:
        raise HTTPException(status_code=400, detail="Quantity must be 1-100")
    if req.side not in ("buy", "sell"):
        raise HTTPException(status_code=400, detail="Side must be 'buy' or 'sell'")
    if req.order_type == "limit" and req.price <= 0:
        raise HTTPException(status_code=400, detail="Limit price must be positive")
    try:
        from src.broker_gateway.registry import GatewayRegistry
        registry = GatewayRegistry.get_instance()
        gw = registry.gateways.get(req.account_id)
        if gw is None:
            raise HTTPException(status_code=404, detail=f"Account not found: {req.account_id}")
        if not gw.is_connected:
            raise HTTPException(status_code=503, detail=f"Account {req.account_id} is not connected")
        result = await asyncio.to_thread(
            gw.place_option_order,
            contract_code=req.contract_code,
            side=req.side,
            quantity=req.quantity,
            price=req.price,
            order_type=req.order_type,
        )
        return {"status": "ok", **result}
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("place_option_order_failed", error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/positions")
async def get_option_positions() -> list[dict]:
    """Fetch current option positions from all connected gateways."""
    try:
        from src.broker_gateway.registry import GatewayRegistry
        registry = GatewayRegistry.get_instance()
        positions = []
        for gw_id, gw in registry.gateways.items():
            if not gw.is_connected:
                continue
            api = getattr(gw, "_api", None)
            if api is None:
                continue
            try:
                api.update_status(api.futopt_account)
                for trade in api.list_trades():
                    code = getattr(trade.contract, "code", "")
                    if not code.startswith("TXO"):
                        continue
                    contract = trade.contract
                    status = trade.status
                    order = trade.order
                    qty = getattr(status, "deal_quantity", 0) or getattr(order, "quantity", 0)
                    if qty == 0:
                        continue
                    positions.append({
                        "gateway_id": gw_id,
                        "contract_code": code,
                        "strike": float(getattr(contract, "strike_price", 0)),
                        "option_type": str(getattr(contract, "option_right", "")),
                        "expiry": getattr(contract, "delivery_date", "").replace("/", "-"),
                        "side": str(getattr(order, "action", "")),
                        "quantity": qty,
                        "avg_price": float(getattr(status, "modified_price", 0) or 0),
                        "status": str(getattr(status, "status", "")),
                    })
            except Exception as exc:
                logger.warning("get_positions_failed", gateway=gw_id, error=str(exc))
        return positions
    except Exception as exc:
        logger.warning("get_option_positions_failed", error=str(exc))
        return []
