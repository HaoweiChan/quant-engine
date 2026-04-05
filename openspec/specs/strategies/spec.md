## Purpose

A user-editable directory (`src/strategies/`) containing custom policy implementations and engine configuration files. This is the defined sandbox for strategy development — users extend the core policy ABCs here without touching system internals. The directory is the exclusive target of the dashboard code editor.

## Requirements

### Requirement: User-editable strategy directory
The project SHALL maintain a `src/strategies/` directory organized into a nested structure with timeframe as the primary axis and strategy type as the secondary axis:

```
src/strategies/
├── short_term/
│   ├── breakout/
│   ├── mean_reversion/
│   └── trend_following/
├── daily/
│   ├── breakout/
│   └── trend_following/
├── examples/
├── _session_utils.py
├── _shared_indicators.py
├── scaffold.py
├── registry.py
├── param_registry.py
├── param_loader.py
├── configs/
└── __init__.py
```

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

Strategy modules SHALL also export a `STRATEGY_META: dict` containing classification metadata using the `StrategyCategory` and `StrategyTimeframe` enums:

```python
STRATEGY_META: dict = {
    "category": StrategyCategory.BREAKOUT,       # required enum value
    "timeframe": StrategyTimeframe.INTRADAY,     # required enum value
    "session": "day" | "night" | "both",         # optional, for intraday
    "description": "...",                         # required
}
```

#### Scenario: Strategy files in nested directories are discovered
- **WHEN** a `.py` file exists at `src/strategies/short_term/breakout/ta_orb.py` with `PARAM_SCHEMA` and `create_ta_orb_engine`
- **THEN** the strategy registry SHALL discover it with slug `"short_term/breakout/ta_orb"` and module `"src.strategies.short_term.breakout.ta_orb"`

#### Scenario: Infrastructure files at root level are excluded
- **WHEN** `src/strategies/registry.py`, `param_registry.py`, `param_loader.py`, or `scaffold.py` exist at root level
- **THEN** the strategy discovery SHALL NOT attempt to import them as strategies

#### Scenario: Private files are excluded
- **WHEN** a file starts with `_` (e.g., `_session_utils.py`, `_shared_indicators.py`)
- **THEN** the strategy discovery SHALL NOT attempt to import it

#### Scenario: Example files are excluded from discovery
- **WHEN** files exist in `src/strategies/examples/`
- **THEN** the strategy discovery SHALL NOT discover them as strategies (they lack `PARAM_SCHEMA` and factories)

#### Scenario: STRATEGY_META uses enum classification
- **WHEN** `ta_orb.py` is imported
- **THEN** its `STRATEGY_META["category"]` SHALL be `StrategyCategory.BREAKOUT`
- **AND** its `STRATEGY_META["timeframe"]` SHALL be `StrategyTimeframe.INTRADAY`

#### Scenario: Strategy files import from core only
- **WHEN** a strategy file is evaluated
- **THEN** it SHALL only import from `src.core.policies` (ABCs), `src.core.types` (data types), `src.core.position_engine` (for factory), and `src.strategies._session_utils` / `src.strategies._shared_indicators` (shared utilities)

#### Scenario: Factory functions are module-level and picklable
- **WHEN** a strategy factory function is defined
- **THEN** it SHALL be a module-level function (not a lambda or closure) so it can be pickled by `StrategyOptimizer` for parallel execution

### Requirement: Strategy classification enums
The system SHALL define `StrategyCategory` and `StrategyTimeframe` enums in `src/strategies/__init__.py`.

```python
from enum import Enum

class StrategyCategory(str, Enum):
    BREAKOUT = "breakout"
    MEAN_REVERSION = "mean_reversion"
    TREND_FOLLOWING = "trend_following"

class StrategyTimeframe(str, Enum):
    INTRADAY = "intraday"
    DAILY = "daily"
    MULTI_DAY = "multi_day"
```

#### Scenario: Enums are string-based for JSON serialization
- **WHEN** `StrategyCategory.BREAKOUT` is serialized via `json.dumps`
- **THEN** it SHALL serialize as `"breakout"` (string value)

#### Scenario: Enums are importable from strategies package
- **WHEN** `from src.strategies import StrategyCategory, StrategyTimeframe` is executed
- **THEN** it SHALL succeed without error

### Requirement: Shared session utilities
The system SHALL provide a `src/strategies/_session_utils.py` module containing TAIFEX session boundary helpers shared across intraday strategies.

```python
def in_day_session(t: time) -> bool: ...
def in_night_session(t: time) -> bool: ...
def in_or_window(t: time) -> bool: ...
def in_force_close(t: time, mode: str = "default") -> bool: ...
```

#### Scenario: Day session boundaries
- **WHEN** `in_day_session(time(8, 45))` is called
- **THEN** it SHALL return `True`
- **AND** `in_day_session(time(13, 16))` SHALL return `False`

#### Scenario: Night session boundaries
- **WHEN** `in_night_session(time(15, 15))` is called
- **THEN** it SHALL return `True`
- **AND** `in_night_session(time(4, 31))` SHALL return `False`

#### Scenario: Force close with mode
- **WHEN** `in_force_close(time(13, 30), mode="default")` is called
- **THEN** it SHALL return `True` (13:25-13:45 is day force-close window)

#### Scenario: Existing strategies use shared module
- **WHEN** `atr_mean_reversion.py` and `ta_orb.py` are refactored
- **THEN** they SHALL import session helpers from `src.strategies._session_utils` instead of defining their own

### Requirement: Shared indicator utilities
The system SHALL provide a `src/strategies/_shared_indicators.py` module containing reusable rolling indicator computations.

```python
class RollingATR:
    def __init__(self, length: int) -> None: ...
    def update(self, price: float) -> None: ...
    @property
    def value(self) -> float | None: ...

class RollingBB:
    def __init__(self, length: int, upper_mult: float, lower_mult: float) -> None: ...
    def update(self, price: float) -> None: ...

class RollingRSI:
    def __init__(self, length: int) -> None: ...
    def update(self, price: float) -> None: ...

class RollingMA:
    def __init__(self, length: int) -> None: ...
    def update(self, price: float) -> None: ...
```

#### Scenario: RollingATR matches existing behavior
- **WHEN** `RollingATR(14)` is updated with the same price sequence as `atr_mean_reversion._Indicators` with `atr_len=14`
- **THEN** the `value` property SHALL produce the same result

#### Scenario: Indicators warm up correctly
- **WHEN** fewer than `length` updates have been provided
- **THEN** the `value` property SHALL return `None`

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
The system SHALL provide a backup mechanism for strategy files before they are overwritten. The backup function SHALL preserve the subdirectory structure within `.backup/`.

```python
def backup_strategy_file(filename: str) -> str | None: ...
```

#### Scenario: Backup before overwrite
- **WHEN** `backup_strategy_file` is called for an existing file
- **THEN** it SHALL copy the current file to `src/strategies/.backup/<filename>.<ISO-timestamp>.py` and return the backup path

#### Scenario: Backup nested strategy file
- **WHEN** `backup_strategy_file("short_term/breakout/ta_orb")` is called
- **THEN** it SHALL save to `src/strategies/.backup/short_term/breakout/ta_orb.<timestamp>.py`

#### Scenario: Backup directory creation
- **WHEN** `src/strategies/.backup/` does not exist
- **THEN** `backup_strategy_file` SHALL create it before saving the backup

#### Scenario: No backup for new files
- **WHEN** `backup_strategy_file` is called for a filename that does not exist in `src/strategies/`
- **THEN** it SHALL return `None` without creating a backup

### Requirement: Strategy file listing
The system SHALL provide a function to list available strategy files. The function SHALL recursively scan `src/strategies/` subdirectories and return path-like stems.

```python
def list_strategy_files() -> list[dict[str, Any]]: ...
```

#### Scenario: Nested files included in listing
- **WHEN** `list_strategy_files()` is called and `src/strategies/short_term/breakout/ta_orb.py` exists
- **THEN** the result SHALL include `{"filename": "short_term/breakout/ta_orb", "size_bytes": ..., "modified": ...}`

#### Scenario: Infrastructure and private files excluded
- **WHEN** `list_strategy_files()` is called
- **THEN** the result SHALL NOT include entries for `registry.py`, `param_registry.py`, `param_loader.py`, `scaffold.py`, `_session_utils.py`, or any `__init__.py` file

#### Scenario: Empty strategies directory
- **WHEN** `src/strategies/` contains no `.py` files (other than excluded infrastructure)
- **THEN** it SHALL return an empty list

### Requirement: Strategy file write supports nested paths
The `write_strategy_file` workflow SHALL support path-like filenames that create parent directories as needed.

#### Scenario: Write to nested path
- **WHEN** `write_strategy_file(filename="medium_term/trend_following/ema_pullback", content=...)` is called
- **THEN** it SHALL create directories `src/strategies/medium_term/trend_following/` if they don't exist
- **AND** write the content to `src/strategies/medium_term/trend_following/ema_pullback.py`

#### Scenario: Registry cache invalidated after write
- **WHEN** `write_strategy_file` completes successfully
- **THEN** the strategy registry's cached discovery results SHALL be invalidated so the next access re-discovers
