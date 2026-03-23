"""War Room data endpoint."""
from __future__ import annotations

from fastapi import APIRouter

from src.api.helpers import get_war_room_data

router = APIRouter(prefix="/api", tags=["trading"])


@router.get("/war-room")
async def war_room() -> dict:
    try:
        data = get_war_room_data()
    except Exception as exc:
        return {"error": str(exc), "accounts": {}, "all_sessions": [], "sessions_by_account": {}}
    # Serialize into JSON-safe format
    accounts = {}
    for acct_id, info in data.get("accounts", {}).items():
        snap = info.get("snapshot")
        config = info.get("config")
        equity_curve = info.get("equity_curve", [])
        accounts[acct_id] = {
            "display_name": config.display_name if config else acct_id,
            "broker": config.broker if config else "",
            "connected": bool(snap and snap.connected),
            "connect_error": info.get("connect_error"),
            "equity": snap.equity if snap and snap.connected else 0,
            "margin_used": snap.margin_used if snap and snap.connected else 0,
            "margin_available": snap.margin_available if snap and snap.connected else 0,
            "positions": [
                {
                    "symbol": p.symbol,
                    "side": p.side,
                    "quantity": p.quantity,
                    "avg_entry_price": p.avg_entry_price,
                    "unrealized_pnl": p.unrealized_pnl,
                }
                for p in (snap.positions if snap and snap.connected else [])
            ],
            "equity_curve": [
                {"timestamp": t.isoformat(), "equity": e}
                for t, e in equity_curve
            ],
        }
    sessions = []
    for s in data.get("all_sessions", []):
        snap = s.current_snapshot
        sessions.append({
            "account_id": s.account_id,
            "strategy_slug": s.strategy_slug,
            "symbol": s.symbol,
            "status": s.status,
            "snapshot": {
                "equity": snap.equity,
                "unrealized_pnl": snap.unrealized_pnl,
                "drawdown_pct": snap.drawdown_pct,
                "trade_count": snap.trade_count,
                "positions": [
                    {
                        "symbol": p.symbol,
                        "side": p.side,
                        "quantity": p.quantity,
                        "avg_entry_price": p.avg_entry_price,
                        "unrealized_pnl": p.unrealized_pnl,
                    }
                    for p in snap.positions
                ],
            } if snap else None,
        })
    return {
        "accounts": accounts,
        "all_sessions": sessions,
        "sessions_by_account": data.get("sessions_by_account", {}),
    }
