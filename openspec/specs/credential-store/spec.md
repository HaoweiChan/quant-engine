## Purpose

Manage broker account credentials with zero secrets on disk. All API keys, secrets, and passwords are stored exclusively in Google Secret Manager (GSM) and accessed at runtime. Non-secret account metadata is persisted in SQLite.

## Requirements

### Requirement: SecretManager write capabilities
The existing `SecretManager` SHALL be extended with methods to create and update secrets in Google Secret Manager, enabling the dashboard UI to save broker credentials directly to GSM with zero secrets on disk.

```python
class SecretManager:
    # ... existing get/get_batch/get_group methods ...

    def set(self, name: str, value: str) -> None: ...
    def delete(self, name: str) -> None: ...
    def exists(self, name: str) -> bool: ...
```

#### Scenario: Create new secret
- **WHEN** `set("BINANCE_API_KEY", "abc123")` is called and the secret does not exist in GSM
- **THEN** it SHALL create a new secret in `projects/tx-collar-trader/secrets/BINANCE_API_KEY` and add the value as version 1

#### Scenario: Update existing secret
- **WHEN** `set("SINOPAC_API_KEY", "new_value")` is called and the secret already exists
- **THEN** it SHALL add a new version to the existing secret with the updated value

#### Scenario: Delete secret
- **WHEN** `delete("BINANCE_API_KEY")` is called
- **THEN** it SHALL delete the secret from GSM and remove it from the in-memory cache

#### Scenario: Check secret existence
- **WHEN** `exists("SINOPAC_API_KEY")` is called
- **THEN** it SHALL return `True` if the secret exists in GSM, `False` otherwise

#### Scenario: Cache invalidation on set
- **WHEN** `set(name, value)` is called
- **THEN** the in-memory cache for that secret SHALL be updated to the new value

#### Scenario: GSM write permission denied
- **WHEN** the service account lacks `secretmanager.secrets.create` or `secretmanager.versions.add` permission
- **THEN** the system SHALL raise a `SecretAccessError` with the required IAM role in the message

### Requirement: Secret naming convention for broker accounts
The system SHALL follow a naming convention for broker account secrets in GSM: `{ACCOUNT_ID}_{FIELD}` where ACCOUNT_ID is uppercased with hyphens replaced by underscores, and FIELD is one of `API_KEY`, `API_SECRET`, `PASSWORD`.

Examples:
- Account `sinopac-main` → secrets: `SINOPAC_MAIN_API_KEY`, `SINOPAC_MAIN_API_SECRET`
- Account `binance-test` → secrets: `BINANCE_TEST_API_KEY`, `BINANCE_TEST_API_SECRET`, `BINANCE_TEST_PASSWORD`

#### Scenario: Save credentials from dashboard
- **WHEN** the user enters API Key "abc" and Secret "xyz" for account "sinopac-main" in the dashboard modal and clicks Save
- **THEN** the system SHALL call `SecretManager.set("SINOPAC_MAIN_API_KEY", "abc")` and `SecretManager.set("SINOPAC_MAIN_API_SECRET", "xyz")`

#### Scenario: Load credentials for gateway connection
- **WHEN** `GatewayRegistry` needs credentials for account "sinopac-main"
- **THEN** it SHALL call `SecretManager.get("SINOPAC_MAIN_API_KEY")` and `SecretManager.get("SINOPAC_MAIN_API_SECRET")`

#### Scenario: Delete account removes secrets
- **WHEN** account "binance-test" is deleted from the dashboard
- **THEN** the system SHALL call `SecretManager.delete()` for all secrets matching the `BINANCE_TEST_*` pattern

### Requirement: Secrets config auto-registration
When a new account is created via the dashboard, the system SHALL update `config/secrets.toml` to register the new secret group, maintaining consistency with the existing name resolution system.

#### Scenario: New account registers secret group
- **WHEN** account "binance-test" is created
- **THEN** `config/secrets.toml` SHALL be updated with:
  ```toml
  [binance-test]
  api_key = "BINANCE_TEST_API_KEY"
  api_secret = "BINANCE_TEST_API_SECRET"
  password = "BINANCE_TEST_PASSWORD"
  ```

#### Scenario: Account deletion removes secret group
- **WHEN** account "binance-test" is deleted
- **THEN** the `[binance-test]` section SHALL be removed from `config/secrets.toml`

### Requirement: AccountConfig persistence in SQLite (non-secret data only)
The system SHALL store non-secret account configurations in the `accounts` table of `trading.db`. This includes: id, broker type, display name, gateway class, mode flags, guards, and strategy bindings. NO credentials SHALL be stored in SQLite.

```python
@dataclass
class AccountConfig:
    id: str                    # unique account ID (e.g., "sinopac-main")
    broker: str                # broker type (e.g., "sinopac", "binance", "schwab")
    display_name: str          # human-readable name
    gateway_class: str         # fully qualified class path
    sandbox_mode: bool         # if True, use sandbox/paper endpoints
    demo_trading: bool         # if True, simulate orders without execution
    guards: dict[str, float]   # risk guards (max_drawdown_pct, max_margin_pct, max_daily_loss)
    strategies: list[dict]     # bound strategies [{slug, symbol}]
```

#### Scenario: Save account config from dashboard
- **WHEN** the user fills in the account detail modal and clicks "Save"
- **THEN** non-secret fields SHALL be persisted to `trading.db` and credentials SHALL be written to GSM

#### Scenario: Load all accounts on startup
- **WHEN** the dashboard starts
- **THEN** all `AccountConfig` entries SHALL be loaded from `trading.db` and credentials resolved from GSM

#### Scenario: No secrets in SQLite
- **WHEN** the `accounts` table is inspected
- **THEN** it SHALL NOT contain any API keys, secrets, or passwords — only metadata
