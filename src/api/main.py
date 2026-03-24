"""FastAPI application for the quant engine — REST + WebSocket API."""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api.routes import accounts, backtest, coverage, crawl, deploy, editor, ohlcv, optimizer, params, sessions, strategies, war_room
from src.api.ws import backtest as ws_backtest
from src.api.ws import live_feed, risk

app = FastAPI(
    title="Quant Engine API",
    version="0.1.0",
    docs_url="/docs",
    redoc_url=None,
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


# WebSocket routes
app.include_router(live_feed.router)
app.include_router(ws_backtest.router)
app.include_router(risk.router)


@app.get("/api/health")
async def health() -> dict:
    return {"status": "ok"}
