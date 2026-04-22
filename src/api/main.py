"""FastAPI application for the quant engine — REST + WebSocket API."""
from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from src.pipeline.logging import setup_logging
from src.api.routes import (
    accounts,
    admin_warroom,
    backtest,
    coverage,
    crawl,
    deploy,
    editor,
    heartbeat,
    kill_switch,
    live_portfolios,
    meta,
    monte_carlo,
    ohlcv,
    optimizer,
    orders,
    paper_trade,
    params,
    portfolio,
    risk_evaluation,
    sessions,
    strategies,
    war_room,
)
from src.api.ws import backtest as ws_backtest
from src.api.ws import blotter as ws_blotter
from src.api.ws import live_feed, risk, spread_feed

_main_loop: asyncio.AbstractEventLoop | None = None
_frontend_dist = Path(
    os.getenv(
        "QUANT_FRONTEND_DIST",
        str(Path(__file__).resolve().parents[2] / "frontend" / "dist"),
    )
).resolve()
_frontend_index = _frontend_dist / "index.html"

setup_logging()

def get_main_loop() -> asyncio.AbstractEventLoop | None:
    return _main_loop

log = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    global _main_loop
    _main_loop = asyncio.get_running_loop()
    # Eagerly initialize broker gateways in prod; skip in dev to avoid
    # shioaji C++ crashes when IP is not whitelisted.
    if os.getenv("QUANT_SKIP_BROKER_INIT") != "1":
        try:
            from src.api.helpers import _init_war_room
            _init_war_room()
        except Exception:
            pass  # non-fatal: dashboard still works, just no live feed until retry

    # Startup gap repair: backfill missing bars from last 3 days
    if os.getenv("QUANT_SKIP_BROKER_INIT") != "1":
        async def _bg_gap_repair() -> None:
            try:
                from src.data.gap_repair import startup_gap_repair
                result = await asyncio.to_thread(startup_gap_repair, ["TMF"])
                if result:
                    log.info("startup_gap_repair_complete: %s", result)
            except Exception as exc:
                log.warning("startup_gap_repair_failed: %s", exc)

        asyncio.create_task(_bg_gap_repair())

    # War Room mock seeder (dev-only, gated by QUANT_WARROOM_SEED=1).
    app.state._seed_task = None
    if os.environ.get("QUANT_WARROOM_SEED") == "1":
        from src.trading_session.warroom_seeder import seed_mock_warroom

        async def _bg_seed() -> None:
            try:
                await asyncio.wait_for(
                    asyncio.to_thread(seed_mock_warroom, "mock-dev", 30, False),
                    timeout=60.0,
                )
            except TimeoutError:
                log.warning(
                    "warroom.seed.timeout after 60s — using placeholder data"
                )
            except Exception as exc:
                log.exception("warroom.seed.error", extra={"error": str(exc)})

        app.state._seed_task = asyncio.create_task(_bg_seed())

    try:
        yield
    finally:
        seed_task = getattr(app.state, "_seed_task", None)
        if seed_task is not None and not seed_task.done():
            seed_task.cancel()
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
app.include_router(live_portfolios.router)
app.include_router(meta.router)
app.include_router(kill_switch.router)
app.include_router(heartbeat.router)
app.include_router(monte_carlo.router)
app.include_router(portfolio.router)
app.include_router(risk_evaluation.router)
app.include_router(admin_warroom.router)
app.include_router(paper_trade.router)
app.include_router(orders.router)

# WebSocket routes
app.include_router(live_feed.router)
app.include_router(ws_backtest.router)
app.include_router(risk.router)
app.include_router(ws_blotter.router)
app.include_router(spread_feed.router)

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
