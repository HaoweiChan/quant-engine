## Purpose

Central registry for discovering and exposing strategy metadata (parameter schemas, defaults, optimizer grids) from strategy modules. Acts as the single source of truth for strategy parameter information consumed by the dashboard, MCP server, and optimizer.

## Requirements

### Requirement: Strategy registry auto-discovery
The system SHALL provide a `src/strategies/registry.py` module that lazily discovers all strategy modules in `src/strategies/` by scanning for Python files that export both a `create_*_engine` factory function and a `PARAM_SCHEMA` dict at module level.

#### Scenario: Discovery finds atr_mean_reversion
- **WHEN** the registry is first accessed
- **THEN** it SHALL discover `atr_mean_reversion` with its factory `create_atr_mean_reversion_engine` and its `PARAM_SCHEMA` dict

#### Scenario: Files without PARAM_SCHEMA are skipped
- **WHEN** a `.py` file in `src/strategies/` has a `create_*_engine` function but no `PARAM_SCHEMA`
- **THEN** the registry SHALL skip that file and log a debug message

#### Scenario: Private files are ignored
- **WHEN** a file starts with `_` (e.g., `__init__.py`)
- **THEN** the registry SHALL not attempt to import it

### Requirement: Schema retrieval
The registry SHALL expose a `get_schema(slug: str) -> dict` function that returns the full parameter schema for a strategy, including type, default, min, max, description, and grid values.

```python
def get_schema(slug: str) -> dict[str, Any]:
    """Return the full schema for a strategy.

    Returns dict with keys:
      strategy: str
      parameters: dict[str, ParamInfo]
      meta: dict  (from STRATEGY_META, may be empty)
    """
```

#### Scenario: Schema for known strategy
- **WHEN** `get_schema("atr_mean_reversion")` is called
- **THEN** it SHALL return a dict with `"strategy"`, `"parameters"`, and `"meta"` keys
- **AND** `"parameters"` SHALL contain one entry per key in the module's `PARAM_SCHEMA`

#### Scenario: Schema for unknown strategy
- **WHEN** `get_schema("nonexistent")` is called
- **THEN** it SHALL raise `KeyError`

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

### Requirement: Param grid retrieval
The registry SHALL expose `get_param_grid(slug: str) -> dict[str, dict]` that returns optimizer grid definitions extracted from the `"grid"` key of each `PARAM_SCHEMA` entry.

#### Scenario: Grid values present
- **WHEN** `PARAM_SCHEMA["bb_len"]` contains `"grid": [15, 20, 25]`
- **THEN** `get_param_grid("atr_mean_reversion")["bb_len"]` SHALL include `"default": [15, 20, 25]`

#### Scenario: No grid key
- **WHEN** a `PARAM_SCHEMA` entry has no `"grid"` key
- **THEN** it SHALL be included in the grid with `"default": [<the single default value>]`

### Requirement: List all strategies
The registry SHALL expose `get_all() -> dict[str, StrategyInfo]` returning all discovered strategies.

```python
@dataclass
class StrategyInfo:
    name: str
    slug: str
    module: str
    factory: str
    param_schema: dict[str, dict]
    meta: dict
```

#### Scenario: All discovered strategies returned
- **WHEN** `get_all()` is called
- **THEN** it SHALL return a dict keyed by slug containing `StrategyInfo` for each discovered strategy

### Requirement: Explicit registration for non-standard strategies
The registry SHALL expose `register(slug, module, factory, param_schema, meta)` for strategies that live outside `src/strategies/` (e.g., pyramid in `src/core/`).

#### Scenario: Pyramid registered explicitly
- **WHEN** `register("pyramid", ...)` is called
- **THEN** `get_schema("pyramid")` SHALL return its schema

#### Scenario: Duplicate registration overwrites
- **WHEN** `register()` is called with a slug that already exists
- **THEN** the new registration SHALL replace the previous one

### Requirement: Schema-factory consistency validation
The registry SHALL expose `validate_schemas() -> list[str]` that checks every discovered strategy's `PARAM_SCHEMA` keys match the factory function's keyword argument names (excluding `max_loss`, `lots`, `contract_type`).

#### Scenario: Consistent schema passes
- **WHEN** `PARAM_SCHEMA` keys match factory kwargs
- **THEN** `validate_schemas()` SHALL return an empty list for that strategy

#### Scenario: Extra key in schema detected
- **WHEN** `PARAM_SCHEMA` has a key `"foo"` not in the factory signature
- **THEN** `validate_schemas()` SHALL return a string like `"atr_mean_reversion: PARAM_SCHEMA has 'foo' not in factory signature"`
