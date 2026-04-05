## MODIFIED Requirements

### Requirement: Strategy registry auto-discovery
The system SHALL provide a `src/strategies/registry.py` module that lazily discovers all strategy modules in `src/strategies/` by recursively scanning subdirectories for Python files that export both a `create_*_engine` factory function and a `PARAM_SCHEMA` dict at module level.

The discovery SHALL use `rglob("*.py")` instead of `glob("*.py")`, generating path-like slugs from the relative directory path (e.g., `"short_term/breakout/ta_orb"`).

The discovery SHALL exclude:
- Files starting with `_` (e.g., `_session_utils.py`)
- `__init__.py` files
- Infrastructure modules at the root level: `registry.py`, `param_registry.py`, `param_loader.py`, `scaffold.py`, `code_hash.py`
- Files in the `examples/` directory

#### Scenario: Discovery finds ta_orb in new directory structure
- **WHEN** the registry is first accessed and `src/strategies/short_term/breakout/ta_orb.py` exists with `PARAM_SCHEMA` and `create_ta_orb_engine`
- **THEN** it SHALL discover it with slug `"short_term/breakout/ta_orb"` and module `"src.strategies.short_term.breakout.ta_orb"`

#### Scenario: Discovery finds atr_mean_reversion in new directory structure
- **WHEN** the registry is first accessed and `src/strategies/short_term/mean_reversion/atr_mean_reversion.py` exists
- **THEN** it SHALL discover it with slug `"short_term/mean_reversion/atr_mean_reversion"` and factory `"create_atr_mean_reversion_engine"`

#### Scenario: Discovery finds pyramid_wrapper in swing directory
- **WHEN** the registry is first accessed and `src/strategies/swing/trend_following/pyramid_wrapper.py` exists
- **THEN** it SHALL discover it with slug `"swing/trend_following/pyramid_wrapper"` and module `"src.strategies.swing.trend_following.pyramid_wrapper"`

#### Scenario: Infrastructure files at root are excluded
- **WHEN** `src/strategies/registry.py` exists
- **THEN** it SHALL NOT be treated as a strategy module

#### Scenario: Files without PARAM_SCHEMA are skipped
- **WHEN** a `.py` file in `src/strategies/` has a `create_*_engine` function but no `PARAM_SCHEMA`
- **THEN** the registry SHALL skip that file and log a debug message

#### Scenario: Private files are ignored
- **WHEN** a file starts with `_` (e.g., `_session_utils.py`)
- **THEN** the registry SHALL not attempt to import it

### Requirement: Slug alias resolution
The registry SHALL support resolving flat-name aliases to their canonical path-based slugs. No `intraday/` or `daily/` path aliases are needed — the system is pre-production.

```python
_SLUG_ALIASES: dict[str, str] = {
    # flat name aliases
    "ta_orb": "short_term/breakout/ta_orb",
    "structural_orb": "short_term/breakout/structural_orb",
    "keltner_vwap_breakout": "short_term/breakout/keltner_vwap_breakout",
    "atr_mean_reversion": "short_term/mean_reversion/atr_mean_reversion",
    "bollinger_pinbar": "short_term/mean_reversion/bollinger_pinbar",
    "vwap_statistical_deviation": "short_term/mean_reversion/vwap_statistical_deviation",
    "ema_trend_pullback": "medium_term/trend_following/ema_trend_pullback",
    "donchian_trend_strength": "medium_term/trend_following/donchian_trend_strength",
    "pyramid": "swing/trend_following/pyramid_wrapper",
    "pyramid_wrapper": "swing/trend_following/pyramid_wrapper",
}
```

#### Scenario: Flat alias resolves to new slug
- **WHEN** `get_info("ta_orb")` is called
- **THEN** it SHALL resolve to the `StrategyInfo` for `"short_term/breakout/ta_orb"`

#### Scenario: New slug works directly
- **WHEN** `get_info("short_term/breakout/ta_orb")` is called
- **THEN** it SHALL return the `StrategyInfo` directly without alias lookup

#### Scenario: Unknown slug raises KeyError
- **WHEN** `get_info("nonexistent")` is called and it's not an alias
- **THEN** it SHALL raise `KeyError` with the list of available slugs

### Requirement: StrategyInfo includes new classification fields
The `StrategyInfo` dataclass SHALL include `holding_period`, `signal_timeframe`, and `stop_architecture` fields populated from `STRATEGY_META`, replacing the old `timeframe` field.

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
    holding_period: HoldingPeriod | None = None
    signal_timeframe: SignalTimeframe | None = None
    stop_architecture: StopArchitecture | None = None
```

#### Scenario: New classification populated from STRATEGY_META
- **WHEN** a strategy module's `STRATEGY_META` contains `"holding_period": HoldingPeriod.SHORT_TERM`
- **THEN** the `StrategyInfo.holding_period` SHALL be `HoldingPeriod.SHORT_TERM`

#### Scenario: Missing new classification defaults to None
- **WHEN** a strategy module's `STRATEGY_META` does not contain `"holding_period"`
- **THEN** the `StrategyInfo.holding_period` SHALL be `None`

### Requirement: Filter strategies by new classification
The registry SHALL expose `get_by_holding_period(period)`, `get_by_signal_timeframe(tf)`, and `get_by_session(session)` for filtered queries, replacing the old `get_by_timeframe()`.

```python
def get_by_holding_period(period: HoldingPeriod) -> dict[str, StrategyInfo]: ...
def get_by_signal_timeframe(tf: SignalTimeframe) -> dict[str, StrategyInfo]: ...
def get_by_session(session: str) -> dict[str, StrategyInfo]: ...
```

#### Scenario: Filter by short_term holding period
- **WHEN** `get_by_holding_period(HoldingPeriod.SHORT_TERM)` is called
- **THEN** it SHALL return only strategies whose `STRATEGY_META["holding_period"]` is `HoldingPeriod.SHORT_TERM`
- **AND** the result SHALL include `ta_orb`, `structural_orb`, `keltner_vwap_breakout`, `atr_mean_reversion`, `bollinger_pinbar`, `vwap_statistical_deviation`

#### Scenario: Filter by signal timeframe
- **WHEN** `get_by_signal_timeframe(SignalTimeframe.DAILY)` is called
- **THEN** it SHALL return only strategies whose `STRATEGY_META["signal_timeframe"]` is `SignalTimeframe.DAILY`

#### Scenario: Filter by tradeable session
- **WHEN** `get_by_session("day")` is called
- **THEN** it SHALL return strategies whose `STRATEGY_META["tradeable_sessions"]` list contains `"day"`

#### Scenario: Filter returns empty for unused holding period
- **WHEN** `get_by_holding_period(HoldingPeriod.MEDIUM_TERM)` is called and no medium-term strategies exist
- **THEN** it SHALL return an empty dict

## REMOVED Requirements

### Requirement: Filter strategies by classification (get_by_timeframe)
**Reason**: `get_by_timeframe()` filters on `StrategyTimeframe` which is being removed. Replaced by `get_by_holding_period()`, `get_by_signal_timeframe()`, and `get_by_session()`.
**Migration**: Replace `get_by_timeframe(StrategyTimeframe.INTRADAY)` with `get_by_holding_period(HoldingPeriod.SHORT_TERM)` or `get_by_holding_period(HoldingPeriod.MEDIUM_TERM)` depending on intent. For session-scoped queries, use `get_by_session()`.
