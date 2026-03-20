## 1. Package Structure & Dependencies

- [x] 1.1 Create `quant_engine/secrets/` package with `__init__.py`, `manager.py`, `config.py`, `errors.py`
- [x] 1.2 Add `google-cloud-secret-manager>=2.20` to `pyproject.toml` dependencies
- [x] 1.3 Add `google.cloud.*` to mypy overrides in `pyproject.toml`
- [x] 1.4 Run `uv sync` to verify dependency resolution

## 2. Error Types

- [x] 2.1 Implement `SecretNotFoundError(name, project_id)` in `errors.py`
- [x] 2.2 Implement `SecretAccessError(name, project_id, detail)` in `errors.py` with IAM guidance message

## 3. Secret Name Config

- [x] 3.1 Create `quant_engine/config/secrets.toml` with `[sinopac]` section mapping logical names to GSM IDs (`SHIOAJI_API_KEY`, `SHIOAJI_SECRET_KEY`)
- [x] 3.2 Implement `load_secret_names(path) -> dict[str, dict[str, str]]` in `secrets/config.py` that parses the TOML file

## 4. SecretManager Core

- [x] 4.1 Implement `SecretManager.__init__(project_id="tx-collar-trader")` that creates the GSM client
- [x] 4.2 Implement `SecretManager.get(name, version="latest") -> str` that fetches a single secret from GSM
- [x] 4.3 Implement `SecretManager.get_batch(names) -> dict[str, str]` that fetches multiple secrets
- [x] 4.4 Implement `SecretManager.get_group(group) -> dict[str, str]` that resolves logical names from TOML and fetches all secrets in the group
- [x] 4.5 Implement in-memory cache — `get()` only calls GSM on first access per secret name
- [x] 4.6 Implement module-level `get_secret_manager()` singleton factory
- [x] 4.7 Map `google.api_core.exceptions.NotFound` to `SecretNotFoundError`
- [x] 4.8 Map `google.api_core.exceptions.PermissionDenied` to `SecretAccessError` with IAM role guidance

## 5. Modify SinopacConnector

- [x] 5.1 Change `SinopacConnector.login()` signature to accept `api_key: str` and `secret_key: str` parameters
- [x] 5.2 Remove all `os.environ.get("SINOPAC_API_KEY")` and `os.environ.get("SINOPAC_SECRET_KEY")` references
- [x] 5.3 Remove `import os` if no longer used
- [x] 5.4 Update `ensure_session()` to re-fetch credentials from `SecretManager` on re-auth

## 6. Pipeline Integration

- [x] 6.1 Update `PipelineRunner` (or caller) to fetch Sinopac credentials from `SecretManager` and pass to `SinopacConnector.login()`

## 7. Secret Manifest

- [x] 7.1 Add comments in `config/secrets.toml` documenting each secret's purpose and expected format
- [x] 7.2 Document the required `gcloud` commands for operators to provision secrets in GSM

## 8. Tests

- [x] 8.1 Test `load_secret_names()` — valid TOML parsing, missing file error, missing group error
- [x] 8.2 Test `SecretManager.get()` — mock GSM client, verify single secret retrieval
- [x] 8.3 Test `SecretManager.get_batch()` — mock GSM client, verify batch retrieval
- [x] 8.4 Test `SecretManager.get_group()` — mock GSM client + TOML config, verify logical name resolution
- [x] 8.5 Test in-memory cache — verify GSM client called only once per secret
- [x] 8.6 Test `SecretNotFoundError` raised when secret does not exist in GSM
- [x] 8.7 Test `SecretAccessError` raised on permission denied
- [x] 8.8 Test `SinopacConnector.login(api_key, secret_key)` accepts explicit credentials
- [x] 8.9 Test `SinopacConnector.login()` without args raises `TypeError` (no more env var fallback)

## 9. Quality Gates

- [x] 9.1 `uv run ruff check quant_engine/secrets/ tests/test_secrets*.py` — zero violations
- [x] 9.2 `uv run mypy quant_engine/secrets/` — zero errors
- [x] 9.3 All tests pass: `uv run pytest tests/test_secrets*.py -v`
