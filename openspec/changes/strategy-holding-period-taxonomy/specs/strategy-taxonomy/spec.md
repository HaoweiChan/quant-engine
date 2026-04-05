## ADDED Requirements

### Requirement: Signal timeframe enum
The system SHALL define a `SignalTimeframe` enum in `src/strategies/__init__.py` that describes the bar timeframe used for signal generation.

```python
class SignalTimeframe(str, Enum):
    ONE_MIN = "1min"
    FIVE_MIN = "5min"
    FIFTEEN_MIN = "15min"
    ONE_HOUR = "1hour"
    DAILY = "daily"
```

#### Scenario: SignalTimeframe is string-based for JSON serialization
- **WHEN** `SignalTimeframe.FIFTEEN_MIN` is serialized via `json.dumps`
- **THEN** it SHALL serialize as `"15min"`

#### Scenario: SignalTimeframe is importable from strategies package
- **WHEN** `from src.strategies import SignalTimeframe` is executed
- **THEN** it SHALL succeed without error

### Requirement: Holding period enum
The system SHALL define a `HoldingPeriod` enum in `src/strategies/__init__.py` that describes the expected duration of a position.

```python
class HoldingPeriod(str, Enum):
    SHORT_TERM = "short_term"      # < 4 hours
    MEDIUM_TERM = "medium_term"    # 4 hours - 5 days
    SWING = "swing"                # 1-4 weeks
```

#### Scenario: HoldingPeriod is string-based for JSON serialization
- **WHEN** `HoldingPeriod.SHORT_TERM` is serialized via `json.dumps`
- **THEN** it SHALL serialize as `"short_term"`

#### Scenario: HoldingPeriod is importable from strategies package
- **WHEN** `from src.strategies import HoldingPeriod` is executed
- **THEN** it SHALL succeed without error

### Requirement: Stop architecture enum
The system SHALL define a `StopArchitecture` enum in `src/strategies/__init__.py` that determines session-close behavior.

```python
class StopArchitecture(str, Enum):
    INTRADAY = "intraday"    # Must flatten before session end
    SWING = "swing"          # Can hold multiple days
```

#### Scenario: StopArchitecture is string-based for JSON serialization
- **WHEN** `StopArchitecture.INTRADAY` is serialized via `json.dumps`
- **THEN** it SHALL serialize as `"intraday"`

#### Scenario: StopArchitecture is importable from strategies package
- **WHEN** `from src.strategies import StopArchitecture` is executed
- **THEN** it SHALL succeed without error

### Requirement: Expanded STRATEGY_META schema
Every strategy module SHALL export a `STRATEGY_META: dict` containing the following fields:

```python
STRATEGY_META: dict = {
    "category": StrategyCategory,                    # required
    "signal_timeframe": SignalTimeframe,              # required
    "holding_period": HoldingPeriod,                  # required
    "stop_architecture": StopArchitecture,            # required
    "expected_duration_minutes": tuple[int, int],     # required (min, max)
    "tradeable_sessions": list[str],                  # required: ["day"], ["night"], or ["day", "night"]
    "description": str,                               # required
    # optional fields:
    "bars_per_day": int,
    "presets": dict,
    "paper": str,
}
```

The old `"timeframe"` key SHALL NOT be present. The old `"session"` key SHALL be replaced by `"tradeable_sessions"` (always a list).

#### Scenario: Short-term breakout strategy metadata
- **WHEN** `ta_orb.py`'s `STRATEGY_META` is read
- **THEN** `STRATEGY_META["signal_timeframe"]` SHALL be `SignalTimeframe.FIFTEEN_MIN`
- **AND** `STRATEGY_META["holding_period"]` SHALL be `HoldingPeriod.SHORT_TERM`
- **AND** `STRATEGY_META["stop_architecture"]` SHALL be `StopArchitecture.INTRADAY`
- **AND** `STRATEGY_META["expected_duration_minutes"]` SHALL be a 2-tuple of integers
- **AND** `STRATEGY_META["tradeable_sessions"]` SHALL be a list of strings

#### Scenario: Swing strategy metadata
- **WHEN** `pyramid_wrapper.py`'s `STRATEGY_META` is read
- **THEN** `STRATEGY_META["signal_timeframe"]` SHALL be `SignalTimeframe.DAILY`
- **AND** `STRATEGY_META["holding_period"]` SHALL be `HoldingPeriod.SWING`
- **AND** `STRATEGY_META["stop_architecture"]` SHALL be `StopArchitecture.SWING`

#### Scenario: Old timeframe key absent
- **WHEN** any strategy module's `STRATEGY_META` is read after migration
- **THEN** `"timeframe"` SHALL NOT be a key in the dict

#### Scenario: tradeable_sessions is always a list
- **WHEN** any strategy module's `STRATEGY_META` is read
- **THEN** `STRATEGY_META["tradeable_sessions"]` SHALL be a `list[str]`, never a bare string

### Requirement: Quality gate thresholds by holding period
The system SHALL define expected metric ranges per holding period for use by the optimizer and risk auditor:

| HoldingPeriod | Win Rate | Profit Factor | Max Drawdown |
|---------------|----------|---------------|--------------|
| SHORT_TERM | 55-65% | 1.3-1.8 | < 5% |
| MEDIUM_TERM | 45-55% | 1.8-2.5 | 5-8% |
| SWING | 35-45% | 2.5+ | 8-15% |

These thresholds SHALL be accessible via a function:

```python
def get_quality_thresholds(period: HoldingPeriod) -> dict[str, tuple[float, float]]:
    """Return expected metric ranges for a holding period.

    Returns dict with keys: win_rate, profit_factor, max_drawdown
    Each value is a (min, max) tuple.
    """
```

#### Scenario: Short-term thresholds
- **WHEN** `get_quality_thresholds(HoldingPeriod.SHORT_TERM)` is called
- **THEN** `result["win_rate"]` SHALL be `(0.55, 0.65)`
- **AND** `result["profit_factor"]` SHALL be `(1.3, 1.8)`
- **AND** `result["max_drawdown"]` SHALL be `(0.0, 0.05)`

#### Scenario: Swing thresholds
- **WHEN** `get_quality_thresholds(HoldingPeriod.SWING)` is called
- **THEN** `result["win_rate"]` SHALL be `(0.35, 0.45)`
- **AND** `result["profit_factor"]` SHALL be `(2.5, float('inf'))`
