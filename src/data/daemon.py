"""Standalone TAIFEX data ingestion daemon.

Subscribes to shioaji tick feeds for TX, MTX, TMF and builds 1-minute OHLCV
bars via LiveMinuteBarStore. Runs independently of the FastAPI backend.
"""
from __future__ import annotations

import json
import signal
import threading
import time
from datetime import datetime, time as dt_time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import structlog

from src.broker_gateway.live_bar_store import LiveMinuteBarStore
from src.data.contracts import CONTRACTS
from src.data.session_utils import DAY_OPEN, NIGHT_OPEN, is_trading

logger = structlog.get_logger(__name__)

TAIPEI_TZ = ZoneInfo("Asia/Taipei")
HEARTBEAT_PATH = Path("/tmp/taifex-data-daemon.heartbeat")
HEARTBEAT_INTERVAL_SECS = 60

# Note: routing is done per-contract at subscribe time via self._code_to_symbol,
# not by prefix. Prefix-routing collapses R1/R2 into the same db_symbol because
# both share the same shioaji_group (e.g. "TXF").


class SessionScheduler:
    """Determines when TAIFEX trading sessions are active."""

    def is_trading_now(self) -> bool:
        return is_trading(datetime.now(TAIPEI_TZ))

    def is_weekend(self) -> bool:
        now = datetime.now(TAIPEI_TZ)
        wd = now.weekday()
        t = now.time()
        if wd == 5 and t >= dt_time(5, 0):
            return True
        if wd == 6:
            return True
        return False

    def next_session_open(self) -> datetime:
        now = datetime.now(TAIPEI_TZ)
        t = now.time()
        today = now.date()

        if t < DAY_OPEN:
            candidate = datetime.combine(today, DAY_OPEN, tzinfo=TAIPEI_TZ)
            if candidate > now:
                return candidate
        if t < NIGHT_OPEN:
            candidate = datetime.combine(today, NIGHT_OPEN, tzinfo=TAIPEI_TZ)
            if candidate > now:
                return candidate

        tomorrow = today + timedelta(days=1)
        while tomorrow.weekday() >= 5:
            tomorrow += timedelta(days=1)
        return datetime.combine(tomorrow, dt_time(0, 0), tzinfo=TAIPEI_TZ)

    def seconds_until_next_session(self) -> float:
        now = datetime.now(TAIPEI_TZ)
        return max(0.0, (self.next_session_open() - now).total_seconds())


class DataDaemon:
    """Standalone tick-to-bar ingestion daemon for TAIFEX futures."""

    def __init__(self, db_path: Path | None = None) -> None:
        self._scheduler = SessionScheduler()
        self._bar_store = LiveMinuteBarStore(db_path=db_path)
        self._api: Any = None
        self._running = False
        self._shutdown_event = threading.Event()
        self._last_tick_ts: datetime | None = None
        self._tick_count = 0
        # Resolved-contract-code → db_symbol. Rebuilt on every _subscribe()
        # because contract codes change after each TAIFEX settlement.
        self._code_to_symbol: dict[str, str] = {}

    def start(self, api_key: str, secret_key: str, simulation: bool = False) -> None:
        """Start the daemon: login, subscribe, and run the main loop."""
        self._running = True
        self._api_key = api_key
        self._api_secret = secret_key
        self._simulation = simulation
        self._install_signal_handlers()

        logger.info("daemon_starting", symbols=[c.db_symbol for c in CONTRACTS])
        self._login(api_key, secret_key, simulation)

        heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop, daemon=True, name="heartbeat",
        )
        heartbeat_thread.start()

        try:
            self._main_loop()
        except KeyboardInterrupt:
            pass
        finally:
            self._shutdown()

    def _login(self, api_key: str, secret_key: str, simulation: bool) -> None:
        try:
            import shioaji as sj
        except ImportError as exc:
            raise ImportError(
                "shioaji is required. Install with: uv sync --extra taifex"
            ) from exc

        self._api = sj.Shioaji(simulation=simulation)
        self._api.login(api_key=api_key, secret_key=secret_key)
        logger.info("daemon_shioaji_login_ok", simulation=simulation)

    def _relogin_and_subscribe(self) -> None:
        """Logout the old session, re-login, and subscribe fresh."""
        if self._api:
            try:
                self._api.logout()
            except Exception:
                pass
        self._login(self._api_key, self._api_secret, self._simulation)
        self._subscribe()

    def _subscribe(self) -> None:
        """Subscribe to tick feeds for all configured contracts.

        Resolves each CONTRACTS entry's shioaji_path (e.g. "Futures.TXF.TXFR1")
        to its actual contract object and records contract.code → db_symbol so
        ticks route by exact contract code (R1 vs R2) rather than by prefix.
        """
        import shioaji as sj

        def _on_tick(exchange: Any, tick: Any) -> None:
            code = getattr(tick, "code", "")
            symbol = self._code_to_symbol.get(code)
            if symbol is None:
                return  # not a subscribed contract
            price = float(getattr(tick, "close", 0))
            volume = int(getattr(tick, "volume", 0))
            if price <= 0:
                return

            raw_ts = getattr(tick, "datetime", None)
            if isinstance(raw_ts, datetime):
                tick_ts = raw_ts if raw_ts.tzinfo else raw_ts.replace(tzinfo=TAIPEI_TZ)
            else:
                tick_ts = datetime.now(TAIPEI_TZ)

            try:
                self._bar_store.ingest_tick(symbol, price, volume, tick_ts)
                self._last_tick_ts = tick_ts
                self._tick_count += 1
            except Exception as exc:
                logger.debug("daemon_tick_error", symbol=symbol, error=str(exc))

        try:
            self._api.quote.set_on_tick_fop_v1_callback(_on_tick)
        except Exception as exc:
            logger.warning("daemon_tick_callback_failed", error=str(exc))
            return

        # shioaji fetches contracts asynchronously after login
        time.sleep(2)

        # Rebuild the code map from scratch — contract codes change after settlement.
        self._code_to_symbol.clear()

        for contract_def in CONTRACTS:
            try:
                obj = self._api.Contracts
                for part in contract_def.shioaji_path.split("."):
                    obj = getattr(obj, part)
                actual_code = getattr(obj, "code", None)
                if not actual_code:
                    logger.warning(
                        "daemon_resolve_failed",
                        symbol=contract_def.db_symbol,
                        path=contract_def.shioaji_path,
                    )
                    continue
                self._api.quote.subscribe(
                    obj,
                    quote_type=sj.constant.QuoteType.Tick,
                    version=sj.constant.QuoteVersion.v1,
                )
                self._code_to_symbol[actual_code] = contract_def.db_symbol
                logger.info(
                    "daemon_subscribed",
                    symbol=contract_def.db_symbol,
                    code=actual_code,
                    path=contract_def.shioaji_path,
                )
            except Exception as exc:
                logger.warning(
                    "daemon_subscribe_failed",
                    symbol=contract_def.db_symbol,
                    error=str(exc),
                )

    def _main_loop(self) -> None:
        subscribed = False
        stale_check_interval = 300  # 5 minutes

        while self._running and not self._shutdown_event.is_set():
            if self._scheduler.is_weekend():
                wait_secs = self._scheduler.seconds_until_next_session()
                logger.info("daemon_weekend_sleep", wake_in_hours=round(wait_secs / 3600, 1))
                self._shutdown_event.wait(timeout=min(wait_secs, 3600))
                continue

            if self._scheduler.is_trading_now():
                if not subscribed:
                    self._relogin_and_subscribe()
                    subscribed = True
                    logger.info("daemon_session_active")
                # Detect stale connection: no ticks for 5min during trading
                elif self._last_tick_ts:
                    now = datetime.now(TAIPEI_TZ)
                    stale_secs = (now - self._last_tick_ts).total_seconds()
                    if stale_secs > stale_check_interval:
                        logger.warning("daemon_tick_stale", stale_secs=stale_secs)
                        subscribed = False  # force re-login on next iteration
                        continue
                self._shutdown_event.wait(timeout=30)
            else:
                if subscribed:
                    logger.info("daemon_session_closed", ticks_received=self._tick_count)
                    subscribed = False
                    self._tick_count = 0

                wait_secs = self._scheduler.seconds_until_next_session()
                logger.info("daemon_inter_session_sleep", wake_in_minutes=round(wait_secs / 60, 1))
                self._shutdown_event.wait(timeout=min(wait_secs, 300))

    def _heartbeat_loop(self) -> None:
        while self._running and not self._shutdown_event.is_set():
            try:
                data = {
                    "status": "running",
                    "last_tick": self._last_tick_ts.isoformat() if self._last_tick_ts else None,
                    "tick_count": self._tick_count,
                    "symbols": [c.db_symbol for c in CONTRACTS],
                    "trading_now": self._scheduler.is_trading_now(),
                    "checked_at": datetime.now(TAIPEI_TZ).isoformat(),
                }
                HEARTBEAT_PATH.write_text(json.dumps(data, indent=2))
            except Exception as exc:
                logger.debug("heartbeat_write_error", error=str(exc))
            self._shutdown_event.wait(timeout=HEARTBEAT_INTERVAL_SECS)

    def _shutdown(self) -> None:
        self._running = False
        self._shutdown_event.set()
        logger.info("daemon_shutting_down")

        if self._api:
            try:
                self._api.logout()
                logger.info("daemon_shioaji_logout_ok")
            except Exception as exc:
                logger.warning("daemon_logout_error", error=str(exc))

        try:
            data = {
                "status": "stopped",
                "stopped_at": datetime.now(TAIPEI_TZ).isoformat(),
                "tick_count": self._tick_count,
            }
            HEARTBEAT_PATH.write_text(json.dumps(data, indent=2))
        except Exception:
            pass

        logger.info("daemon_stopped")

    def _install_signal_handlers(self) -> None:
        def _handler(signum: int, frame: Any) -> None:
            sig_name = signal.Signals(signum).name
            logger.info("daemon_signal_received", signal=sig_name)
            self._running = False
            self._shutdown_event.set()

        signal.signal(signal.SIGTERM, _handler)
        signal.signal(signal.SIGINT, _handler)
