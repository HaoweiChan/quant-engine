"""Tests for alerting: dispatcher, formatters, and wiring."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from src.alerting.dispatcher import NotificationDispatcher
from src.alerting.formatters import (
    format_daily_summary,
    format_entry,
    format_exit,
    format_pre_trade_rejection,
    format_risk_alert,
    format_trade,
)
from src.core.types import Order, RiskAction
from src.execution.engine import ExecutionResult


def _result(reason: str = "entry", side: str = "buy") -> ExecutionResult:
    return ExecutionResult(
        order=Order(
            order_type="market", side=side, symbol="TX",
            contract_type="large", lots=2.0, price=None,
            stop_price=None, reason=reason,
        ),
        status="filled", fill_price=20100.0, expected_price=20098.0,
        slippage=2.0, fill_qty=2.0, remaining_qty=0.0,
    )


class TestFormatters:
    def test_entry_format(self) -> None:
        msg = format_entry(_result("entry"))
        assert "ENTRY" in msg
        assert "BUY" in msg
        assert "TX" in msg

    def test_exit_format(self) -> None:
        msg = format_exit(_result("stop_loss", "sell"))
        assert "EXIT" in msg
        assert "stop_loss" in msg

    def test_risk_alert_format(self) -> None:
        msg = format_risk_alert(
            RiskAction.CLOSE_ALL, "drawdown_circuit_breaker",
            {"drawdown_pct": 0.12},
        )
        assert "RISK ALERT" in msg
        assert "close_all" in msg

    def test_pre_trade_rejection_format(self) -> None:
        msg = format_pre_trade_rejection(
            {
                "symbol": "TX",
                "reason": "insufficient_margin",
                "required_margin": 184000.0,
                "available_margin": 120000.0,
                "decision_direction": "long",
                "decision_lots": 1.0,
            }
        )
        assert "PRE-TRADE REJECTION" in msg
        assert "insufficient_margin" in msg

    def test_daily_summary(self) -> None:
        msg = format_daily_summary(2_000_000.0, 15_000.0, -3_000.0, 5)
        assert "Daily P&amp;L Summary" in msg
        assert "2,000,000" in msg

    def test_format_trade_entry(self) -> None:
        msg = format_trade(_result("entry"))
        assert "ENTRY" in msg

    def test_format_trade_stop(self) -> None:
        msg = format_trade(_result("stop_loss", "sell"))
        assert "EXIT" in msg

    def test_format_trade_add(self) -> None:
        msg = format_trade(_result("add_level_2"))
        assert "ADD" in msg


class TestDispatcher:
    @pytest.mark.asyncio
    async def test_successful_send(self) -> None:
        mock_resp = AsyncMock()
        mock_resp.status_code = 200

        with patch("src.alerting.dispatcher.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_resp
            mock_cls.return_value = mock_client

            dispatcher = NotificationDispatcher("fake_token", "123")
            dispatcher._client = mock_client
            result = await dispatcher.dispatch("test message")
            assert result is True
            mock_client.post.assert_called_once()

    @pytest.mark.asyncio
    async def test_failed_send_returns_false(self) -> None:
        mock_resp = AsyncMock()
        mock_resp.status_code = 400
        mock_resp.text = "Bad Request"

        with patch("src.alerting.dispatcher.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_resp
            mock_cls.return_value = mock_client

            dispatcher = NotificationDispatcher("fake_token", "123")
            dispatcher._client = mock_client
            result = await dispatcher.dispatch("test message")
            assert result is False

    @pytest.mark.asyncio
    async def test_exception_returns_false(self) -> None:
        with patch("src.alerting.dispatcher.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.post.side_effect = ConnectionError("network down")
            mock_cls.return_value = mock_client

            dispatcher = NotificationDispatcher("fake_token", "123")
            dispatcher._client = mock_client
            result = await dispatcher.dispatch("test message")
            assert result is False

    @pytest.mark.asyncio
    async def test_dispatch_pre_trade_rejection(self) -> None:
        mock_resp = AsyncMock()
        mock_resp.status_code = 200
        with patch("src.alerting.dispatcher.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_resp
            mock_cls.return_value = mock_client
            dispatcher = NotificationDispatcher("fake_token", "123")
            dispatcher._client = mock_client
            ok = await dispatcher.dispatch_pre_trade_rejection(
                {
                    "symbol": "TX",
                    "reason": "missing_account_context",
                    "required_margin": 184000.0,
                    "available_margin": None,
                    "decision_direction": "short",
                    "decision_lots": 1.0,
                }
            )
            assert ok is True
            mock_client.post.assert_called_once()
