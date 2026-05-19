"""TXO Options IV Screener API routes."""
from __future__ import annotations

import asyncio
import logging
import math
import os
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


def _registry():
    """Return the lazy-initialized GatewayRegistry, or None if not yet set up.

    There is no GatewayRegistry.get_instance() — the canonical accessor lives
    in src.api.helpers and uses module-level state. Routes were calling a
    method that doesn't exist (raising AttributeError → 500). Fix by routing
    everything through this helper.
    """
    try:
        from src.api.helpers import get_gateway_registry
        return get_gateway_registry()
    except Exception:
        return None


def _iter_connected_gateways():
    """Yield (gateway_id, gateway) pairs for all connected gateways.

    Returns an empty iterator when the registry isn't initialized yet, so
    routes never 500 just because the trading session hasn't started.
    """
    reg = _registry()
    if reg is None:
        return
    for aid in reg.account_ids:
        gw = reg.get_gateway(aid)
        if gw is not None and getattr(gw, "is_connected", False):
            yield aid, gw


def _get_gateway(gateway_id: str):
    """Return a connected gateway by id, or None."""
    reg = _registry()
    if reg is None:
        return None
    gw = reg.get_gateway(gateway_id)
    if gw is None or not getattr(gw, "is_connected", False):
        return None
    return gw


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
    from sqlalchemy import func, select

    from src.analytics.options.pricing import implied_vol
    from src.data.db import OptionContract, OptionQuote

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
        accounts = []
        for gw_id, gw in _iter_connected_gateways():
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
        logger.warning("list_trading_accounts_failed: %s", str(exc))
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
        gw = _get_gateway(req.account_id)
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
        logger.error("place_option_order_failed: %s", str(exc))
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/positions")
async def get_option_positions() -> list[dict]:
    """Fetch current option positions from all connected gateways with mark-to-market."""
    from sqlalchemy import select

    from src.data.db import OptionContract, OptionQuote

    def _lookup_mtm(db_url: str, contract_code: str) -> tuple[float | None, float]:
        """Return (mark_price, multiplier) for a contract_code from the latest quote."""
        from src.data.db import Database
        db = Database(db_url)
        with db.session() as session:
            oq = session.execute(
                select(OptionQuote)
                .where(OptionQuote.contract_code == contract_code)
                .order_by(OptionQuote.timestamp.desc())
                .limit(1)
            ).scalar_one_or_none()
            oc = session.execute(
                select(OptionContract)
                .where(OptionContract.contract_code == contract_code)
            ).scalar_one_or_none()
        mark_price: float | None = None
        if oq is not None:
            if oq.bid is not None and oq.ask is not None:
                mark_price = (oq.bid + oq.ask) / 2.0
            elif oq.last is not None:
                mark_price = float(oq.last)
        multiplier = float(oc.multiplier) if oc is not None and oc.multiplier else 50.0
        return mark_price, multiplier

    try:
        positions = []
        for gw_id, gw in _iter_connected_gateways():
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
                    avg_price = float(getattr(status, "modified_price", 0) or 0)
                    side_str = str(getattr(order, "action", ""))
                    pos: dict = {
                        "gateway_id": gw_id,
                        "contract_code": code,
                        "strike": float(getattr(contract, "strike_price", 0)),
                        "option_type": str(getattr(contract, "option_right", "")),
                        "expiry": getattr(contract, "delivery_date", "").replace("/", "-"),
                        "side": side_str,
                        "quantity": qty,
                        "avg_price": avg_price,
                        "status": str(getattr(status, "status", "")),
                    }
                    # Mark-to-market enrichment
                    try:
                        mark_price, multiplier = await asyncio.to_thread(
                            _lookup_mtm, f"sqlite:///{DB_PATH}", code
                        )
                        pos["multiplier"] = multiplier
                        pos["mark_price"] = mark_price
                        if mark_price is not None and avg_price > 0:
                            side_sign = 1.0 if side_str == "Buy" else -1.0
                            pos["unrealized_pnl"] = (
                                (mark_price - avg_price) * qty * multiplier * side_sign
                            )
                        else:
                            pos["unrealized_pnl"] = None
                    except Exception as mtm_exc:
                        logger.debug("mtm_lookup_failed contract=%s error=%s", code, mtm_exc)
                        pos["multiplier"] = 50.0
                        pos["mark_price"] = None
                        pos["unrealized_pnl"] = None
                    positions.append(pos)
            except Exception as exc:
                logger.warning("get_positions_failed gateway=%s: %s", gw_id, str(exc))
        return positions
    except Exception as exc:
        logger.warning("get_option_positions_failed: %s", str(exc))
        return []


class LegRequest(BaseModel):
    option_type: str  # "C" or "P"
    strike: float
    side: str         # "buy" or "sell"
    qty: int = 1
    price: float
    multiplier: float = 50.0


class ScenariosRequest(BaseModel):
    legs: list[LegRequest]
    S_now: float
    dte_days: int
    sigma: float = 0.20
    r: float = 0.0175
    q: float = 0.0


@router.post("/scenarios")
async def compute_option_scenarios(req: ScenariosRequest) -> dict:
    """Compute payoff curve, breakeven, max profit/loss, premium, margin estimate."""
    for L in req.legs:
        if L.qty < 1 or L.qty > 100:
            raise HTTPException(status_code=400, detail=f"qty must be 1-100, got {L.qty}")
        if L.side not in ("buy", "sell"):
            raise HTTPException(status_code=400, detail=f"side must be 'buy' or 'sell', got {L.side!r}")

    from src.analytics.options.scenarios import Leg, compute_scenarios
    legs = [
        Leg(
            option_type=L.option_type,
            strike=L.strike,
            side=L.side,
            qty=L.qty,
            price=L.price,
            multiplier=L.multiplier,
        )
        for L in req.legs
    ]
    result = await asyncio.to_thread(
        compute_scenarios,
        legs, req.S_now, req.dte_days,
        r=req.r, q=req.q, sigma=req.sigma,
    )

    def _safe(x):
        if isinstance(x, float) and (math.isinf(x) or math.isnan(x)):
            return None if math.isnan(x) else "inf"
        return x

    return {k: _safe(v) for k, v in result.items()}


@router.get("/portfolio-greeks")
async def portfolio_greeks_route() -> dict:
    """Aggregate net delta/gamma/theta/vega across all open option positions.

    Combines /api/options/positions data with the latest screener chain
    payload so the frontend can show "if I add this trade, my book delta
    changes from X to Y" without a second round-trip.
    """
    from src.analytics.options.portfolio import aggregate_greeks
    from src.analytics.options.screener import build_screener
    db = _get_db()
    chain = await asyncio.to_thread(build_screener, db)
    flat_strikes: list[dict] = []
    for exp in chain.expiries:
        flat_strikes.extend(exp.strikes)
    positions = await get_option_positions()
    return aggregate_greeks(positions, flat_strikes)


# ------------------------------------------------------------------ #
# Order lifecycle — list / cancel / amend                             #
# ------------------------------------------------------------------ #


class AmendOrderRequest(BaseModel):
    price: float | None = None
    quantity: int | None = None


@router.get("/orders")
async def list_open_option_orders() -> list[dict]:
    """Aggregate open TXO orders across all connected gateways."""
    all_orders: list[dict] = []
    for gw_id, gw in _iter_connected_gateways():
        try:
            orders = await asyncio.to_thread(gw.list_open_orders)
            for o in orders:
                all_orders.append({**o, "gateway_id": gw_id})
        except Exception as exc:
            logger.warning("list_orders_failed gateway=%s error=%s", gw_id, exc)
    return all_orders


@router.post("/orders/{order_id}/cancel")
async def cancel_option_order(order_id: str, gateway_id: str = Query(...)) -> dict:
    """Cancel an open TXO option order."""
    gw = _get_gateway(gateway_id)
    if gw is None:
        raise HTTPException(404, f"Gateway not found or disconnected: {gateway_id}")
    try:
        result = await asyncio.to_thread(gw.cancel_order, order_id)
        return {**result, "status": "ok"}
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(500, f"Cancel failed: {exc}") from exc


@router.patch("/orders/{order_id}")
async def amend_option_order(
    order_id: str,
    req: AmendOrderRequest,
    gateway_id: str = Query(...),
) -> dict:
    """Amend price and/or quantity of an open TXO option order."""
    if req.price is None and req.quantity is None:
        raise HTTPException(400, "Provide at least one of price or quantity")
    gw = _get_gateway(gateway_id)
    if gw is None:
        raise HTTPException(404, f"Gateway not found or disconnected: {gateway_id}")
    try:
        result = await asyncio.to_thread(
            gw.amend_order, order_id, price=req.price, qty=req.quantity
        )
        return {**result, "status": "ok"}
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(500, f"Amend failed: {exc}") from exc


# ---------------------------------------------------------------------------
# Combo order placement
# ---------------------------------------------------------------------------


class ComboLegRequest(BaseModel):
    contract_code: str
    side: str  # 'buy' or 'sell'
    quantity: int = 1
    price: float
    order_type: str = "limit"


class ComboOrderRequest(BaseModel):
    account_id: str
    legs: list[ComboLegRequest]
    dry_run: bool = False


@router.post("/orders/combo")
async def place_combo_option_order(req: ComboOrderRequest) -> dict:
    """Place a multi-leg combo option order.

    If dry_run is True, classify the combo and return the recognized structure
    without hitting the broker. If False, route to gateway.place_combo_order.
    """
    from sqlalchemy import select as _select

    from src.analytics.options.scenarios import Leg
    from src.analytics.options.strategy_recognizer import classify_combo
    from src.data.db import OptionContract

    if not req.legs:
        raise HTTPException(status_code=400, detail="Empty legs list")
    if len(req.legs) > 4:
        raise HTTPException(status_code=400, detail="More than 4 legs not supported")
    for L in req.legs:
        if L.side not in ("buy", "sell"):
            raise HTTPException(status_code=400, detail=f"Invalid side: {L.side}")
        if L.quantity < 1 or L.quantity > 100:
            raise HTTPException(status_code=400, detail=f"Invalid quantity: {L.quantity}")

    db = _get_db()
    leg_objects: list[Leg] = []
    with db.session() as s:
        for L in req.legs:
            oc = s.execute(
                _select(OptionContract).where(OptionContract.contract_code == L.contract_code)
            ).scalar_one_or_none()
            if oc is None:
                raise HTTPException(status_code=404, detail=f"Unknown contract: {L.contract_code}")
            leg_objects.append(Leg(
                option_type=oc.option_type,
                strike=oc.strike,
                side=L.side,
                qty=L.quantity,
                price=L.price,
                multiplier=oc.multiplier,
            ))

    try:
        combo = classify_combo(leg_objects)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if req.dry_run:
        return {
            "status": "dry_run",
            "combo": {
                "name": combo.name,
                "confidence": combo.confidence,
                "notes": combo.notes,
            },
            "legs": [L.model_dump() for L in req.legs],
        }

    gw = _get_gateway(req.account_id)
    if gw is None:
        raise HTTPException(status_code=404, detail=f"Gateway not connected: {req.account_id}")

    result = await asyncio.to_thread(gw.place_combo_order, [L.model_dump() for L in req.legs])
    return {
        "status": "ok",
        "combo": {"name": combo.name, "confidence": combo.confidence, "notes": combo.notes},
        **result,
    }
