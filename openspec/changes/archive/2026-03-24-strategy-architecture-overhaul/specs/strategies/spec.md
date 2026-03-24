## MODIFIED Requirements

### Requirement: User-editable strategy directory
The project SHALL maintain a `src/strategies/` directory organized into a nested structure with timeframe as the primary axis and strategy type as the secondary axis:

```
src/strategies/
├── intraday/
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
- **WHEN** a `.py` file exists at `src/strategies/intraday/breakout/ta_orb.py` with `PARAM_SCHEMA` and `create_ta_orb_engine`
- **THEN** the strategy registry SHALL discover it with slug `"intraday/breakout/ta_orb"` and module `"src.strategies.intraday.breakout.ta_orb"`

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

## ADDED Requirements

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

### Requirement: Strategy file listing supports nested directories
The `list_strategy_files()` function SHALL recursively scan `src/strategies/` subdirectories and return path-like stems.

```python
def list_strategy_files() -> list[dict[str, Any]]: ...
```

#### Scenario: Nested files included in listing
- **WHEN** `list_strategy_files()` is called and `src/strategies/intraday/breakout/ta_orb.py` exists
- **THEN** the result SHALL include `{"filename": "intraday/breakout/ta_orb", "size_bytes": ..., "modified": ...}`

#### Scenario: Infrastructure and private files excluded
- **WHEN** `list_strategy_files()` is called
- **THEN** the result SHALL NOT include entries for `registry.py`, `param_registry.py`, `param_loader.py`, `scaffold.py`, `_session_utils.py`, or any `__init__.py` file

### Requirement: Strategy file write supports nested paths
The `write_strategy_file` workflow SHALL support path-like filenames that create parent directories as needed.

#### Scenario: Write to nested path
- **WHEN** `write_strategy_file(filename="intraday/trend_following/ema_pullback", content=...)` is called
- **THEN** it SHALL create directories `src/strategies/intraday/trend_following/` if they don't exist
- **AND** write the content to `src/strategies/intraday/trend_following/ema_pullback.py`

#### Scenario: Registry cache invalidated after write
- **WHEN** `write_strategy_file` completes successfully
- **THEN** the strategy registry's cached discovery results SHALL be invalidated so the next access re-discovers

### Requirement: Strategy file backup supports nested paths
The `backup_strategy_file` function SHALL preserve the subdirectory structure within `.backup/`.

#### Scenario: Backup nested strategy file
- **WHEN** `backup_strategy_file("intraday/breakout/ta_orb")` is called
- **THEN** it SHALL save to `src/strategies/.backup/intraday/breakout/ta_orb.<timestamp>.py`
