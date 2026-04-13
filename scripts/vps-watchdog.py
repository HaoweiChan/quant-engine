#!/usr/bin/env python3
"""
VPS Watchdog - External heartbeat monitor for production trading platform.

Run this script on a SEPARATE machine (e.g., WSL dev box) to monitor the VPS.
If the VPS becomes unresponsive, the watchdog alerts and can trigger protective actions.

Usage:
    python scripts/vps-watchdog.py --vps-url https://your-vps.com --interval 30

Environment:
    WATCHDOG_TELEGRAM_TOKEN - Telegram bot token for alerts (optional)
    WATCHDOG_TELEGRAM_CHAT_ID - Telegram chat ID for alerts (optional)
    WATCHDOG_SLACK_WEBHOOK - Slack webhook URL for alerts (optional)
"""

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime, timedelta
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


class VPSWatchdog:
    """Monitor VPS health and alert on failures."""

    def __init__(
        self,
        vps_url: str,
        interval: int = 30,
        failure_threshold: int = 3,
        timeout: int = 10,
    ):
        self.vps_url = vps_url.rstrip("/")
        self.interval = interval
        self.failure_threshold = failure_threshold
        self.timeout = timeout
        self.consecutive_failures = 0
        self.last_success: datetime | None = None
        self.alert_sent = False

        # Alert configuration from environment
        self.telegram_token = os.getenv("WATCHDOG_TELEGRAM_TOKEN")
        self.telegram_chat_id = os.getenv("WATCHDOG_TELEGRAM_CHAT_ID")
        self.slack_webhook = os.getenv("WATCHDOG_SLACK_WEBHOOK")

    def check_health(self) -> dict[str, Any]:
        """Check VPS health endpoint."""
        url = f"{self.vps_url}/api/health"
        try:
            req = Request(url, headers={"User-Agent": "VPS-Watchdog/1.0"})
            with urlopen(req, timeout=self.timeout) as response:
                data = json.loads(response.read().decode())
                return {"ok": True, "data": data, "latency_ms": 0}
        except URLError as e:
            return {"ok": False, "error": str(e.reason)}
        except TimeoutError:
            return {"ok": False, "error": "timeout"}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def check_positions(self) -> dict[str, Any]:
        """Check if there are open positions on the VPS."""
        url = f"{self.vps_url}/api/positions"
        try:
            req = Request(url, headers={"User-Agent": "VPS-Watchdog/1.0"})
            with urlopen(req, timeout=self.timeout) as response:
                data = json.loads(response.read().decode())
                return {"ok": True, "positions": data.get("positions", [])}
        except Exception as e:
            return {"ok": False, "error": str(e), "positions": []}

    def send_telegram_alert(self, message: str) -> bool:
        """Send alert via Telegram."""
        if not self.telegram_token or not self.telegram_chat_id:
            return False
        try:
            url = f"https://api.telegram.org/bot{self.telegram_token}/sendMessage"
            data = json.dumps({
                "chat_id": self.telegram_chat_id,
                "text": message,
                "parse_mode": "HTML",
            }).encode()
            req = Request(url, data=data, headers={"Content-Type": "application/json"})
            with urlopen(req, timeout=10):
                return True
        except Exception as e:
            logger.error(f"Telegram alert failed: {e}")
            return False

    def send_slack_alert(self, message: str) -> bool:
        """Send alert via Slack webhook."""
        if not self.slack_webhook:
            return False
        try:
            data = json.dumps({"text": message}).encode()
            req = Request(
                self.slack_webhook,
                data=data,
                headers={"Content-Type": "application/json"},
            )
            with urlopen(req, timeout=10):
                return True
        except Exception as e:
            logger.error(f"Slack alert failed: {e}")
            return False

    def send_alert(self, message: str, level: str = "WARNING") -> None:
        """Send alert via all configured channels."""
        full_message = f"[VPS WATCHDOG - {level}]\n{message}"
        logger.warning(full_message)

        # Try all alert channels
        self.send_telegram_alert(full_message)
        self.send_slack_alert(full_message)

    def handle_failure(self) -> None:
        """Handle consecutive failures."""
        self.consecutive_failures += 1
        logger.warning(
            f"Health check failed ({self.consecutive_failures}/{self.failure_threshold})"
        )

        if self.consecutive_failures >= self.failure_threshold and not self.alert_sent:
            # Check for open positions
            pos_result = self.check_positions()
            positions = pos_result.get("positions", [])

            message = (
                f"VPS UNRESPONSIVE!\n"
                f"URL: {self.vps_url}\n"
                f"Last success: {self.last_success or 'never'}\n"
                f"Consecutive failures: {self.consecutive_failures}\n"
            )

            if positions:
                message += f"\nOPEN POSITIONS DETECTED ({len(positions)}):\n"
                for pos in positions[:5]:  # Show first 5
                    message += f"  - {pos.get('symbol', '?')} {pos.get('side', '?')} x{pos.get('qty', '?')}\n"
                message += "\nMANUAL INTERVENTION MAY BE REQUIRED!"
            else:
                message += "\nNo open positions detected."

            self.send_alert(message, level="CRITICAL")
            self.alert_sent = True

    def handle_recovery(self) -> None:
        """Handle recovery after failures."""
        if self.consecutive_failures > 0:
            downtime = ""
            if self.last_success:
                downtime = f" (downtime: {datetime.now() - self.last_success})"
            logger.info(f"VPS recovered after {self.consecutive_failures} failures{downtime}")

            if self.alert_sent:
                self.send_alert(
                    f"VPS RECOVERED\nURL: {self.vps_url}\nPrevious failures: {self.consecutive_failures}",
                    level="INFO",
                )

        self.consecutive_failures = 0
        self.last_success = datetime.now()
        self.alert_sent = False

    def run(self) -> None:
        """Main watchdog loop."""
        logger.info(f"Starting VPS watchdog for {self.vps_url}")
        logger.info(f"Check interval: {self.interval}s, Failure threshold: {self.failure_threshold}")

        alert_channels = []
        if self.telegram_token:
            alert_channels.append("Telegram")
        if self.slack_webhook:
            alert_channels.append("Slack")
        if alert_channels:
            logger.info(f"Alert channels: {', '.join(alert_channels)}")
        else:
            logger.warning("No alert channels configured (set WATCHDOG_* env vars)")

        while True:
            try:
                result = self.check_health()

                if result["ok"]:
                    self.handle_recovery()
                    logger.debug(f"Health OK: {result.get('data', {})}")
                else:
                    logger.warning(f"Health check failed: {result.get('error')}")
                    self.handle_failure()

            except KeyboardInterrupt:
                logger.info("Watchdog stopped by user")
                break
            except Exception as e:
                logger.error(f"Watchdog error: {e}")
                self.handle_failure()

            time.sleep(self.interval)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="VPS Watchdog - Monitor trading platform health"
    )
    parser.add_argument(
        "--vps-url",
        required=True,
        help="Base URL of the VPS (e.g., https://your-vps.com)",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=30,
        help="Check interval in seconds (default: 30)",
    )
    parser.add_argument(
        "--failure-threshold",
        type=int,
        default=3,
        help="Consecutive failures before alerting (default: 3)",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=10,
        help="HTTP timeout in seconds (default: 10)",
    )

    args = parser.parse_args()

    watchdog = VPSWatchdog(
        vps_url=args.vps_url,
        interval=args.interval,
        failure_threshold=args.failure_threshold,
        timeout=args.timeout,
    )
    watchdog.run()


if __name__ == "__main__":
    main()
