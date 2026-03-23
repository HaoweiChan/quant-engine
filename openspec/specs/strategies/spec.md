## Purpose

A user-editable directory (`src/strategies/`) containing custom policy implementations and engine configuration files. This is the defined sandbox for strategy development — users extend the core policy ABCs here without touching system internals. The directory is the exclusive target of the dashboard code editor.

## Requirements

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

### Requirement: Engine config files
The `src/strategies/configs/` directory SHALL contain per-strategy TOML files using the convention `configs/<slug>.toml`. Each strategy's config stores its optimized parameter overrides under a `[params]` table. The legacy `default.toml` is replaced by per-strategy files.

#### Scenario: Pyramid config in its own file
- **WHEN** `load_strategy_params("pyramid")` is called
- **THEN** it SHALL read from `src/strategies/configs/pyramid.toml`

#### Scenario: Legacy default.toml is removed
- **WHEN** the migration is complete
- **THEN** `src/strategies/configs/default.toml` SHALL NOT exist

### Requirement: Policy ABC compliance
All `.py` files in `src/strategies/` SHALL implement at least one of the policy ABCs from `src.core.policies`. Classes SHALL be instantiable with a `PyramidConfig` argument and SHALL implement all abstract methods.

#### Scenario: Strategy instantiation succeeds
- **WHEN** the engine validation pipeline runs
- **THEN** all strategy classes SHALL instantiate with a default `PyramidConfig` without raising exceptions

### Requirement: Strategy file validation
The system SHALL provide a validation function that checks strategy file content before it is written to `src/strategies/`.

```python
@dataclass
class ValidationResult:
    valid: bool
    errors: list[str]

def validate_strategy_content(content: str, filename: str) -> ValidationResult: ...
```

#### Scenario: Syntax validation
- **WHEN** `validate_strategy_content` is called with content containing a Python syntax error
- **THEN** `ValidationResult.valid` SHALL be `False` and `errors` SHALL include the syntax error message with line number

#### Scenario: Forbidden import detection
- **WHEN** content contains `import os`, `import sys`, `import subprocess`, `import socket`, `import requests`, or `import shutil`
- **THEN** `ValidationResult.valid` SHALL be `False` and `errors` SHALL include `"Forbidden import: <module>"`

#### Scenario: Forbidden from-import detection
- **WHEN** content contains `from os import ...` or `from subprocess import ...`
- **THEN** `ValidationResult.valid` SHALL be `False` and `errors` SHALL include `"Forbidden import: <module>"`

#### Scenario: Policy ABC interface check
- **WHEN** content defines a class that subclasses `EntryPolicy`, `AddPolicy`, or `StopPolicy`
- **THEN** validation SHALL verify the class implements all required abstract methods of that ABC

#### Scenario: Missing method detected
- **WHEN** a class subclasses `StopPolicy` but does not define `initial_stop` or `update_stop`
- **THEN** `ValidationResult.valid` SHALL be `False` and `errors` SHALL list the missing methods

#### Scenario: Valid content passes
- **WHEN** content is syntactically valid Python, contains no forbidden imports, and all policy classes implement required methods
- **THEN** `ValidationResult.valid` SHALL be `True` and `errors` SHALL be empty

### Requirement: Strategy file backup
The system SHALL provide a backup mechanism for strategy files before they are overwritten.

```python
def backup_strategy_file(filename: str) -> str | None: ...
```

#### Scenario: Backup before overwrite
- **WHEN** `backup_strategy_file` is called for an existing file
- **THEN** it SHALL copy the current file to `src/strategies/.backup/<filename>.<ISO-timestamp>.py` and return the backup path

#### Scenario: Backup directory creation
- **WHEN** `src/strategies/.backup/` does not exist
- **THEN** `backup_strategy_file` SHALL create it before saving the backup

#### Scenario: No backup for new files
- **WHEN** `backup_strategy_file` is called for a filename that does not exist in `src/strategies/`
- **THEN** it SHALL return `None` without creating a backup

### Requirement: Strategy file listing
The system SHALL provide a function to list available strategy files.

```python
def list_strategy_files() -> list[dict]: ...
```

#### Scenario: List all strategy files
- **WHEN** `list_strategy_files` is called
- **THEN** it SHALL return a list of `{"filename": str, "size_bytes": int, "modified": str}` for each `.py` file in `src/strategies/` (excluding `__init__.py` and `__pycache__/`)

#### Scenario: Empty strategies directory
- **WHEN** `src/strategies/` contains no `.py` files (other than `__init__.py`)
- **THEN** it SHALL return an empty list
