#!/usr/bin/env python3
"""
On-VPS self-watchdog for the trading API.

Polls http://127.0.0.1:8000/api/health every 30s. After N consecutive
failures (default 3 = ~90s of unresponsiveness), it:

  1. Calls `systemctl restart quant-engine-api.service`
  2. Fires a Telegram alert (best effort)

Distinct from scripts/vps-watchdog.py (which runs OFF-host as alert-only).
This one runs on the VPS itself and takes the auto-restart action chosen
by the user policy "alert + auto-restart, no auto-flatten".

Safety guarantees:
- stdlib-only (no extra deps to break under memory pressure)
- never imports the trading code paths
- uses `subprocess.run` with explicit args (no shell=True)
- logs to stdout/stderr -> journald (via systemd unit)

Required env vars (set in scripts/deploy/quant-vps-self-watchdog.service):
  WATCHDOG_TARGET_UNIT      systemd unit to restart (default: quant-engine-api.service)
  WATCHDOG_HEALTH_URL       URL to poll (default: http://127.0.0.1:8000/api/health)
  WATCHDOG_INTERVAL_S       seconds between checks (default: 30)
  WATCHDOG_FAILURE_THRESHOLD consecutive failures before action (default: 3)
  WATCHDOG_HTTP_TIMEOUT_S   per-request timeout (default: 10)
  WATCHDOG_RESTART_COOLDOWN_S minimum gap between auto-restarts (default: 300)

Optional alert env vars:
  WATCHDOG_TELEGRAM_TOKEN
  WATCHDOG_TELEGRAM_CHAT_ID
"""

from __future__ import annotations

import json
import logging
import os
import signal
import subprocess
import sys
import time
from datetime import datetime
from urllib.error import URLError
from urllib.request import Request, urlopen

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("vps_self_watchdog")


def _env_str(name: str, default: str) -> str:
    val = os.getenv(name, default)
    return val.strip() if val else default


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        log.warning("invalid int for %s=%r; using default %d", name, raw, default)
        return default


TARGET_UNIT = _env_str("WATCHDOG_TARGET_UNIT", "quant-engine-api.service")
HEALTH_URL = _env_str("WATCHDOG_HEALTH_URL", "http://127.0.0.1:8000/api/health")
INTERVAL_S = _env_int("WATCHDOG_INTERVAL_S", 30)
FAILURE_THRESHOLD = _env_int("WATCHDOG_FAILURE_THRESHOLD", 3)
HTTP_TIMEOUT_S = _env_int("WATCHDOG_HTTP_TIMEOUT_S", 10)
RESTART_COOLDOWN_S = _env_int("WATCHDOG_RESTART_COOLDOWN_S", 300)

TELEGRAM_TOKEN = os.getenv("WATCHDOG_TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("WATCHDOG_TELEGRAM_CHAT_ID")


def check_health() -> tuple[bool, str]:
    try:
        req = Request(HEALTH_URL, headers={"User-Agent": "quant-vps-self-watchdog/1.0"})
        with urlopen(req, timeout=HTTP_TIMEOUT_S) as response:
            if 200 <= response.status < 300:
                return True, "ok"
            return False, f"http {response.status}"
    except URLError as e:
        return False, f"urlerror: {e.reason}"
    except TimeoutError:
        return False, "timeout"
    except Exception as e:  # noqa: BLE001 - watchdog must not die on unexpected errors
        return False, f"{type(e).__name__}: {e}"


def restart_unit() -> tuple[bool, str]:
    cmd = ["systemctl", "restart", TARGET_UNIT]
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=30, check=False
        )
    except subprocess.TimeoutExpired:
        return False, "systemctl timeout"
    except FileNotFoundError:
        return False, "systemctl not found"
    if result.returncode != 0:
        return False, f"rc={result.returncode} stderr={result.stderr.strip()[:200]}"
    return True, "restarted"


def send_telegram(message: str) -> None:
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        data = json.dumps(
            {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"}
        ).encode()
        req = Request(url, data=data, headers={"Content-Type": "application/json"})
        with urlopen(req, timeout=10):
            pass
    except Exception as e:  # noqa: BLE001
        log.warning("telegram alert failed: %s", e)


def alert(level: str, message: str) -> None:
    body = f"[VPS SELF-WATCHDOG - {level}]\n{message}"
    log.warning(body)
    send_telegram(body)


def main() -> int:
    log.info(
        "starting: target=%s url=%s interval=%ds threshold=%d cooldown=%ds",
        TARGET_UNIT,
        HEALTH_URL,
        INTERVAL_S,
        FAILURE_THRESHOLD,
        RESTART_COOLDOWN_S,
    )

    consecutive_failures = 0
    last_restart_at: float | None = None

    def _on_signal(signum: int, _frame) -> None:
        log.info("signal %d received; exiting", signum)
        sys.exit(0)

    signal.signal(signal.SIGTERM, _on_signal)
    signal.signal(signal.SIGINT, _on_signal)

    while True:
        ok, detail = check_health()
        if ok:
            if consecutive_failures > 0:
                log.info("recovered after %d failures", consecutive_failures)
            consecutive_failures = 0
        else:
            consecutive_failures += 1
            log.warning(
                "health failed (%d/%d): %s",
                consecutive_failures,
                FAILURE_THRESHOLD,
                detail,
            )

            if consecutive_failures >= FAILURE_THRESHOLD:
                now = time.time()
                if last_restart_at is not None and (now - last_restart_at) < RESTART_COOLDOWN_S:
                    elapsed = int(now - last_restart_at)
                    log.warning(
                        "skip restart: cooldown %ds, last restart %ds ago",
                        RESTART_COOLDOWN_S,
                        elapsed,
                    )
                else:
                    alert(
                        "CRITICAL",
                        (
                            f"{TARGET_UNIT} unresponsive at {HEALTH_URL} "
                            f"({consecutive_failures} consecutive failures, last reason: {detail}). "
                            f"Restarting at {datetime.utcnow().isoformat()}Z."
                        ),
                    )
                    restarted, restart_detail = restart_unit()
                    if restarted:
                        log.info("restart command succeeded: %s", restart_detail)
                        last_restart_at = now
                        consecutive_failures = 0
                        time.sleep(15)  # give the lifespan startup a head start before re-polling
                    else:
                        alert("ERROR", f"systemctl restart {TARGET_UNIT} failed: {restart_detail}")

        time.sleep(INTERVAL_S)


if __name__ == "__main__":
    sys.exit(main())
