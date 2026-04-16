"""Message formatters for Telegram notifications."""
from __future__ import annotations

from typing import Any

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
    realized_pnl = result.metadata.get("realized_pnl", 0.0) if result.metadata else 0.0
    pnl_sign = "+" if realized_pnl >= 0 else ""
    pnl_line = f"\nP&L: {pnl_sign}{realized_pnl:,.0f}" if realized_pnl != 0 else ""
    return (
        f"<b>EXIT</b> {o.side.upper()} {o.symbol}\n"
        f"Lots: {result.fill_qty}  Price: {result.fill_price:,.0f}\n"
        f"Reason: {o.reason}{pnl_line}"
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


def format_pre_trade_rejection(event: dict[str, Any]) -> str:
    return (
        f"<b>PRE-TRADE REJECTION</b>\n"
        f"Strategy: {event.get('strategy', 'unknown')}\n"
        f"Symbol: {event.get('symbol', 'unknown')}\n"
        f"Reason: {event.get('reason', 'unknown')}\n"
        f"Required margin: {event.get('required_margin', 0.0):,.0f}\n"
        f"Available margin: {event.get('available_margin', 0.0) if event.get('available_margin') is not None else 'N/A'}\n"
        f"Direction: {event.get('decision_direction', 'unknown')}\n"
        f"Lots: {event.get('decision_lots', 0.0)}"
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


def format_roll_window_open(
    symbol: str,
    holding_period: str,
    days_to_settlement: int,
    spread: float | None = None,
) -> str:
    spread_info = f"\nCurrent spread: {spread:+.1f} pts" if spread is not None else ""
    return (
        f"<b>ROLL WINDOW OPEN</b>\n"
        f"Symbol: {symbol}  ({holding_period})\n"
        f"Settlement in {days_to_settlement} days{spread_info}\n"
        f"Monitoring for optimal spread..."
    )


def format_roll_executed(
    symbol: str,
    strategy_slug: str,
    old_contract: str,
    new_contract: str,
    lots: float,
    spread_cost: float,
    trigger: str,
) -> str:
    return (
        f"<b>CONTRACT ROLLED</b>\n"
        f"Symbol: {symbol}\n"
        f"Strategy: {strategy_slug}\n"
        f"{old_contract} -> {new_contract}\n"
        f"Lots: {lots}  Spread cost: {spread_cost:,.0f}\n"
        f"Trigger: {trigger}"
    )


def format_settlement_warning(
    symbol: str,
    days_remaining: int,
    open_lots: float,
) -> str:
    urgency = "CRITICAL" if days_remaining <= 1 else "WARNING"
    return (
        f"<b>SETTLEMENT {urgency}</b>\n"
        f"Symbol: {symbol}\n"
        f"Settlement in {days_remaining} day(s)\n"
        f"Open lots: {open_lots}\n"
        f"Roll required before settlement!"
    )
