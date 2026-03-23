## MODIFIED Requirements

### Requirement: Save optimized params as TOML config
The dashboard SHALL provide a "Save as Default Params" button in the Optimizer results view that writes the best parameter set to a TOML config file at `src/strategies/configs/<strategy_slug>.toml`.

```python
def save_strategy_params(strategy_name: str, params: dict[str, Any]) -> Path:
    """Write params dict as TOML to src/strategies/configs/<name>.toml."""
    ...

def load_strategy_params(strategy_name: str) -> dict[str, Any] | None:
    """Load params from TOML config if it exists, else return None."""
    ...
```

#### Scenario: Save writes per-strategy TOML file
- **WHEN** the user clicks "Save as Default Params" for `atr_mean_reversion`
- **THEN** a file `src/strategies/configs/atr_mean_reversion.toml` SHALL be written containing the best params under a `[params]` table

#### Scenario: Save overwrites existing config
- **WHEN** a TOML config already exists for the strategy
- **THEN** the save SHALL overwrite it with the new params

#### Scenario: Load returns params dict
- **WHEN** `load_strategy_params("atr_mean_reversion")` is called and the config file exists
- **THEN** it SHALL return a `dict[str, Any]` of the param values

#### Scenario: Load returns None when no config
- **WHEN** `load_strategy_params("nonexistent")` is called
- **THEN** it SHALL return `None`

### Requirement: Per-strategy config files replace default.toml
The `configs/default.toml` file SHALL be replaced by per-strategy files using the convention `configs/<slug>.toml`. The pyramid strategy config SHALL be stored in `configs/pyramid.toml`.

#### Scenario: Pyramid config in its own file
- **WHEN** `load_strategy_params("pyramid")` is called
- **THEN** it SHALL read from `src/strategies/configs/pyramid.toml`

#### Scenario: Legacy default.toml is removed
- **WHEN** the migration is complete
- **THEN** `src/strategies/configs/default.toml` SHALL NOT exist
