"""Custom exceptions for secret management."""
from __future__ import annotations


class SecretNotFoundError(Exception):
    """Raised when a secret does not exist in Google Secret Manager."""

    def __init__(self, name: str, project_id: str) -> None:
        self.name = name
        self.project_id = project_id
        super().__init__(
            f"Secret '{name}' not found in project '{project_id}'. "
            f"Create it with: gcloud secrets create {name} --project={project_id}"
        )


class SecretAccessError(Exception):
    """Raised when access to a secret is denied or GSM is unreachable."""

    def __init__(self, name: str, project_id: str, detail: str) -> None:
        self.name = name
        self.project_id = project_id
        self.detail = detail
        super().__init__(
            f"Cannot access secret '{name}' in project '{project_id}': {detail}. "
            f"Ensure the service account has roles/secretmanager.secretAccessor "
            f"or run: gcloud auth application-default login"
        )
