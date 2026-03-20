## Purpose

Provide a bar-level price simulation engine for backtesting. Given a single OHLC bar, simulate the intra-bar price path, check active stops, and determine entry fills — without look-ahead bias and without depending on any external trading framework.

## Requirements

### Requirement: OHLCBar data model
The system SHALL define an `OHLCBar` dataclass to represent a single OHLC bar.

```python
@dataclass
class OHLCBar:
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int
```

#### Scenario: All fields present
- **WHEN** an `OHLCBar` is constructed
- **THEN** it SHALL have `timestamp`, `open`, `high`, `low`, `close`, and `volume` fields

### Requirement: StopLevel data model
The system SHALL define a `StopLevel` dataclass to represent an active stop condition.

```python
@dataclass
class StopLevel:
    price: float
    direction: Literal["below", "above"]
    label: str
```

#### Scenario: Long stop-loss direction
- **WHEN** `direction` is `"below"`
- **THEN** the stop triggers when price <= `stop.price`

#### Scenario: Short stop-loss direction
- **WHEN** `direction` is `"above"`
- **THEN** the stop triggers when price >= `stop.price`

### Requirement: StopTriggerResult data model
The system SHALL define a `StopTriggerResult` dataclass for stop check outcomes.

```python
@dataclass
class StopTriggerResult:
    triggered: bool
    trigger_price: float | None
    trigger_label: str | None
    sequence_idx: int | None
```

#### Scenario: No stop triggered
- **WHEN** no stop condition is met
- **THEN** `triggered` SHALL be `False` and all other fields SHALL be `None`

#### Scenario: Stop triggered
- **WHEN** a stop condition is met
- **THEN** `triggered` SHALL be `True`, `trigger_price` SHALL be the estimated fill price, `trigger_label` SHALL identify which stop fired, and `sequence_idx` SHALL be the position in the price sequence

### Requirement: EntryFillResult data model
The system SHALL define an `EntryFillResult` dataclass for entry fill outcomes.

```python
@dataclass
class EntryFillResult:
    filled: bool
    fill_price: float | None
    fill_bar: Literal["signal_bar_close", "next_bar_open"]
    slippage: float
```

#### Scenario: Entry filled
- **WHEN** an entry is filled
- **THEN** `filled` SHALL be `True` and `fill_price` SHALL be the computed fill price

#### Scenario: Entry not filled
- **WHEN** a limit order does not execute
- **THEN** `filled` SHALL be `False` and `fill_price` SHALL be `None`

### Requirement: BarSimResult data model
The system SHALL define a `BarSimResult` dataclass combining stop and entry outcomes.

```python
@dataclass
class BarSimResult:
    stop_result: StopTriggerResult
    entry_result: EntryFillResult | None
    price_sequence: list[float]
    stop_before_entry: bool
```

#### Scenario: No entry signal
- **WHEN** `entry_signal` is `False`
- **THEN** `entry_result` SHALL be `None`

#### Scenario: Both stop and entry on same bar
- **WHEN** a stop triggers and an entry signal exists on the same bar
- **THEN** `stop_before_entry` SHALL be `True`

### Requirement: Intra-bar price sequence generation
The system SHALL generate a conservative price sequence from a single OHLC bar representing the order prices were visited.

#### Scenario: Open always first
- **WHEN** any OHLC bar is processed
- **THEN** the first element of the sequence SHALL be `open`

#### Scenario: Close always last
- **WHEN** any OHLC bar is processed
- **THEN** the last element of the sequence SHALL be `close`

#### Scenario: Open closer to high — up first
- **WHEN** `abs(open - high) <= abs(open - low)`
- **THEN** the sequence SHALL be `[open, high, low, close]`

#### Scenario: Open closer to low — down first
- **WHEN** `abs(open - high) > abs(open - low)`
- **THEN** the sequence SHALL be `[open, low, high, close]`

#### Scenario: Equidistant — default up first
- **WHEN** `abs(open - high) == abs(open - low)`
- **THEN** the sequence SHALL default to `[open, high, low, close]`

#### Scenario: Consecutive duplicates removed
- **WHEN** consecutive elements in the sequence are equal
- **THEN** duplicates SHALL be removed while preserving order

#### Scenario: Doji bar
- **WHEN** `open == high == low == close`
- **THEN** the sequence SHALL be `[open]` (single element)

#### Scenario: Configurable ordering mode
- **WHEN** `high_low_order` is set to `"always_up"` or `"always_down"`
- **THEN** the sequence SHALL use the specified order regardless of open proximity

### Requirement: Stop condition checking against price sequence
The system SHALL check a list of active stop levels against the intra-bar price sequence and return the first triggered stop.

#### Scenario: Long stop triggered within bar
- **WHEN** any price in the sequence is `<= stop.price` for a `"below"` stop
- **THEN** the stop SHALL be reported as triggered

#### Scenario: Short stop triggered within bar
- **WHEN** any price in the sequence is `>= stop.price` for an `"above"` stop
- **THEN** the stop SHALL be reported as triggered

#### Scenario: First triggered stop wins
- **WHEN** multiple stops would trigger at the same sequence position
- **THEN** the stop that appears first in the `stops` list SHALL be returned

#### Scenario: Earliest sequence position wins
- **WHEN** different stops trigger at different sequence positions
- **THEN** the stop triggered at the earliest `sequence_idx` SHALL be returned

#### Scenario: No stops triggered
- **WHEN** no price in the sequence violates any stop level
- **THEN** `triggered` SHALL be `False`

#### Scenario: Fill price includes adverse slippage
- **WHEN** a long stop triggers (`direction="below"`)
- **THEN** `trigger_price` SHALL be `stop.price - slippage_points`

#### Scenario: Short stop fill price includes adverse slippage
- **WHEN** a short stop triggers (`direction="above"`)
- **THEN** `trigger_price` SHALL be `stop.price + slippage_points`

### Requirement: Entry fill checking with look-ahead prevention
The system SHALL prevent look-ahead bias on entry signals by restricting fill timing.

#### Scenario: Bar-close market entry for long
- **WHEN** `entry_mode` is `"bar_close"` and no `limit_price` is set
- **THEN** `filled` SHALL be `True` and `fill_price` SHALL be `signal_bar.close + slippage_points`

#### Scenario: Bar-close market entry for short
- **WHEN** `entry_mode` is `"bar_close"`, no `limit_price`, and direction is short
- **THEN** `fill_price` SHALL be `signal_bar.close - slippage_points`

#### Scenario: Next-open market entry
- **WHEN** `entry_mode` is `"next_open"` and `next_bar` is provided
- **THEN** `filled` SHALL be `True` and `fill_price` SHALL be `next_bar.open + slippage_points` (for long)

#### Scenario: Next-open at end of data
- **WHEN** `entry_mode` is `"next_open"` and `next_bar` is `None`
- **THEN** the function SHALL raise `ValueError`

#### Scenario: Bar-close limit entry for long
- **WHEN** `entry_mode` is `"bar_close"` and `limit_price` is set
- **THEN** `filled` SHALL be `True` only if `signal_bar.low <= limit_price`

#### Scenario: Next-open limit entry
- **WHEN** `entry_mode` is `"next_open"` and `limit_price` is set
- **THEN** `filled` SHALL be `True` only if the next bar's intra-bar price sequence contains a price at or below `limit_price` (for long)

### Requirement: BarSimulator unified interface
The system SHALL provide a `BarSimulator` class that wraps price sequence generation, stop checking, and entry checking into a single `process_bar()` call.

```python
class BarSimulator:
    def __init__(
        self,
        slippage_points: float = 2.0,
        entry_mode: Literal["bar_close", "next_open"] = "bar_close",
        high_low_order: Literal["open_proximity", "always_up", "always_down"] = "open_proximity",
    ): ...

    def process_bar(
        self,
        bar: OHLCBar,
        next_bar: OHLCBar | None,
        stops: list[StopLevel],
        entry_signal: bool,
        limit_price: float | None = None,
    ) -> BarSimResult: ...
```

#### Scenario: Process bar with stops and no entry
- **WHEN** `process_bar()` is called with stops and `entry_signal=False`
- **THEN** `entry_result` SHALL be `None` and stops SHALL be checked against the price sequence

#### Scenario: Process bar with entry and no stops
- **WHEN** `process_bar()` is called with no stops and `entry_signal=True`
- **THEN** `stop_result.triggered` SHALL be `False` and `entry_result` SHALL contain the fill result

#### Scenario: Same-bar stop and entry — stop wins
- **WHEN** both a stop triggers and an entry signal fires on the same bar
- **THEN** `stop_before_entry` SHALL be `True` and entry SHALL be cancelled (`entry_result` is `None` or `entry_result.filled` is `False`)

#### Scenario: Price sequence available for debugging
- **WHEN** `process_bar()` returns
- **THEN** `price_sequence` SHALL contain the full intra-bar price path used for evaluation

### Requirement: No external trading framework dependencies
The `bar_simulator` module SHALL NOT depend on any external trading framework (backtrader, vectorbt, zipline, etc.). Only stdlib, numpy, and pandas are permitted.

#### Scenario: Import isolation
- **WHEN** `bar_simulator` is imported
- **THEN** it SHALL NOT transitively import any trading framework
