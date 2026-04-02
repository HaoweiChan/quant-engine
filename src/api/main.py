"""FastAPI application for the quant engine — REST + WebSocket API."""
from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from src.api.routes import (
    accounts,
    backtest,
    coverage,
    crawl,
    deploy,
    editor,
    heartbeat,
    kill_switch,
    meta,
    monte_carlo,
    ohlcv,
    optimizer,
    params,
    portfolio,
    sessions,
    strategies,
    war_room,
)
from src.api.ws import backtest as ws_backtest
from src.api.ws import blotter as ws_blotter
from src.api.ws import live_feed, risk

_main_loop: asyncio.AbstractEventLoop | None = None
_frontend_dist = Path(
    os.getenv(
        "QUANT_FRONTEND_DIST",
        str(Path(__file__).resolve().parents[2] / "frontend" / "dist"),
    )
).resolve()
_frontend_index = _frontend_dist / "index.html"

def get_main_loop() -> asyncio.AbstractEventLoop | None:
    return _main_loop

@asynccontextmanager
async def lifespan(app: FastAPI):
    global _main_loop
    _main_loop = asyncio.get_running_loop()
    # Eagerly initialize broker gateways so tick subscriptions start
    # immediately at backend startup — not lazily on first frontend request.
    try:
        from src.api.helpers import _init_war_room
        _init_war_room()
    except Exception:
        pass  # non-fatal: dashboard still works, just no live feed until retry
    yield
    _main_loop = None

app = FastAPI(
    title="Quant Engine API",
    version="0.1.0",
    docs_url="/docs",
    redoc_url=None,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# REST routes
app.include_router(ohlcv.router)
app.include_router(coverage.router)
app.include_router(strategies.router)
app.include_router(backtest.router)
app.include_router(optimizer.router)
app.include_router(accounts.router)
app.include_router(war_room.router)
app.include_router(crawl.router)
app.include_router(editor.router)
app.include_router(params.router)
app.include_router(deploy.router)
app.include_router(sessions.router)
app.include_router(meta.router)
app.include_router(kill_switch.router)
app.include_router(heartbeat.router)
app.include_router(monte_carlo.router)
app.include_router(portfolio.router)

# WebSocket routes
app.include_router(live_feed.router)
app.include_router(ws_backtest.router)
app.include_router(risk.router)
app.include_router(ws_blotter.router)

@app.get("/api/health")
async def health() -> dict:
    return {"status": "ok"}

def _is_reserved_path(path: str) -> bool:
    reserved_prefixes = ("api", "ws", "docs", "openapi.json", "redoc")
    return any(path == prefix or path.startswith(f"{prefix}/") for prefix in reserved_prefixes)

if _frontend_index.is_file():
    @app.get("/", include_in_schema=False)
    async def dashboard_index() -> FileResponse:
        return FileResponse(_frontend_index)

    @app.get("/{full_path:path}", include_in_schema=False)
    async def dashboard_assets(full_path: str) -> FileResponse:
        if _is_reserved_path(full_path):
            raise HTTPException(status_code=404, detail="Not Found")
        candidate = (_frontend_dist / full_path).resolve()
        if candidate.is_file() and candidate.is_relative_to(_frontend_dist):
            return FileResponse(candidate)
        return FileResponse(_frontend_index)
