"""OHLCV data endpoint."""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Query

from src.api.helpers import load_ohlcv

router = APIRouter(prefix="/api", tags=["data"])

# MTX tracks the same TAIEX index as TX — use TX bars when MTX data is missing.
_CHART_FALLBACK: dict[str, str] = {"MTX": "TX"}


@router.get("/ohlcv")
async def get_ohlcv(
    symbol: str = Query(..., description="Contract symbol (e.g. TX)"),
    start: str = Query(..., description="Start date YYYY-MM-DD"),
    end: str = Query(..., description="End date YYYY-MM-DD"),
    tf_minutes: int = Query(60, description="Timeframe in minutes"),
) -> dict:
    try:
        start_dt = datetime.fromisoformat(start)
        end_dt = datetime.fromisoformat(end)
    except ValueError as exc:
        from fastapi import HTTPException
        raise HTTPException(status_code=422, detail=f"Invalid date format: {exc}")
    df = load_ohlcv(symbol, start_dt, end_dt, tf_minutes)
    fallback_used = None
    if df.empty and symbol in _CHART_FALLBACK:
        fallback_used = _CHART_FALLBACK[symbol]
        df = load_ohlcv(fallback_used, start_dt, end_dt, tf_minutes)
    if df.empty:
        return {"bars": [], "count": 0}
    bars = df.to_dict(orient="records")
    for bar in bars:
        if "timestamp" in bar:
            bar["timestamp"] = str(bar["timestamp"])
    result: dict = {"bars": bars, "count": len(bars)}
    if fallback_used:
        result["fallback_symbol"] = fallback_used
    return result
