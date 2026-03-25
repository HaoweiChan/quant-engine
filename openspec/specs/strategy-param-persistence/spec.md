## Purpose

Persist optimized strategy parameters as TOML files under `src/strategies/configs/`, with load/save helpers for the dashboard Optimizer and other callers.

## Requirements

### Requirement: Save optimized params as TOML config
The dashboard SHALL provide a "Save as Default Params" button in the Optimizer results view that writes the best parameter set to the parameter registry database via `ParamRegistry.save_run()` and activates the best candidate. The existing `save_strategy_params()` function SHALL delegate to `ParamRegistry` for the primary write and additionally write a TOML file at `src/strategies/configs/<strategy_slug>.toml` for backward compatibility. The `save_backtest_run()` and `save_run()` methods on `ParamRegistry` SHALL accept two additional optional keyword arguments: `strategy_hash: str | None = None` and `strategy_code: str | None = None`. Both values SHALL be persisted to the corresponding columns in `param_runs`. If not provided, they default to `NULL`.

```python
def save_strategy_params(
    name: str,
    params: dict[str, Any],
    metadata: dict[str, Any] | None = None,
) -> Path:
    """Write params to both the registry DB and a TOML file (backward compat)."""
    ...

def load_strategy_params(name: str) -> dict[str, Any] | None:
    """Load active params from registry DB, falling back to TOML if no DB entry."""
    ...

def save_backtest_run(
    self,
    strategy: str,
    params: dict,
    metrics: dict,
    source: str = "mcp",
    strategy_hash: str | None = None,
    strategy_code: str | None = None,
) -> int: ...

def save_run(
    self,
    strategy: str,
    objective: str,
    params: dict,
    metrics: dict,
    trials: list[dict],
    symbol: str = "SYNTHETIC",
    tag: str | None = None,
    notes: str | None = None,
    strategy_hash: str | None = None,
    strategy_code: str | None = None,
) -> int: ...
```

#### Scenario: Save writes to registry and TOML
- **WHEN** the user clicks "Save as Default Params" for `atr_mean_reversion`
- **THEN** the params SHALL be saved as an active candidate in `param_registry.db`
- **AND** a TOML file `src/strategies/configs/atr_mean_reversion.toml` SHALL also be written for backward compatibility

#### Scenario: Save with hash stores hash and code
- **WHEN** `save_backtest_run()` is called with `strategy_hash="abc123"` and `strategy_code="<source>"`
- **THEN** `param_runs.strategy_hash` SHALL contain `"abc123"`
- **AND** `param_runs.strategy_code` SHALL contain the full source text

#### Scenario: Save without hash stores NULL
- **WHEN** `save_backtest_run()` is called without `strategy_hash` or `strategy_code`
- **THEN** `param_runs.strategy_hash` and `param_runs.strategy_code` SHALL be `NULL`

#### Scenario: Load reads from registry first
- **WHEN** `load_strategy_params("atr_mean_reversion")` is called
- **THEN** it SHALL first query `ParamRegistry.get_active("atr_mean_reversion")`
- **AND** if no active candidate exists, it SHALL fall back to reading the TOML file
- **AND** if neither exists, it SHALL return `None`

#### Scenario: Save overwrites existing config
- **WHEN** a TOML config already exists for the strategy
- **THEN** the save SHALL overwrite the TOML and activate a new candidate in the registry (previous candidate deactivated)

#### Scenario: Load returns None when no config
- **WHEN** `load_strategy_params("nonexistent")` is called and neither DB entry nor TOML file exists
- **THEN** it SHALL return `None`

#### Scenario: TOML format is human-readable
- **WHEN** the TOML config file is opened in a text editor
- **THEN** it SHALL contain a `[params]` section with one key-value pair per parameter, with inline comments showing the optimization objective and IS metric value

### Requirement: Per-strategy config files replace default.toml
The `configs/default.toml` file SHALL be replaced by per-strategy files using the convention `configs/<slug>.toml`. The pyramid strategy config SHALL be stored in `configs/pyramid.toml`.

#### Scenario: Pyramid config in its own file
- **WHEN** `load_strategy_params("pyramid")` is called
- **THEN** it SHALL read from `src/strategies/configs/pyramid.toml`

#### Scenario: Legacy default.toml is removed
- **WHEN** the migration is complete
- **THEN** `src/strategies/configs/default.toml` SHALL NOT exist

### Requirement: param_runs schema includes strategy hash columns
The `param_runs` table in `param_registry.db` SHALL include `strategy_hash TEXT` and `strategy_code TEXT` columns. A backward-compatible migration SHALL add these columns to existing databases. Fresh databases SHALL include them in the `CREATE TABLE` statement.

#### Scenario: Migration adds columns to existing DB
- **WHEN** `ParamRegistry` connects to an existing database that lacks `strategy_hash`
- **THEN** it SHALL execute `ALTER TABLE param_runs ADD COLUMN strategy_hash TEXT` and `ALTER TABLE param_runs ADD COLUMN strategy_code TEXT`
- **AND** existing rows SHALL have `NULL` in both columns

#### Scenario: Fresh DB includes columns in schema
- **WHEN** a new `param_registry.db` is created from scratch
- **THEN** the `CREATE TABLE param_runs` statement SHALL include `strategy_hash TEXT` and `strategy_code TEXT` columns

#### Scenario: Migration is idempotent
- **WHEN** the migration method is called on a database that already has both columns
- **THEN** no SQL error SHALL occur and the schema SHALL remain unchanged

### Requirement: get_active_detail and get_run_history return hash metadata
`ParamRegistry.get_active_detail()` SHALL include `strategy_hash` in its return dict. `ParamRegistry.get_run_history()` SHALL include `strategy_hash` in each run entry. Both methods SHALL handle `NULL` values gracefully by returning `None` for those fields.

#### Scenario: get_active_detail includes hash
- **WHEN** `get_active_detail("pyramid")` is called and the active candidate has a non-NULL hash
- **THEN** the return dict SHALL include `"strategy_hash": "<hash_value>"`

#### Scenario: get_active_detail hash is None for legacy run
- **WHEN** `get_active_detail("pyramid")` is called and the active candidate's run has `strategy_hash IS NULL`
- **THEN** the return dict SHALL include `"strategy_hash": None`

#### Scenario: get_run_history includes hash per entry
- **WHEN** `get_run_history("pyramid")` is called
- **THEN** each entry dict SHALL include a `"strategy_hash"` key (value may be `None` for legacy rows)

### Requirement: deactivate_stale_candidates method
`ParamRegistry` SHALL expose a `deactivate_stale_candidates(strategy: str, current_hash: str) -> int` method that sets `is_active = 0` on `param_candidates` rows linked to `param_runs` with `strategy_hash != current_hash` (excluding NULL rows). It SHALL return the count of deactivated rows.

#### Scenario: Deactivates mismatched hash candidates
- **WHEN** `deactivate_stale_candidates("pyramid", "newhash")` is called and an active candidate is linked to a run with `strategy_hash="oldhash"`
- **THEN** that candidate's `is_active` SHALL be set to `0`
- **AND** the method SHALL return `1`

#### Scenario: Skips candidates with matching hash
- **WHEN** `deactivate_stale_candidates("pyramid", "currenthash")` is called and the active candidate's run has `strategy_hash="currenthash"`
- **THEN** that candidate SHALL remain active
- **AND** the method SHALL return `0`

#### Scenario: Skips NULL hash rows
- **WHEN** `deactivate_stale_candidates("pyramid", "newhash")` is called and the active candidate's run has `strategy_hash IS NULL`
- **THEN** that candidate SHALL NOT be deactivated
- **AND** the method SHALL return `0`
