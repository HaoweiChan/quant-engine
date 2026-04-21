#!/usr/bin/env python3
"""Configure paper-trading sessions for vol_managed_bnh + night_session_long.

Idempotent setup — running twice is safe, it updates the existing rows.

Creates:
  - vol_managed_bnh on TX with equity_share=0.60
  - night_session_long on TX with equity_share=0.40

Both bound to the existing 'sinopac-main' account (sandbox_mode=1,
demo_trading=1). Status is left as 'stopped' so the operator starts each
session manually when the market opens.

Usage: python3 scripts/setup-paper-sessions.py
"""
from __future__ import annotations

import sys

from src.trading_session.session import TradingSession
from src.trading_session.session_db import SessionDB

PAPER_ACCOUNT = "sinopac-main"
PLAN = [
    ("vol_managed_bnh", "TX", 0.60),
    ("night_session_long", "TX", 0.40),
]


def main() -> int:
    db = SessionDB()
    # Verify the paper account exists (we don't create it here — it's
    # already seeded in trading.db with sandbox_mode=1, which routes shioaji
    # to its simulation server). ``demo_trading`` was dropped; sandbox_mode
    # is now the single connection-mode flag.
    row = db._conn.execute(  # noqa: SLF001
        "SELECT id, broker, sandbox_mode FROM accounts WHERE id = ?",
        (PAPER_ACCOUNT,),
    ).fetchone()
    if row is None:
        print(f"ERROR: paper account {PAPER_ACCOUNT!r} not found in trading.db")
        print("Seed it first via the /api/accounts route or the CLI helper.")
        return 1
    if not row["sandbox_mode"]:
        print(
            f"ERROR: account {PAPER_ACCOUNT} is not in sandbox mode"
            f" (sandbox_mode={row['sandbox_mode']})"
        )
        return 1

    # Remove any legacy sessions on this account so the AllocationSlider UI
    # sees exactly the two planned sessions and can render in interactive
    # 2-session mode (it falls back to read-only at 3+). If a legacy
    # session is still active, we refuse to delete — the operator must
    # stop it first.
    planned_keys = {(slug, symbol) for slug, symbol, _ in PLAN}
    legacy_rows = db._conn.execute(  # noqa: SLF001
        "SELECT session_id, strategy_slug, symbol, status FROM sessions WHERE account_id = ?",
        (PAPER_ACCOUNT,),
    ).fetchall()
    for lr in legacy_rows:
        if (lr["strategy_slug"], lr["symbol"]) in planned_keys:
            continue
        if lr["status"] == "active":
            print(
                f"SKIP     {lr['strategy_slug']:22} {lr['symbol']}  still active —"
                f" stop it before rerunning this script"
            )
            continue
        db.delete_session(lr["session_id"])
        print(f"removed  {lr['strategy_slug']:22} {lr['symbol']}  (legacy, not in plan)")

    for slug, symbol, share in PLAN:
        existing = db.find_session(PAPER_ACCOUNT, slug, symbol)
        if existing is None:
            session = TradingSession.create(
                account_id=PAPER_ACCOUNT,
                strategy_slug=slug,
                symbol=symbol,
                equity_share=share,
                status="stopped",
            )
            db.save(session)
            print(f"created  {slug:22} {symbol}  equity_share={share}  session_id={session.session_id}")
        else:
            existing.equity_share = share
            existing.status = "stopped"  # force safe initial state
            db.save(existing)
            db.update_equity_share(existing.session_id, share)
            print(f"updated  {slug:22} {symbol}  equity_share={share}  session_id={existing.session_id}")

    total = db.sum_equity_share_for_account(PAPER_ACCOUNT)
    print(f"\ntotal equity_share on {PAPER_ACCOUNT}: {total:.2f}")
    if total > 1.0 + 1e-6:
        print(f"WARNING: total exceeds 1.0 — remove unused sessions before going live.")
        return 2
    print("Setup complete. Start each session from the War Room when ready.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
