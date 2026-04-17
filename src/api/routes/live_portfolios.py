"""LivePortfolio endpoints — CRUD, membership, atomic mode flip.

See `.claude/plans/in-our-war-room-squishy-squirrel.md` for the
design. Membership endpoints cascade `portfolio_id` onto sessions;
the flip endpoint runs the precondition scan (all members flat +
stopped/paused) and returns 409 with per-session reasons on failure.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from src.trading_session.live_portfolio_manager import PortfolioFlipError

router = APIRouter(prefix="/api/live-portfolios", tags=["live-portfolios"])


class PortfolioCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    account_id: str
    mode: str = Field(default="paper", pattern="^(paper|live)$")


class MemberAttachRequest(BaseModel):
    session_id: str


class FlipModeRequest(BaseModel):
    mode: str = Field(..., pattern="^(paper|live)$")


def _get_manager():
    from src.api.helpers import get_live_portfolio_manager
    return get_live_portfolio_manager()


def _portfolio_to_dict(portfolio, members=None) -> dict:
    base = {
        "portfolio_id": portfolio.portfolio_id,
        "name": portfolio.name,
        "account_id": portfolio.account_id,
        "mode": portfolio.mode,
        "created_at": portfolio.created_at.isoformat(),
        "updated_at": portfolio.updated_at.isoformat(),
    }
    if members is not None:
        base["members"] = [
            {
                "session_id": s.session_id,
                "strategy_slug": s.strategy_slug,
                "symbol": s.symbol,
                "status": s.status,
                "equity_share": s.equity_share,
            }
            for s in members
        ]
        base["member_count"] = len(members)
    return base


@router.get("")
async def list_portfolios(account_id: str | None = None) -> list[dict]:
    mgr = _get_manager()
    portfolios = mgr.list_portfolios(account_id)
    return [
        _portfolio_to_dict(p, members=mgr.list_members(p.portfolio_id))
        for p in portfolios
    ]


@router.post("", status_code=201)
async def create_portfolio(req: PortfolioCreateRequest) -> dict:
    mgr = _get_manager()
    try:
        portfolio = mgr.create_portfolio(
            name=req.name, account_id=req.account_id, mode=req.mode,  # type: ignore[arg-type]
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    return _portfolio_to_dict(portfolio, members=[])


@router.get("/{portfolio_id}")
async def get_portfolio(portfolio_id: str) -> dict:
    mgr = _get_manager()
    portfolio = mgr.get_portfolio(portfolio_id)
    if portfolio is None:
        raise HTTPException(
            status_code=404, detail=f"Portfolio '{portfolio_id}' not found",
        )
    return _portfolio_to_dict(portfolio, members=mgr.list_members(portfolio_id))


@router.delete("/{portfolio_id}")
async def delete_portfolio(portfolio_id: str) -> dict:
    mgr = _get_manager()
    try:
        mgr.delete_portfolio(portfolio_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    return {"portfolio_id": portfolio_id, "status": "deleted"}


@router.post("/{portfolio_id}/members", status_code=201)
async def attach_member(portfolio_id: str, body: MemberAttachRequest) -> dict:
    mgr = _get_manager()
    try:
        session = mgr.attach_session(portfolio_id, body.session_id)
    except ValueError as exc:
        msg = str(exc)
        if "not found" in msg:
            raise HTTPException(status_code=404, detail=msg) from None
        raise HTTPException(status_code=409, detail=msg) from None
    return {
        "portfolio_id": portfolio_id,
        "session_id": session.session_id,
        "status": "attached",
    }


@router.delete("/{portfolio_id}/members/{session_id}")
async def detach_member(portfolio_id: str, session_id: str) -> dict:
    mgr = _get_manager()
    session = mgr._sessions.get_session(session_id)  # type: ignore[attr-defined]
    if session is None:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")
    if session.portfolio_id != portfolio_id:
        raise HTTPException(
            status_code=409,
            detail=f"Session '{session_id}' is not a member of portfolio '{portfolio_id}'",
        )
    try:
        mgr.detach_session(session_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    return {
        "portfolio_id": portfolio_id,
        "session_id": session_id,
        "status": "detached",
    }


@router.post("/{portfolio_id}/flip-mode")
async def flip_mode(portfolio_id: str, body: FlipModeRequest) -> dict:
    """Atomically flip portfolio mode after precondition scan.

    Returns 409 with per-session reasons when any member session is
    running or holds positions. The War Room UI surfaces these reasons
    so operators can flatten or stop the offenders before retrying.
    """
    mgr = _get_manager()
    try:
        portfolio = mgr.flip_mode(portfolio_id, body.mode)  # type: ignore[arg-type]
    except PortfolioFlipError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "portfolio_flip_rejected",
                "portfolio_id": portfolio_id,
                "reasons": exc.reasons,
            },
        ) from None
    except ValueError as exc:
        msg = str(exc)
        if "not found" in msg:
            raise HTTPException(status_code=404, detail=msg) from None
        raise HTTPException(status_code=400, detail=msg) from None
    return _portfolio_to_dict(portfolio, members=mgr.list_members(portfolio_id))
