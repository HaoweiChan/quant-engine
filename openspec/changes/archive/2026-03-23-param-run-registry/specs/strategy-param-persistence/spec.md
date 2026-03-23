## MODIFIED Requirements

### Requirement: Save optimized params as TOML config
The dashboard SHALL provide a "Save as Default Params" button in the Optimizer results view that writes the best parameter set to the parameter registry database via `ParamRegistry.save_run()` and activates the best candidate. The existing `save_strategy_params()` function SHALL delegate to `ParamRegistry` for the primary write and additionally write a TOML file at `src/strategies/configs/<strategy_slug>.toml` for backward compatibility.

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
```

#### Scenario: Save writes to registry and TOML
- **WHEN** the user clicks "Save as Default Params" for `atr_mean_reversion`
- **THEN** the params SHALL be saved as an active candidate in `param_registry.db`
- **AND** a TOML file `src/strategies/configs/atr_mean_reversion.toml` SHALL also be written for backward compatibility

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
