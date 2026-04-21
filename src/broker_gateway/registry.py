"""Gateway registry — loads accounts from SQLite, resolves credentials from GSM."""
from __future__ import annotations

import importlib
import threading
from pathlib import Path

import structlog

from src.broker_gateway.abc import BrokerGateway
from src.broker_gateway.account_db import AccountDB
from src.broker_gateway.types import AccountConfig, AccountSnapshot

logger = structlog.get_logger(__name__)

# GSM naming convention: {ACCOUNT_ID}_{FIELD} with hyphens → underscores, uppercased
_CREDENTIAL_FIELDS = ("API_KEY", "API_SECRET", "PASSWORD")


def _gsm_key(account_id: str, field: str) -> str:
    """Convert account ID + field to GSM secret name. e.g. sinopac-main + API_KEY → SINOPAC_MAIN_API_KEY."""
    prefix = account_id.upper().replace("-", "_")
    return f"{prefix}_{field}"


def save_credentials(account_id: str, creds: dict[str, str]) -> None:
    """Write credentials to GSM. Keys: api_key, api_secret, password (optional)."""
    from src.secrets.manager import get_secret_manager
    sm = get_secret_manager()
    field_map = {"api_key": "API_KEY", "api_secret": "API_SECRET", "password": "PASSWORD"}
    for logical, value in creds.items():
        if not value:
            continue
        gsm_field = field_map.get(logical)
        if gsm_field:
            gsm_name = _gsm_key(account_id, gsm_field)
            sm.set(gsm_name, value)
            logger.info("credential_saved_to_gsm", account_id=account_id, field=gsm_field)


def load_credentials(account_id: str) -> dict[str, str]:
    """Load credentials from GSM. Returns dict with api_key, api_secret, password keys."""
    from src.secrets.manager import get_secret_manager
    sm = get_secret_manager()
    result: dict[str, str] = {}
    field_map = {"API_KEY": "api_key", "API_SECRET": "api_secret", "PASSWORD": "password"}
    for gsm_field, logical in field_map.items():
        gsm_name = _gsm_key(account_id, gsm_field)
        try:
            result[logical] = sm.get(gsm_name)
        except Exception:
            pass
    return result


def delete_credentials(account_id: str) -> None:
    """Remove all credentials for an account from GSM."""
    from src.secrets.manager import get_secret_manager
    sm = get_secret_manager()
    for field in _CREDENTIAL_FIELDS:
        gsm_name = _gsm_key(account_id, field)
        try:
            sm.delete(gsm_name)
        except Exception:
            pass


def _import_gateway_class(class_path: str) -> type[BrokerGateway]:
    """Dynamically import a gateway class from a dotted path like 'src.broker_gateway.sinopac.SinopacGateway'."""
    module_path, class_name = class_path.rsplit(".", 1)
    mod = importlib.import_module(module_path)
    cls = getattr(mod, class_name)
    if not (isinstance(cls, type) and issubclass(cls, BrokerGateway)):
        raise TypeError(f"{class_path} is not a BrokerGateway subclass")
    return cls


class GatewayRegistry:
    """Manages broker gateway instances loaded from trading.db + GSM."""

    def __init__(self, db: AccountDB | None = None) -> None:
        self._db = db or AccountDB()
        self._gateways: dict[str, BrokerGateway] = {}
        self._configs: dict[str, AccountConfig] = {}

    def load_all(self) -> None:
        """Load all accounts from DB and instantiate gateways."""
        accounts = self._db.load_all_accounts()
        for config in accounts:
            self._register(config)

    def _register(self, config: AccountConfig) -> None:
        """Instantiate and register a single gateway from config."""
        # Always register the config so it appears in account overview even if gateway fails
        self._configs[config.id] = config
        try:
            cls = _import_gateway_class(config.gateway_class)
            gateway = cls()
            self._gateways[config.id] = gateway
            logger.info("gateway_registered", account_id=config.id, broker=config.broker)
            # Auto-connect in background so we don't block the registry load
            self._bg_connect(config.id, gateway)
        except Exception as exc:
            logger.error("gateway_registration_failed", account_id=config.id, error=str(exc))

    def _bg_connect(self, account_id: str, gateway: BrokerGateway) -> None:
        """Attempt gateway.connect() in a background thread (non-blocking)."""
        config = self._configs.get(account_id)
        simulation = bool(config and config.sandbox_mode)
        def _do_connect() -> None:
            try:
                gateway.connect(account_id=account_id, simulation=simulation)  # type: ignore[call-arg]
                logger.info("gateway_connected", account_id=account_id, simulation=simulation)
            except TypeError:
                try:
                    gateway.connect(account_id=account_id)  # type: ignore[call-arg]
                    logger.info("gateway_connected", account_id=account_id)
                except TypeError:
                    try:
                        gateway.connect()
                        logger.info("gateway_connected", account_id=account_id)
                    except Exception as exc:
                        logger.warning("gateway_connect_failed", account_id=account_id, error=str(exc))
            except Exception as exc:
                logger.warning("gateway_connect_failed", account_id=account_id, error=str(exc))
        threading.Thread(target=_do_connect, daemon=True, name=f"gw-connect-{account_id}").start()

    def hot_reload(self, config: AccountConfig) -> None:
        """Add or replace a single gateway at runtime (called after UI save)."""
        old = self._gateways.pop(config.id, None)
        if old:
            try:
                old.disconnect()
            except Exception:
                pass
        self._register(config)

    def remove(self, account_id: str) -> None:
        """Remove a gateway from the registry."""
        gw = self._gateways.pop(account_id, None)
        self._configs.pop(account_id, None)
        if gw:
            try:
                gw.disconnect()
            except Exception:
                pass

    def get_gateway(self, account_id: str) -> BrokerGateway | None:
        return self._gateways.get(account_id)

    def get_config(self, account_id: str) -> AccountConfig | None:
        return self._configs.get(account_id)

    def get_all_configs(self) -> list[AccountConfig]:
        return list(self._configs.values())

    def get_all_snapshots(self) -> dict[str, AccountSnapshot]:
        """Fetch account snapshots for all registered gateways."""
        return {aid: gw.get_account_snapshot() for aid, gw in self._gateways.items()}

    @property
    def account_ids(self) -> list[str]:
        return list(self._gateways.keys())
