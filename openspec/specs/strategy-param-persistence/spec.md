## Purpose

Persist optimized strategy parameters as TOML files under `src/strategies/configs/`, with load/save helpers for the dashboard Optimizer and other callers.

## Requirements

### Requirement: Save optimized params as TOML config
The dashboard SHALL provide a "Save as Default Params" button in the Optimizer results view that writes the best parameter set to a TOML config file at `src/strategies/configs/<strategy_name>.toml`.

```python
def save_strategy_params(strategy_name: str, params: dict[str, Any]) -> Path:
    """Write params dict as TOML to src/strategies/configs/<name>.toml."""
    ...

def load_strategy_params(strategy_name: str) -> dict[str, Any] | None:
    """Load params from TOML config if it exists, else return None."""
    ...
```

#### Scenario: Save writes TOML file
- **WHEN** the user clicks "Save as Default Params" after an optimization run
- **THEN** a file `src/strategies/configs/<strategy_name>.toml` SHALL be written containing the best params under a `[params]` table

#### Scenario: Save overwrites existing config
- **WHEN** a TOML config already exists for the strategy
- **THEN** the save SHALL overwrite it with the new params

#### Scenario: Load returns params dict
- **WHEN** `load_strategy_params("atr_mean_reversion")` is called and the config file exists
- **THEN** it SHALL return a `dict[str, Any]` of the param values

#### Scenario: Load returns None when no config
- **WHEN** `load_strategy_params("nonexistent")` is called
- **THEN** it SHALL return `None`

#### Scenario: TOML format is human-readable
- **WHEN** the config file is opened in a text editor
- **THEN** it SHALL contain a `[params]` section with one key-value pair per parameter, with inline comments showing the optimization objective and IS metric value
