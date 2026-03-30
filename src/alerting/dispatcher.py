"""Telegram notification dispatcher — fire-and-forget, never crash the system."""
from __future__ import annotations

import httpx
import structlog
from typing import Any

logger = structlog.get_logger(__name__)

_BASE_URL = "https://api.telegram.org/bot{token}/sendMessage"


class NotificationDispatcher:
    """Send messages to a Telegram chat. Failures are logged, never raised."""

    def __init__(self, bot_token: str, chat_id: str) -> None:
        self._url = _BASE_URL.format(token=bot_token)
        self._chat_id = chat_id
        self._client = httpx.AsyncClient(timeout=10.0)

    async def dispatch(self, message: str) -> bool:
        try:
            resp = await self._client.post(
                self._url,
                json={"chat_id": self._chat_id, "text": message, "parse_mode": "HTML"},
            )
            if resp.status_code != 200:
                logger.warning(
                    "telegram_send_failed",
                    status=resp.status_code, body=resp.text[:200],
                )
                return False
            return True
        except Exception:
            logger.exception("telegram_dispatch_error")
            return False

    async def dispatch_pre_trade_rejection(self, event: dict[str, Any]) -> bool:
        from src.alerting.formatters import format_pre_trade_rejection

        return await self.dispatch(format_pre_trade_rejection(event))

    async def close(self) -> None:
        await self._client.aclose()
