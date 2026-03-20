## ADDED Requirements

### Requirement: SecretManager interface
The system SHALL provide a `SecretManager` class that retrieves secrets from Google Secret Manager (GCP project `tx-collar-trader`) at runtime. No secrets SHALL ever be stored on disk or in environment variables.

```python
@dataclass
class SecretManager:
    project_id: str = "tx-collar-trader"

    def get(self, name: str, version: str = "latest") -> str: ...
    def get_batch(self, names: list[str]) -> dict[str, str]: ...
```

#### Scenario: Retrieve a single secret
- **WHEN** `SecretManager.get("SHIOAJI_API_KEY")` is called
- **THEN** the system SHALL fetch the secret value from `projects/tx-collar-trader/secrets/SHIOAJI_API_KEY/versions/latest` and return it as a string

#### Scenario: Retrieve a batch of secrets
- **WHEN** `SecretManager.get_batch(["SHIOAJI_API_KEY", "SHIOAJI_SECRET_KEY"])` is called
- **THEN** the system SHALL fetch all requested secrets in parallel and return a `dict[str, str]` mapping each name to its value

#### Scenario: Secret not found
- **WHEN** a secret name does not exist in GSM
- **THEN** the system SHALL raise a `SecretNotFoundError` with the secret name and project ID in the message

#### Scenario: Permission denied
- **WHEN** the service account lacks `secretmanager.versions.access` permission
- **THEN** the system SHALL raise a `SecretAccessError` with actionable guidance (required IAM role)

#### Scenario: GSM unavailable
- **WHEN** the GSM API is unreachable (network error, service outage)
- **THEN** the system SHALL raise a `SecretAccessError` after exhausting retries, without falling back to any other source

### Requirement: Secret name resolution from config
The system SHALL resolve logical secret names (e.g., `sinopac.api_key`) to GSM secret IDs via a TOML config file (`config/secrets.toml`).

```toml
[sinopac]
api_key = "SHIOAJI_API_KEY"
secret_key = "SHIOAJI_SECRET_KEY"
```

#### Scenario: Config-based resolution
- **WHEN** a module requests credentials by logical group (e.g., `sinopac`)
- **THEN** the `SecretManager` SHALL look up the GSM secret IDs from `config/secrets.toml` and fetch them

#### Scenario: Missing config entry
- **WHEN** a logical secret name is not found in `config/secrets.toml`
- **THEN** the system SHALL raise a `KeyError` indicating the missing config entry

### Requirement: Process-lifetime caching
The system SHALL cache fetched secrets in memory for the lifetime of the process to avoid redundant GSM API calls. No secrets SHALL be written to disk, files, or environment variables.

#### Scenario: Repeated access returns cached value
- **WHEN** the same secret is requested multiple times within a process
- **THEN** only the first call SHALL hit the GSM API; subsequent calls SHALL return the cached value

#### Scenario: No disk persistence
- **WHEN** secrets are cached
- **THEN** they SHALL exist only in process memory — no files, no env vars, no temp storage

### Requirement: Secret manifest documentation
The system SHALL maintain a manifest listing all required GSM secrets so operators know what to provision.

#### Scenario: Operator provisions secrets
- **WHEN** deploying the system for the first time
- **THEN** the operator SHALL be able to reference a manifest (in docs or config comments) listing every required secret name, its purpose, and expected format
