## Context

The quant-engine currently reads Sinopac broker credentials from environment variables (`SINOPAC_API_KEY`, `SINOPAC_SECRET_KEY`) in `quant_engine/data/connector.py`. This means secrets exist on disk (`.env` files, shell profiles) or in process environment. As the platform grows to support Schwab, Binance, and MLflow tracking, credential management needs a secure, centralized approach.

All secrets are stored in Google Secret Manager under GCP project `tx-collar-trader`. The platform must fetch them at runtime with no fallback to env vars or disk.

## Goals / Non-Goals

**Goals:**
- Single `SecretManager` class that all modules use to retrieve credentials
- Secrets fetched from GSM at runtime, cached in memory only
- TOML-based mapping from logical names to GSM secret IDs
- Clean error messages when secrets are missing or inaccessible
- Operator-facing manifest of all required secrets

**Non-Goals:**
- Secret rotation / auto-refresh (secrets are cached for process lifetime)
- Env var fallback for local development (operator must have GSM access)
- Encryption at rest beyond what GSM provides
- Secret write operations (read-only client)

## Decisions

### D1: google-cloud-secret-manager SDK (not REST or gcloud CLI)

Use the official `google-cloud-secret-manager` Python library. It handles authentication via Application Default Credentials (ADC), supports `grpc`, and is well-typed.

**Alternatives considered:**
- Raw REST API — more boilerplate, no retry/auth built in
- `gcloud secrets` subprocess — fragile, slower, not testable

### D2: Single `SecretManager` singleton per process

A module-level factory `get_secret_manager()` returns a cached instance. All modules import and call this rather than constructing their own clients. This ensures the in-memory cache is shared.

```
quant_engine/secrets/
├── __init__.py
├── manager.py      # SecretManager class + get_secret_manager()
├── config.py       # load_secret_names() from TOML
└── errors.py       # SecretNotFoundError, SecretAccessError
```

### D3: TOML config for secret name mapping

`quant_engine/config/secrets.toml` maps logical groups to GSM secret IDs:

```toml
[sinopac]
api_key = "SHIOAJI_API_KEY"
secret_key = "SHIOAJI_SECRET_KEY"
```

Modules request by group: `sm.get_group("sinopac")` → `{"api_key": "...", "secret_key": "..."}`.

### D4: Inject credentials into SinopacConnector

Change `SinopacConnector.login()` to accept `api_key` and `secret_key` as parameters. The caller (pipeline runner or CLI) fetches from `SecretManager` and passes them in. This keeps `SinopacConnector` testable without GSM access.

```
Before:  connector.login()              # reads os.environ internally
After:   connector.login(api_key, sk)   # caller provides credentials
```

### D5: Authentication via Application Default Credentials (ADC)

No explicit service account key files. The operator authenticates via:
- **Local dev**: `gcloud auth application-default login`
- **GCE/Cloud Run**: automatic metadata server
- **CI**: workload identity federation or `GOOGLE_APPLICATION_CREDENTIALS`

This means the machine needs GCP auth configured, but no secret files on disk.

## Risks / Trade-offs

**[Risk] GSM unavailable blocks startup** → The system cannot start without secrets. This is intentional — trading with wrong credentials is worse than not trading.

**[Risk] ADC not configured** → Clear error message at startup: "Run `gcloud auth application-default login` or configure workload identity".

**[Risk] Cold-start latency from GSM fetch** → First call adds ~200-500ms. Acceptable for a trading engine that runs for hours. Cached after first fetch.

**[Trade-off] No env var fallback** → Operator decision. Simplifies the security model at the cost of requiring GCP auth even for local dev.

**[Trade-off] Process-lifetime cache** → If a secret is rotated in GSM, the process must be restarted. Acceptable for Phase 1; auto-refresh can be added later.
