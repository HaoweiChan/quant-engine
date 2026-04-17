"""OHLCV data endpoint."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query

from src.api.helpers import load_ohlcv

router = APIRouter(prefix="/api", tags=["data"])

_DB_PATH = Path(__file__).resolve().parent.parent.parent.parent / "data" / "market.db"

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


# Symbols with R1/R2 calendar spread support (R2 data must exist in market.db)
_SPREAD_SYMBOLS = {"TX", "MTX", "TMF"}


@router.get("/bars/spread/{symbol}")
async def get_spread_bars(
    symbol: str,
    start: str = Query(..., description="Start date YYYY-MM-DD"),
    end: str = Query(..., description="End date YYYY-MM-DD"),
    tf: int = Query(1, description="Timeframe in minutes"),
) -> dict:
    """Get synthetic spread bars (R1 - R2) for a symbol.

    Used by the war room SpreadView for historical spread visualization.
    Returns bars with an offset applied to ensure positive prices for charting.
    """
    if symbol not in _SPREAD_SYMBOLS:
        raise HTTPException(
            status_code=400,
            detail=f"Spread not supported for {symbol}. Allowed: {sorted(_SPREAD_SYMBOLS)}",
        )

    try:
        start_dt = datetime.fromisoformat(start)
        end_dt = datetime.fromisoformat(end)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"Invalid date format: {exc}")

    from src.data.db import Database
    from src.data.spread_monitor import get_live_buffer
    from src.mcp_server.facade import _build_spread_bars

    if not _DB_PATH.exists():
        raise HTTPException(status_code=503, detail="Database not available")

    db = Database(f"sqlite:///{_DB_PATH}")

    # Use live session offset if available for z-score continuity
    live_buffer = get_live_buffer(symbol)
    offset_override = live_buffer.get_session_offset() if live_buffer.warmup_complete else None

    leg2_sym = f"{symbol}_R2"
    bars, err = _build_spread_bars(
        db=db,
        leg1_sym=symbol,
        leg2_sym=leg2_sym,
        start=start_dt,
        end=end_dt,
        bar_agg=tf,
        offset_override=offset_override,
    )

    if err:
        raise HTTPException(status_code=400, detail=err)

    if not bars:
        return {"bars": [], "count": 0, "offset": offset_override or 100.0}

    # Convert bars to dict format matching frontend expectations
    bar_dicts = [
        {
            "timestamp": str(b.timestamp),
            "open": b.open,
            "high": b.high,
            "low": b.low,
            "close": b.close,
            "volume": b.volume,
        }
        for b in bars
    ]

    return {
        "bars": bar_dicts,
        "count": len(bar_dicts),
        "offset": offset_override if offset_override is not None else 100.0,
    }
