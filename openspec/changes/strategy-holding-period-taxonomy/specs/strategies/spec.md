## MODIFIED Requirements

### Requirement: User-editable strategy directory
The project SHALL maintain a `src/strategies/` directory organized into a nested structure with **holding period** as the primary axis and **entry logic** as the secondary axis:

```
src/strategies/
├── short_term/
│   ├── breakout/
│   ├── mean_reversion/
│   └── trend_following/
├── medium_term/
│   ├── breakout/
│   ├── mean_reversion/
│   └── trend_following/
├── swing/
│   ├── breakout/
│   ├── mean_reversion/
│   └── trend_following/
├── examples/
├── _session_utils.py
├── _shared_indicators.py
├── scaffold.py
├── registry.py
├── param_registry.py
├── param_loader.py
├── code_hash.py
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

Strategy modules SHALL also export a `STRATEGY_META: dict` containing classification metadata using the `StrategyCategory`, `SignalTimeframe`, `HoldingPeriod`, and `StopArchitecture` enums:

```python
STRATEGY_META: dict = {
    "category": StrategyCategory.BREAKOUT,                   # required
    "signal_timeframe": SignalTimeframe.FIFTEEN_MIN,          # required
    "holding_period": HoldingPeriod.SHORT_TERM,               # required
    "stop_architecture": StopArchitecture.INTRADAY,           # required
    "expected_duration_minutes": (30, 120),                   # required
    "tradeable_sessions": ["day", "night"],                   # required
    "description": "...",                                     # required
}
```

#### Scenario: Strategy files in nested directories are discovered
- **WHEN** a `.py` file exists at `src/strategies/short_term/breakout/ta_orb.py` with `PARAM_SCHEMA` and `create_ta_orb_engine`
- **THEN** the strategy registry SHALL discover it with slug `"short_term/breakout/ta_orb"` and module `"src.strategies.short_term.breakout.ta_orb"`

#### Scenario: Infrastructure files at root level are excluded
- **WHEN** `src/strategies/registry.py`, `param_registry.py`, `param_loader.py`, `scaffold.py`, or `code_hash.py` exist at root level
- **THEN** the strategy discovery SHALL NOT attempt to import them as strategies

#### Scenario: Private files are excluded
- **WHEN** a file starts with `_` (e.g., `_session_utils.py`, `_shared_indicators.py`)
- **THEN** the strategy discovery SHALL NOT attempt to import it

#### Scenario: Example files are excluded from discovery
- **WHEN** files exist in `src/strategies/examples/`
- **THEN** the strategy discovery SHALL NOT discover them as strategies

#### Scenario: STRATEGY_META uses new enum classification
- **WHEN** `ta_orb.py` is imported
- **THEN** its `STRATEGY_META["category"]` SHALL be `StrategyCategory.BREAKOUT`
- **AND** its `STRATEGY_META["signal_timeframe"]` SHALL be `SignalTimeframe.FIFTEEN_MIN`
- **AND** its `STRATEGY_META["holding_period"]` SHALL be `HoldingPeriod.SHORT_TERM`
- **AND** its `STRATEGY_META["stop_architecture"]` SHALL be `StopArchitecture.INTRADAY`

#### Scenario: Strategy files import from core only
- **WHEN** a strategy file is evaluated
- **THEN** it SHALL only import from `src.core.policies` (ABCs), `src.core.types` (data types), `src.core.position_engine` (for factory), and `src.strategies._session_utils` / `src.strategies._shared_indicators` (shared utilities)

#### Scenario: Factory functions are module-level and picklable
- **WHEN** a strategy factory function is defined
- **THEN** it SHALL be a module-level function (not a lambda or closure) so it can be pickled by `StrategyOptimizer` for parallel execution

### Requirement: Strategy classification enums
The system SHALL define `StrategyCategory`, `SignalTimeframe`, `HoldingPeriod`, and `StopArchitecture` enums in `src/strategies/__init__.py`.

```python
from enum import Enum

class StrategyCategory(str, Enum):
    BREAKOUT = "breakout"
    MEAN_REVERSION = "mean_reversion"
    TREND_FOLLOWING = "trend_following"

class SignalTimeframe(str, Enum):
    ONE_MIN = "1min"
    FIVE_MIN = "5min"
    FIFTEEN_MIN = "15min"
    ONE_HOUR = "1hour"
    DAILY = "daily"

class HoldingPeriod(str, Enum):
    SHORT_TERM = "short_term"
    MEDIUM_TERM = "medium_term"
    SWING = "swing"

class StopArchitecture(str, Enum):
    INTRADAY = "intraday"
    SWING = "swing"
```

The `StrategyTimeframe` enum SHALL be removed.

#### Scenario: New enums are string-based for JSON serialization
- **WHEN** `SignalTimeframe.FIFTEEN_MIN` is serialized via `json.dumps`
- **THEN** it SHALL serialize as `"15min"` (string value)

#### Scenario: New enums are importable from strategies package
- **WHEN** `from src.strategies import SignalTimeframe, HoldingPeriod, StopArchitecture` is executed
- **THEN** it SHALL succeed without error

#### Scenario: StrategyCategory remains unchanged
- **WHEN** `from src.strategies import StrategyCategory` is executed
- **THEN** it SHALL still provide `BREAKOUT`, `MEAN_REVERSION`, `TREND_FOLLOWING` values

## REMOVED Requirements

### Requirement: StrategyTimeframe enum (from Strategy classification enums)
**Reason**: Replaced by three independent enums (`SignalTimeframe`, `HoldingPeriod`, `StopArchitecture`) that capture the distinct dimensions previously collapsed into a single enum.
**Migration**: Replace all references to `StrategyTimeframe.INTRADAY` with the appropriate combination of `SignalTimeframe`, `HoldingPeriod`, and `StopArchitecture`. Replace `StrategyTimeframe.DAILY` with `SignalTimeframe.DAILY` + `HoldingPeriod.SWING` + `StopArchitecture.SWING`.
