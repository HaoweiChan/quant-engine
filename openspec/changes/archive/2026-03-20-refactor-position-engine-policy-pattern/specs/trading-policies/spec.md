## Purpose

Define the strategy policy interfaces and concrete implementations that decouple trading decision logic from position state management. Policies answer "what to do"; the engine answers "how to execute it."

## ADDED Requirements

### Requirement: EntryPolicy ABC
The system SHALL define an `EntryPolicy` abstract base class that decides whether to open a new position.

```python
class EntryPolicy(ABC):
    @abstractmethod
    def should_enter(
        self,
        snapshot: MarketSnapshot,
        signal: MarketSignal | None,
        engine_state: EngineState,
    ) -> EntryDecision | None: ...
```

#### Scenario: Returns None when no entry
- **WHEN** `should_enter()` determines conditions are not met
- **THEN** it SHALL return `None`

#### Scenario: Returns EntryDecision on entry
- **WHEN** `should_enter()` determines conditions are met
- **THEN** it SHALL return an `EntryDecision` with `lots`, `contract_type`, `initial_stop`, and `direction`

#### Scenario: Policy does not mutate state
- **WHEN** `should_enter()` is called
- **THEN** it SHALL NOT modify `engine_state`, `snapshot`, or `signal` — it is a pure query

### Requirement: AddPolicy ABC
The system SHALL define an `AddPolicy` abstract base class that decides whether to add to an existing position.

```python
class AddPolicy(ABC):
    @abstractmethod
    def should_add(
        self,
        snapshot: MarketSnapshot,
        signal: MarketSignal | None,
        engine_state: EngineState,
    ) -> AddDecision | None: ...
```

#### Scenario: Returns None when no add
- **WHEN** `should_add()` determines conditions are not met
- **THEN** it SHALL return `None`

#### Scenario: Returns AddDecision on add
- **WHEN** `should_add()` determines conditions are met
- **THEN** it SHALL return an `AddDecision` with `lots`, `contract_type`, and `move_existing_to_breakeven`

### Requirement: StopPolicy ABC
The system SHALL define a `StopPolicy` abstract base class that computes stop levels.

```python
class StopPolicy(ABC):
    @abstractmethod
    def initial_stop(
        self, entry_price: float, direction: str, snapshot: MarketSnapshot,
    ) -> float: ...

    @abstractmethod
    def update_stop(
        self, position: Position, snapshot: MarketSnapshot, high_history: deque[float],
    ) -> float: ...
```

#### Scenario: initial_stop returns valid level
- **WHEN** `initial_stop()` is called for a long position
- **THEN** it SHALL return a price below `entry_price`

#### Scenario: initial_stop for short position
- **WHEN** `initial_stop()` is called for a short position
- **THEN** it SHALL return a price above `entry_price`

#### Scenario: update_stop returns raw proposed level
- **WHEN** `update_stop()` is called
- **THEN** it SHALL return the raw proposed stop level; the engine is responsible for enforcing the "only move favorably" constraint

### Requirement: EntryDecision dataclass
The system SHALL define an `EntryDecision` dataclass carrying entry intent from policy to engine.

```python
@dataclass
class EntryDecision:
    lots: float
    contract_type: str
    initial_stop: float
    direction: Literal["long", "short"]
    metadata: dict = field(default_factory=dict)
```

#### Scenario: Lots must be positive
- **WHEN** `EntryDecision` is constructed with `lots <= 0`
- **THEN** validation SHALL raise `ValueError`

#### Scenario: Direction is required
- **WHEN** `EntryDecision` is constructed
- **THEN** `direction` SHALL be either `"long"` or `"short"`

### Requirement: AddDecision dataclass
The system SHALL define an `AddDecision` dataclass carrying add-position intent from policy to engine.

```python
@dataclass
class AddDecision:
    lots: float
    contract_type: str
    move_existing_to_breakeven: bool = False
    metadata: dict = field(default_factory=dict)
```

#### Scenario: Lots must be positive
- **WHEN** `AddDecision` is constructed with `lots <= 0`
- **THEN** validation SHALL raise `ValueError`

#### Scenario: Breakeven flag is optional
- **WHEN** `AddDecision` is constructed without `move_existing_to_breakeven`
- **THEN** it SHALL default to `False`

### Requirement: PyramidEntryPolicy
The system SHALL provide a `PyramidEntryPolicy` implementing `EntryPolicy` with the existing pyramid entry logic.

#### Scenario: Strong long signal generates entry
- **WHEN** `should_enter()` is called with `signal.direction > 0` AND `signal.direction_conf > entry_conf_threshold`
- **THEN** it SHALL return an `EntryDecision` with `direction="long"`, lots from `lot_schedule[0]`, and `initial_stop = price - stop_atr_mult * daily_atr`

#### Scenario: Weak signal returns None
- **WHEN** `signal.direction_conf <= entry_conf_threshold`
- **THEN** it SHALL return `None`

#### Scenario: Bearish signal returns None
- **WHEN** `signal.direction <= 0`
- **THEN** it SHALL return `None`

#### Scenario: No signal returns None
- **WHEN** `signal` is `None`
- **THEN** it SHALL return `None`

#### Scenario: Risk scaling by max_loss
- **WHEN** the computed `max_loss_if_stopped` exceeds `max_loss`
- **THEN** lots SHALL be scaled down until within limit, or `None` returned if even `min_lot` exceeds limit

#### Scenario: Halted or rule_only mode
- **WHEN** `engine_state.mode` is `"halted"` or `"rule_only"`
- **THEN** it SHALL return `None`

### Requirement: PyramidAddPolicy
The system SHALL provide a `PyramidAddPolicy` implementing `AddPolicy` with the existing pyramid add logic.

#### Scenario: Add at ATR threshold
- **WHEN** floating profit >= `add_trigger_atr[pyramid_level - 1] * daily_atr` AND `pyramid_level < max_levels`
- **THEN** it SHALL return an `AddDecision` with lots from `lot_schedule[pyramid_level]` and `move_existing_to_breakeven=True`

#### Scenario: Below threshold returns None
- **WHEN** floating profit < trigger threshold
- **THEN** it SHALL return `None`

#### Scenario: Max level reached returns None
- **WHEN** `pyramid_level >= max_levels`
- **THEN** it SHALL return `None`

#### Scenario: Margin headroom check
- **WHEN** `account.margin_ratio > margin_limit * 0.8`
- **THEN** it SHALL return `None`

#### Scenario: Halted mode
- **WHEN** `engine_state.mode` is `"halted"`
- **THEN** it SHALL return `None`

### Requirement: ChandelierStopPolicy
The system SHALL provide a `ChandelierStopPolicy` implementing `StopPolicy` with the existing 3-layer stop logic.

#### Scenario: Initial stop distance
- **WHEN** `initial_stop()` is called for a long position
- **THEN** it SHALL return `entry_price - stop_atr_mult * daily_atr`

#### Scenario: Initial stop for short
- **WHEN** `initial_stop()` is called for a short position
- **THEN** it SHALL return `entry_price + stop_atr_mult * daily_atr`

#### Scenario: Breakeven activation (long)
- **WHEN** `update_stop()` is called AND floating profit > `1 * daily_atr` AND current stop < entry_price
- **THEN** it SHALL propose `entry_price` as the new stop level

#### Scenario: Chandelier trailing (long)
- **WHEN** `update_stop()` is called with a populated `high_history`
- **THEN** it SHALL propose `max(high_history) - trail_atr_mult * daily_atr`

#### Scenario: Returns raw value
- **WHEN** `update_stop()` computes a new stop
- **THEN** it SHALL return the raw value; the engine enforces the ratchet constraint

### Requirement: NoAddPolicy convenience
The system SHALL provide a `NoAddPolicy` that always returns `None`, for strategies that do not add to positions.

#### Scenario: Always returns None
- **WHEN** `should_add()` is called under any conditions
- **THEN** it SHALL return `None`
