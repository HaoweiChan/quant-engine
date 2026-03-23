"""Crawl management endpoints."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.api.helpers import get_crawl_state, start_crawl

router = APIRouter(prefix="/api", tags=["data"])


class CrawlRequest(BaseModel):
    symbol: str
    start: str
    end: str


@router.post("/crawl/start", status_code=202)
async def start_crawl_endpoint(req: CrawlRequest) -> dict:
    ok = start_crawl(req.symbol, req.start, req.end)
    if not ok:
        raise HTTPException(status_code=409, detail="Crawl already running")
    return {"status": "started", "symbol": req.symbol}


@router.get("/crawl/status")
async def crawl_status() -> dict:
    return get_crawl_state()
