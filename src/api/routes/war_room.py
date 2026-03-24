"""War Room data endpoint."""
from __future__ import annotations

import json

from fastapi import APIRouter

from src.api.helpers import get_war_room_data

router = APIRouter(prefix="/api", tags=["trading"])


def _resolve_deployment_info(session) -> dict:
    """Resolve deployed candidate → params + backtest metrics + stale flag."""
    info: dict = {
        "deployed_candidate_id": session.deployed_candidate_id,
        "deployed_params": None,
        "backtest_metrics": None,
        "is_stale": False,
        "active_candidate_id": None,
    }
    if not session.deployed_candidate_id:
        return info
    try:
        from src.strategies.param_registry import ParamRegistry
        reg = ParamRegistry()
        # Get deployed candidate params
        row = reg._conn.execute(
            "SELECT params, run_id, strategy FROM param_candidates WHERE id = ?",
            (session.deployed_candidate_id,),
        ).fetchone()
        if row:
            info["deployed_params"] = json.loads(row["params"])
            # Get backtest metrics from the associated trial
            trial = reg._conn.execute(
                """SELECT sharpe, total_pnl, win_rate, max_drawdown_pct, profit_factor, trade_count
                   FROM param_trials WHERE run_id = ? ORDER BY sharpe DESC LIMIT 1""",
                (row["run_id"],),
            ).fetchone()
            if trial:
                info["backtest_metrics"] = {
                    "sharpe": trial["sharpe"],
                    "total_pnl": trial["total_pnl"],
                    "win_rate": trial["win_rate"],
                    "max_drawdown_pct": trial["max_drawdown_pct"],
                    "profit_factor": trial["profit_factor"],
                    "trade_count": trial["trade_count"],
                }
            # Check stale: is deployed candidate still the active one?
            active = reg._conn.execute(
                "SELECT id FROM param_candidates WHERE strategy = ? AND is_active = 1",
                (row["strategy"],),
            ).fetchone()
            if active:
                info["active_candidate_id"] = active["id"]
                info["is_stale"] = active["id"] != session.deployed_candidate_id
        reg.close()
    except Exception:
        pass
    return info


@router.get("/war-room")
async def war_room() -> dict:
    try:
        data = get_war_room_data()
    except Exception as exc:
        return {"error": str(exc), "accounts": {}, "all_sessions": [], "sessions_by_account": {}}
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
        deploy_info = _resolve_deployment_info(s)
        sessions.append({
            "session_id": s.session_id,
            "account_id": s.account_id,
            "strategy_slug": s.strategy_slug,
            "symbol": s.symbol,
            "status": s.status,
            **deploy_info,
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
