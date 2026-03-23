## MODIFIED Requirements

### Requirement: User-editable strategy directory
The project SHALL maintain a `src/strategies/` directory containing Python files that implement one or more of the core policy ABCs (`EntryPolicy`, `AddPolicy`, `StopPolicy`) and a `configs/` subdirectory for TOML engine configuration files.

Strategy factory functions in `src/strategies/` SHALL expose all tunable parameters as explicit keyword arguments so that `StrategyOptimizer` can call them programmatically.

Strategy modules that contain a `create_*_engine` factory function SHALL also export a module-level `PARAM_SCHEMA: dict[str, dict]` declaring metadata for each tunable parameter.

Each entry in `PARAM_SCHEMA` SHALL have the following structure:

```python
PARAM_SCHEMA: dict[str, dict] = {
    "<param_name>": {
        "type": "int" | "float",       # required
        "default": <value>,            # required, must match factory default
        "min": <value>,                # optional, for UI/validation
        "max": <value>,                # optional, for UI/validation
        "description": "<text>",       # required
        "grid": [<values>],            # optional, optimizer grid defaults
    },
}
```

Strategy modules MAY also export a `STRATEGY_META: dict` containing non-parameter metadata (e.g., `recommended_timeframe`, `bars_per_day`, `presets`).

#### Scenario: ATR Mean Reversion exports PARAM_SCHEMA
- **WHEN** `src/strategies/atr_mean_reversion.py` is imported
- **THEN** it SHALL have a module-level `PARAM_SCHEMA` dict with keys matching the factory's keyword arguments (excluding `max_loss`, `lots`, `contract_type`)

#### Scenario: PARAM_SCHEMA defaults match factory defaults
- **WHEN** `PARAM_SCHEMA["bb_len"]["default"]` is read
- **THEN** it SHALL equal the default value of the `bb_len` parameter in `create_atr_mean_reversion_engine()`

#### Scenario: Strategy files import from core only
- **WHEN** a strategy file is evaluated
- **THEN** it SHALL only import from `src.core.policies` (ABCs), `src.core.types` (data types), and `src.core.position_engine` (for factory functions that construct and return a `PositionEngine`) — never from execution, bar_simulator, or other application layers

#### Scenario: Factory functions are module-level and picklable
- **WHEN** a strategy factory function (e.g., `create_atr_mean_reversion_engine`) is defined in `src/strategies/`
- **THEN** it SHALL be a module-level function (not a lambda or closure) so it can be pickled by `StrategyOptimizer` for parallel execution
