## Why

All secrets (broker API keys, future service credentials) are currently read from environment variables, which means they exist on disk or in shell history. The platform needs a centralized, secure secret management layer using Google Secret Manager (GSM) under GCP project `flash-realm-492814`. Secrets must never be stored on the machine — GSM is the single source of truth for all credentials.

## What Changes

- Introduce a `SecretManager` abstraction that fetches secrets from GSM at runtime
- **BREAKING**: Remove environment variable fallback from `SinopacConnector.login()` — all credentials must come from GSM
- Update `SinopacConnector` to receive credentials via `SecretManager` instead of `os.environ`
- Add `google-cloud-secret-manager` dependency
- Update TOML config to reference GSM secret names (not values)
- Provide a manifest of all required GSM secrets so the operator knows what to set

## Capabilities

### New Capabilities

- `secret-manager`: Centralized secret retrieval from Google Secret Manager — typed interface, caching within process lifetime, secret name resolution from config

### Modified Capabilities

- `data-layer`: Credential retrieval changes from env vars to GSM for Sinopac connector initialization

## Impact

- **New package**: `quant_engine/secrets/` with GSM client wrapper
- **Modified**: `quant_engine/data/connector.py` — remove `os.environ` reads, accept credentials from `SecretManager`
- **Modified**: `quant_engine/pipeline/config.py` — add secret name config loading
- **New dependency**: `google-cloud-secret-manager>=2.20`
- **Config**: `config/secrets.toml` mapping logical names to GSM secret IDs
- **Operator action required**: populate GSM secrets in project `flash-realm-492814`
