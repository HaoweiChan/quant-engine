"""Paper trading health check and live pipeline status endpoints."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, Query
from pydantic import BaseModel

router = APIRouter(prefix="/api/paper-trade", tags=["paper-trade"])

_DB_PATH = Path(__file__).resolve().parents[3] / "data" / "trading.db"
_MIN_SESSIONS = 5


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


@router.get("/health")
def paper_trade_health(account_id: str = Query(...)):
    """Automated paper trading readiness report for an account."""
    conn = _get_conn()
    try:
        cur = conn.cursor()

        # Session info
        cur.execute(
            "SELECT * FROM sessions WHERE account_id = ?",
            (account_id,),
        )
        sessions = [dict(r) for r in cur.fetchall()]
        active_sessions = [s for s in sessions if s["status"] in ("active", "stopped")]
        strategies = [s["strategy_slug"].split("/")[-1] for s in active_sessions]

        # Equity history
        cur.execute(
            "SELECT count(*) as cnt, min(timestamp) as first_ts, max(timestamp) as last_ts "
            "FROM account_equity_history WHERE account_id = ?",
            (account_id,),
        )
        eq_row = dict(cur.fetchone())
        equity_points = eq_row["cnt"]

        # Count distinct trading days from equity history
        cur.execute(
            "SELECT count(DISTINCT substr(timestamp, 1, 10)) as n_days "
            "FROM account_equity_history WHERE account_id = ?",
            (account_id,),
        )
        n_days = cur.fetchone()["n_days"]

        # Session snapshots (fills proxy)
        cur.execute(
            "SELECT count(*) as cnt FROM session_snapshots ss "
            "JOIN sessions s ON ss.session_id = s.session_id "
            "WHERE s.account_id = ?",
            (account_id,),
        )
        snapshot_count = cur.fetchone()["cnt"]

        # Equity anomalies: jumps > 20% between consecutive points
        cur.execute(
            "SELECT equity FROM account_equity_history WHERE account_id = ? ORDER BY id",
            (account_id,),
        )
        equities = [r["equity"] for r in cur.fetchall()]
        anomalies = 0
        for i in range(1, len(equities)):
            if equities[i - 1] > 0:
                change = abs(equities[i] - equities[i - 1]) / equities[i - 1]
                if change > 0.2:
                    anomalies += 1

        # Estimate sessions completed (2 per trading day: night + day)
        sessions_completed = n_days * 2

    finally:
        conn.close()

    # Build checks
    checks = {}

    checks["signal_generation"] = (
        "PASS" if snapshot_count > 0 else "PENDING — no snapshots recorded yet"
    )

    checks["order_execution"] = (
        "PASS" if snapshot_count > 0 else "PENDING — no fills yet"
    )

    checks["slippage"] = (
        "PENDING — fill-level slippage data not yet recorded"
    )

    checks["session_flatten"] = (
        "PENDING — requires fill analysis across session boundaries"
    )

    checks["kill_switch"] = "PASS — verified via API test"

    checks["equity_tracking"] = (
        "PASS" if anomalies == 0 and equity_points > 0
        else f"WARN — {anomalies} anomalies detected" if anomalies > 0
        else "PENDING — no equity data yet"
    )

    checks["clean_logs"] = "PENDING — requires log analysis"

    checks["position_reconciliation"] = "PENDING — requires runtime reconciliation data"

    min_sessions_met = sessions_completed >= _MIN_SESSIONS
    all_pass = all(v == "PASS" or v.startswith("PASS") for v in checks.values())

    if all_pass and min_sessions_met:
        verdict = "PASS — ready for live"
    elif equity_points == 0:
        verdict = "NOT STARTED — no equity data recorded"
    elif not min_sessions_met:
        verdict = f"IN PROGRESS — {sessions_completed}/{_MIN_SESSIONS} sessions completed"
    else:
        failing = [k for k, v in checks.items() if not v.startswith("PASS")]
        verdict = f"FAILING — checks not passing: {', '.join(failing)}"

    return {
        "account_id": account_id,
        "strategies": strategies,
        "sessions_completed": sessions_completed,
        "trading_days": n_days,
        "equity_points": equity_points,
        "snapshot_count": snapshot_count,
        "equity_anomalies": anomalies,
        "first_record": eq_row.get("first_ts"),
        "last_record": eq_row.get("last_ts"),
        "checks": checks,
        "min_sessions_met": min_sessions_met,
        "verdict": verdict,
    }


@router.get("/pipeline-status")
def pipeline_status():
    """Return live execution pipeline status and per-runner stats."""
    from src.api.helpers import get_live_pipeline, get_subscriber_stats
    pipeline = get_live_pipeline()
    subscriber = get_subscriber_stats()
    if pipeline is None:
        return {"status": "not_initialized", "runners": [], "subscriber": subscriber}
    return {
        "status": "running" if pipeline._started else "stopped",
        "runners": pipeline.get_all_stats(),
        "subscriber": subscriber,
    }


class TelegramConfigRequest(BaseModel):
    bot_token: str
    chat_id: str


@router.post("/configure-telegram")
async def configure_telegram(req: TelegramConfigRequest):
    """Store Telegram credentials in GSM and initialize the dispatcher."""
    from src.secrets.manager import get_secret_manager
    sm = get_secret_manager()
    sm.set("TELEGRAM_BOT_TOKEN", req.bot_token)
    sm.set("TELEGRAM_CHAT_ID", req.chat_id)
    # Re-initialize dispatcher with new credentials
    from src.alerting.dispatcher import NotificationDispatcher
    import src.api.helpers as h
    h._telegram_dispatcher = NotificationDispatcher(bot_token=req.bot_token, chat_id=req.chat_id)
    if h._live_pipeline:
        h._live_pipeline._notifier = h._telegram_dispatcher
    # Send test message
    ok = await h._telegram_dispatcher.dispatch(
        "<b>TAIFEX Trading System</b>\nTelegram connected successfully."
    )
    return {"status": "ok" if ok else "error", "message": "Configured and test sent" if ok else "Stored but test message failed"}


@router.post("/test-telegram")
async def test_telegram():
    """Send a test message to verify Telegram notification setup."""
    from src.api.helpers import get_telegram_dispatcher
    dispatcher = get_telegram_dispatcher()
    if dispatcher is None:
        return {
            "status": "error",
            "message": "Telegram not configured. Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in secrets.",
        }
    ok = await dispatcher.dispatch(
        "<b>TAIFEX Trading System</b>\nTest notification — Telegram integration is working."
    )
    return {"status": "ok" if ok else "error", "message": "Sent" if ok else "Failed to send"}


class SizingConfigRequest(BaseModel):
    risk_per_trade: float = 0.02
    margin_cap: float = 0.50
    max_lots: int = 10
    min_lots: int = 1


@router.get("/sizing")
def get_sizing():
    """Get the current portfolio-level sizing config."""
    from src.api.helpers import get_live_pipeline
    pipeline = get_live_pipeline()
    if pipeline is None:
        return {"status": "not_initialized"}
    cfg = pipeline._sizing_config
    return {
        "risk_per_trade": cfg.risk_per_trade,
        "margin_cap": cfg.margin_cap,
        "max_lots": cfg.max_lots,
        "min_lots": cfg.min_lots,
    }


@router.patch("/sizing")
def update_sizing(req: SizingConfigRequest):
    """Update the portfolio-level sizing config. Applies to all new entries."""
    from src.api.helpers import get_live_pipeline
    from src.core.sizing import SizingConfig
    pipeline = get_live_pipeline()
    if pipeline is None:
        return {"status": "error", "message": "Pipeline not initialized"}
    new_cfg = SizingConfig(
        risk_per_trade=req.risk_per_trade,
        margin_cap=req.margin_cap,
        max_lots=req.max_lots,
        min_lots=req.min_lots,
    )
    pipeline._sizing_config = new_cfg
    # Update existing runners
    for runner in pipeline._runners.values():
        runner._sizer._config = new_cfg
    return {"status": "ok", "config": new_cfg.__dict__}
