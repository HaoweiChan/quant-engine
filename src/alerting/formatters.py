"""Message formatters for Telegram notifications."""
from __future__ import annotations

from src.core.types import RiskAction
from src.execution.engine import ExecutionResult


def format_entry(result: ExecutionResult) -> str:
    o = result.order
    return (
        f"<b>ENTRY</b> {o.side.upper()} {o.symbol}\n"
        f"Lots: {result.fill_qty}  Price: {result.fill_price:,.0f}\n"
        f"Slippage: {result.slippage:+.1f} pts"
    )


def format_exit(result: ExecutionResult) -> str:
    o = result.order
    return (
        f"<b>EXIT</b> {o.side.upper()} {o.symbol}\n"
        f"Lots: {result.fill_qty}  Price: {result.fill_price:,.0f}\n"
        f"Reason: {o.reason}"
    )


def format_add_position(result: ExecutionResult) -> str:
    o = result.order
    return (
        f"<b>ADD</b> {o.side.upper()} {o.symbol}\n"
        f"Lots: {result.fill_qty}  Price: {result.fill_price:,.0f}\n"
        f"Slippage: {result.slippage:+.1f} pts"
    )


def format_risk_alert(action: RiskAction, trigger: str, details: dict) -> str:
    return (
        f"<b>RISK ALERT</b>\n"
        f"Action: {action.value}\n"
        f"Trigger: {trigger}\n"
        f"Details: {details}"
    )


def format_daily_summary(
    equity: float, realized_pnl: float,
    unrealized_pnl: float, trade_count: int,
) -> str:
    total_pnl = realized_pnl + unrealized_pnl
    emoji = "+" if total_pnl >= 0 else ""
    return (
        f"<b>Daily P&amp;L Summary</b>\n"
        f"Equity: {equity:,.0f}\n"
        f"Realized: {emoji}{realized_pnl:,.0f}\n"
        f"Unrealized: {emoji}{unrealized_pnl:,.0f}\n"
        f"Trades today: {trade_count}"
    )


def format_trade(result: ExecutionResult) -> str:
    """Auto-select formatter based on order reason."""
    reason = result.order.reason
    if reason == "entry":
        return format_entry(result)
    if reason in ("stop_loss", "trail_stop", "close"):
        return format_exit(result)
    if reason.startswith("add"):
        return format_add_position(result)
    return format_exit(result)
