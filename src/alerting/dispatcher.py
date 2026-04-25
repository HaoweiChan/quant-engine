"""Telegram notification dispatcher — fire-and-forget, never crash the system."""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import httpx
import structlog
from typing import Any

logger = structlog.get_logger(__name__)
_TAIPEI_TZ = ZoneInfo("Asia/Taipei")

_BASE_URL = "https://api.telegram.org/bot{token}/sendMessage"


class NotificationDispatcher:
    """Send messages to a Telegram chat. Failures are logged, never raised.

    In dev mode (EXECUTION_ENV=dev), logs notifications but skips Telegram send.
    Also skips notifications for accounts starting with "mock".
    """

    def __init__(self, bot_token: str, chat_id: str, account_id: str | None = None) -> None:
        import os
        self._url = _BASE_URL.format(token=bot_token)
        self._chat_id = chat_id
        self._account_id = account_id
        self._client = httpx.AsyncClient(timeout=10.0)
        self._dev_mode = os.getenv("EXECUTION_ENV", "").lower() in ("dev", "mock-dev")

    def _log_to_activity(self, message: str, notification_type: str = "telegram") -> None:
        """Log notification to activity log (fire-and-forget)."""
        if not self._account_id:
            return
        try:
            from src.trading_session.store import ActivityLogger
            activity_logger = ActivityLogger()
            activity_logger.log_notification(
                account_id=self._account_id,
                timestamp=datetime.now(_TAIPEI_TZ).isoformat(),
                notification_type=notification_type,
                message=message,
            )
        except Exception as e:
            logger.debug("activity_log_write_failed", error=str(e))

    async def dispatch(self, message: str, account_id: str | None = None) -> bool:
        self._log_to_activity(message)
        if self._dev_mode:
            logger.debug("telegram_skipped_dev_mode", message=message[:100])
            return True
        check_account = account_id or self._account_id
        if check_account and check_account.startswith("mock"):
            logger.debug("telegram_skipped_mock_account", account=check_account)
            return True
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

    async def dispatch_roll_window_open(
        self,
        symbol: str,
        holding_period: str,
        days_to_settlement: int,
        spread: float | None = None,
    ) -> bool:
        from src.alerting.formatters import format_roll_window_open

        return await self.dispatch(
            format_roll_window_open(symbol, holding_period, days_to_settlement, spread)
        )

    async def dispatch_roll_executed(
        self,
        symbol: str,
        strategy_slug: str,
        old_contract: str,
        new_contract: str,
        lots: float,
        spread_cost: float,
        trigger: str,
    ) -> bool:
        from src.alerting.formatters import format_roll_executed

        return await self.dispatch(
            format_roll_executed(
                symbol, strategy_slug, old_contract, new_contract,
                lots, spread_cost, trigger,
            )
        )

    async def dispatch_settlement_warning(
        self,
        symbol: str,
        days_remaining: int,
        open_lots: float,
    ) -> bool:
        from src.alerting.formatters import format_settlement_warning

        return await self.dispatch(
            format_settlement_warning(symbol, days_remaining, open_lots)
        )

    async def close(self) -> None:
        await self._client.aclose()
