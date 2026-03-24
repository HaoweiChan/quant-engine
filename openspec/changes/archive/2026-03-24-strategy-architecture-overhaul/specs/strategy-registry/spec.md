## MODIFIED Requirements

### Requirement: Strategy registry auto-discovery
The system SHALL provide a `src/strategies/registry.py` module that lazily discovers all strategy modules in `src/strategies/` by recursively scanning subdirectories for Python files that export both a `create_*_engine` factory function and a `PARAM_SCHEMA` dict at module level.

The discovery SHALL use `rglob("*.py")` instead of `glob("*.py")`, generating path-like slugs from the relative directory path (e.g., `"intraday/breakout/ta_orb"`).

The discovery SHALL exclude:
- Files starting with `_` (e.g., `_session_utils.py`)
- `__init__.py` files
- Infrastructure modules at the root level: `registry.py`, `param_registry.py`, `param_loader.py`, `scaffold.py`
- Files in the `examples/` directory

#### Scenario: Discovery finds ta_orb in nested directory
- **WHEN** the registry is first accessed and `src/strategies/intraday/breakout/ta_orb.py` exists with `PARAM_SCHEMA` and `create_ta_orb_engine`
- **THEN** it SHALL discover it with slug `"intraday/breakout/ta_orb"` and module `"src.strategies.intraday.breakout.ta_orb"`

#### Scenario: Discovery finds atr_mean_reversion in nested directory
- **WHEN** the registry is first accessed and `src/strategies/intraday/mean_reversion/atr_mean_reversion.py` exists
- **THEN** it SHALL discover it with slug `"intraday/mean_reversion/atr_mean_reversion"` and factory `"create_atr_mean_reversion_engine"`

#### Scenario: Infrastructure files at root are excluded
- **WHEN** `src/strategies/registry.py` exists
- **THEN** it SHALL NOT be treated as a strategy module

#### Scenario: Files without PARAM_SCHEMA are skipped
- **WHEN** a `.py` file in `src/strategies/` has a `create_*_engine` function but no `PARAM_SCHEMA`
- **THEN** the registry SHALL skip that file and log a debug message

#### Scenario: Private files are ignored
- **WHEN** a file starts with `_` (e.g., `_session_utils.py`)
- **THEN** the registry SHALL not attempt to import it

## ADDED Requirements

### Requirement: Slug alias resolution
The registry SHALL support resolving legacy flat slugs (e.g., `"ta_orb"`) to their new path-based slugs via an alias map.

```python
_SLUG_ALIASES: dict[str, str] = {
    "ta_orb": "intraday/breakout/ta_orb",
    "atr_mean_reversion": "intraday/mean_reversion/atr_mean_reversion",
    "pyramid": "daily/trend_following/pyramid_wrapper",
    "pyramid_wrapper": "daily/trend_following/pyramid_wrapper",
}
```

#### Scenario: Alias resolves to new slug
- **WHEN** `get_info("ta_orb")` is called
- **THEN** it SHALL resolve to the `StrategyInfo` for `"intraday/breakout/ta_orb"`

#### Scenario: New slug works directly
- **WHEN** `get_info("intraday/breakout/ta_orb")` is called
- **THEN** it SHALL return the `StrategyInfo` directly without alias lookup

#### Scenario: Unknown slug raises KeyError
- **WHEN** `get_info("nonexistent")` is called and it's not an alias
- **THEN** it SHALL raise `KeyError` with the list of available slugs

### Requirement: Registry cache invalidation
The registry SHALL expose a `invalidate()` function that clears the cached discovery results, forcing re-discovery on the next access.

```python
def invalidate() -> None:
    """Clear the registry cache. Next access triggers re-discovery."""
```

#### Scenario: Invalidation triggers re-scan
- **WHEN** `invalidate()` is called and then `get_all()` is called
- **THEN** it SHALL re-scan `src/strategies/` and return fresh results including any newly written files

#### Scenario: Invalidation after write_strategy_file
- **WHEN** a new strategy file is written via `write_strategy_file`
- **THEN** the registry SHALL be invalidated so the strategy becomes immediately discoverable

### Requirement: StrategyInfo includes classification
The `StrategyInfo` dataclass SHALL include optional `category` and `timeframe` fields populated from `STRATEGY_META`.

```python
@dataclass
class StrategyInfo:
    name: str
    slug: str
    module: str
    factory: str
    param_schema: dict[str, dict]
    meta: dict
    category: StrategyCategory | None = None
    timeframe: StrategyTimeframe | None = None
```

#### Scenario: Classification populated from STRATEGY_META
- **WHEN** a strategy module's `STRATEGY_META` contains `"category": StrategyCategory.BREAKOUT`
- **THEN** the `StrategyInfo.category` SHALL be `StrategyCategory.BREAKOUT`

#### Scenario: Missing classification defaults to None
- **WHEN** a strategy module's `STRATEGY_META` does not contain `"category"`
- **THEN** the `StrategyInfo.category` SHALL be `None`

### Requirement: Filter strategies by classification
The registry SHALL expose `get_by_category(category)` and `get_by_timeframe(timeframe)` for filtered queries.

```python
def get_by_category(category: StrategyCategory) -> dict[str, StrategyInfo]: ...
def get_by_timeframe(timeframe: StrategyTimeframe) -> dict[str, StrategyInfo]: ...
```

#### Scenario: Filter by breakout category
- **WHEN** `get_by_category(StrategyCategory.BREAKOUT)` is called
- **THEN** it SHALL return only strategies whose `STRATEGY_META["category"]` is `StrategyCategory.BREAKOUT`

#### Scenario: Filter returns empty for unused category
- **WHEN** `get_by_category(StrategyCategory.TREND_FOLLOWING)` is called and no trend-following strategies exist
- **THEN** it SHALL return an empty dict
