"""Google Secret Manager client with in-memory caching."""
from __future__ import annotations

from typing import Any

import structlog
from google.api_core.exceptions import NotFound, PermissionDenied
from google.cloud.secretmanager import SecretManagerServiceClient

from src.secrets.config import load_secret_names
from src.secrets.errors import SecretAccessError, SecretNotFoundError

logger = structlog.get_logger(__name__)

_singleton: SecretManager | None = None


class SecretManager:
    """Fetches secrets from GSM with process-lifetime caching."""

    def __init__(self, project_id: str = "tx-collar-trader") -> None:
        self._project_id = project_id
        self._client: SecretManagerServiceClient = SecretManagerServiceClient()
        self._cache: dict[str, str] = {}
        self._secret_names: dict[str, dict[str, str]] | None = None

    @property
    def project_id(self) -> str:
        return self._project_id

    def get(self, name: str, version: str = "latest") -> str:
        """Fetch a single secret by GSM secret ID. Cached after first call."""
        cache_key = f"{name}:{version}"
        if cache_key in self._cache:
            return self._cache[cache_key]
        resource = f"projects/{self._project_id}/secrets/{name}/versions/{version}"
        try:
            response: Any = self._client.access_secret_version(name=resource)
            value: str = str(response.payload.data.decode("utf-8"))
        except NotFound:
            raise SecretNotFoundError(name, self._project_id) from None
        except PermissionDenied:
            raise SecretAccessError(
                name, self._project_id, "permission denied"
            ) from None
        except Exception as exc:
            raise SecretAccessError(
                name, self._project_id, str(exc)
            ) from exc
        self._cache[cache_key] = value
        logger.info("secret_fetched", name=name)
        return value

    def get_batch(self, names: list[str]) -> dict[str, str]:
        """Fetch multiple secrets by GSM secret IDs."""
        return {name: self.get(name) for name in names}

    def get_group(self, group: str) -> dict[str, str]:
        """Resolve logical names from secrets.toml and fetch all secrets in the group."""
        if self._secret_names is None:
            self._secret_names = load_secret_names()
        if group not in self._secret_names:
            raise KeyError(f"Secret group '{group}' not found in secrets.toml")
        mapping = self._secret_names[group]
        return {logical: self.get(gsm_id) for logical, gsm_id in mapping.items()}


def get_secret_manager(project_id: str = "tx-collar-trader") -> SecretManager:
    """Return a process-wide singleton SecretManager."""
    global _singleton  # noqa: PLW0603
    if _singleton is None:
        _singleton = SecretManager(project_id=project_id)
    return _singleton
