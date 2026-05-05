"""TXO Options IV Screener API routes."""
from __future__ import annotations

import asyncio
import logging
from datetime import date, timedelta

from fastapi import APIRouter, HTTPException, Query

from src.api.deps import DB_PATH
from src.data.db import Database

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/options", tags=["options"])


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
    from src.secrets.manager import get_secret_manager

    try:
        sm = get_secret_manager()
        creds = sm.get_group("sinopac")
        api_key = creds.get("api_key")
        secret_key = creds.get("secret_key")
        if not api_key or not secret_key:
            raise HTTPException(status_code=503, detail="Broker credentials not configured")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Broker not initialized: {exc}")

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
