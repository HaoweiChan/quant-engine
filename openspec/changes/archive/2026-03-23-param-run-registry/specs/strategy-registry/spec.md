## MODIFIED Requirements

### Requirement: Active params with TOML overrides
The registry SHALL expose `get_active_params(slug: str) -> dict[str, Any]` that returns the effective parameter values. It SHALL first check the `ParamRegistry` for an active candidate, then fall back to TOML overrides from `configs/<slug>.toml`, and finally fall back to `PARAM_SCHEMA` defaults.

#### Scenario: Active candidate in registry DB
- **WHEN** `get_active_params("atr_mean_reversion")` is called and an active candidate exists in `param_registry.db`
- **THEN** it SHALL return the candidate's params merged over `PARAM_SCHEMA` defaults (DB params take precedence)

#### Scenario: No DB candidate, TOML override exists
- **WHEN** `get_active_params("atr_mean_reversion")` is called and no active candidate exists in DB but `configs/atr_mean_reversion.toml` exists
- **THEN** it SHALL return the TOML overrides merged over `PARAM_SCHEMA` defaults (same behavior as before)

#### Scenario: No DB candidate, no TOML override
- **WHEN** `get_active_params("atr_mean_reversion")` is called and neither DB entry nor TOML file exists
- **THEN** it SHALL return the `"default"` value from each entry in `PARAM_SCHEMA`

#### Scenario: DB read failure falls back gracefully
- **WHEN** `get_active_params()` is called and the `param_registry.db` file is corrupted or unreadable
- **THEN** it SHALL log a warning and fall back to the TOML → PARAM_SCHEMA default chain without raising an exception
