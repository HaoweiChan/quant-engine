## MODIFIED Requirements

### Requirement: Order dataclass
The system SHALL define an `Order` dataclass as the output of Position Engine and input to Execution Engine. The dataclass SHALL carry `parent_position_id` and `order_class` fields to support disaster stop lifecycle management.

```python
@dataclass
class Order:
    order_type: str             # "market" | "limit" | "stop"
    side: str                   # "buy" | "sell"
    symbol: str
    contract_type: str          # "large" | "small" | "micro" (abstract)
    lots: float
    price: float | None         # None for market orders
    stop_price: float | None    # for stop orders
    reason: str                 # "entry" | "add_level_2" | "stop_loss" | "trailing_stop" | "circuit_breaker" | "disaster_stop"
    metadata: dict              # arbitrary context for logging
    parent_position_id: str | None = None   # links order to a Position by ID
    order_class: Literal["standard", "disaster_stop", "algo_exit"] = "standard"
```

#### Scenario: Market order price is None
- **WHEN** `order_type` is `"market"`
- **THEN** `price` SHALL be `None`

#### Scenario: Stop order requires stop_price
- **WHEN** `order_type` is `"stop"` and `stop_price` is `None`
- **THEN** construction SHALL raise `ValueError`

#### Scenario: Lots must be positive
- **WHEN** `lots` is zero or negative
- **THEN** construction SHALL raise `ValueError`

#### Scenario: parent_position_id defaults to None
- **WHEN** an `Order` is constructed without `parent_position_id`
- **THEN** `parent_position_id` SHALL be `None` and existing callers SHALL require no change

#### Scenario: order_class defaults to standard
- **WHEN** an `Order` is constructed without `order_class`
- **THEN** `order_class` SHALL default to `"standard"` and existing callers SHALL require no change

#### Scenario: Disaster stop order carries position link
- **WHEN** an `Order` is constructed with `order_class="disaster_stop"` and `parent_position_id="pos-123"`
- **THEN** `parent_position_id` SHALL equal `"pos-123"` and `reason` SHALL equal `"disaster_stop"`

#### Scenario: Algo exit order carries position link
- **WHEN** the PositionEngine emits an exit order with `reason="trailing_stop"` or `reason="stop_loss"`
- **THEN** `order_class` SHALL be `"algo_exit"` and `parent_position_id` SHALL be set to the closing position's ID

### Requirement: Position dataclass
The system SHALL define a `Position` dataclass tracking an individual open position within the engine. Position includes trade direction and a stable unique ID for linking to disaster stops.

```python
@dataclass
class Position:
    entry_price: float
    lots: float
    contract_type: str
    stop_level: float
    pyramid_level: int
    entry_timestamp: datetime
    direction: Literal["long", "short"] = "long"
    position_id: str = field(default_factory=lambda: str(uuid.uuid4()))
```

#### Scenario: Position tracks entry and stop
- **WHEN** a `Position` is created
- **THEN** it SHALL contain `entry_price`, `lots`, `contract_type`, `stop_level`, `pyramid_level`, `entry_timestamp`, `direction`, and `position_id`

#### Scenario: Stop level required
- **WHEN** `stop_level` is `None` on an open position
- **THEN** validation SHALL raise `ValueError`

#### Scenario: Direction defaults to long
- **WHEN** `Position` is constructed without explicit `direction`
- **THEN** `direction` SHALL default to `"long"`

#### Scenario: Direction validation
- **WHEN** `Position` is constructed with `direction` not in `{"long", "short"}`
- **THEN** validation SHALL raise `ValueError`

#### Scenario: position_id is auto-generated UUID
- **WHEN** `Position` is constructed without `position_id`
- **THEN** `position_id` SHALL be a non-empty UUID4 string unique per position

#### Scenario: position_id is stable
- **WHEN** a `Position` is created and later updated (stop moved)
- **THEN** `position_id` SHALL remain unchanged throughout the position's lifetime

### Requirement: EngineConfig dataclass
The system SHALL define an `EngineConfig` dataclass holding engine-level parameters that are strategy-agnostic. The config SHALL include `disaster_atr_mult` and `disaster_stop_enabled` fields for the disaster stop hybrid model.

```python
@dataclass
class EngineConfig:
    max_loss: float
    margin_limit: float = 0.50
    trail_lookback: int = 22
    disaster_atr_mult: float = 4.5          # must exceed stop_atr_mult
    disaster_stop_enabled: bool = False     # gated off by default
```

#### Scenario: max_loss must be positive
- **WHEN** `EngineConfig` is constructed with `max_loss <= 0`
- **THEN** validation SHALL raise `ValueError`

#### Scenario: margin_limit range
- **WHEN** `EngineConfig` is constructed
- **THEN** `margin_limit` SHALL be in range `(0.0, 1.0]`

#### Scenario: disaster_atr_mult must exceed stop_atr_mult
- **WHEN** `EngineConfig.disaster_atr_mult` is validated against `PyramidConfig.stop_atr_mult` at engine construction time
- **THEN** if `disaster_atr_mult <= stop_atr_mult`, construction SHALL raise `ValueError` with message `"disaster_atr_mult must exceed stop_atr_mult"`

#### Scenario: disaster_stop_enabled defaults to False
- **WHEN** `EngineConfig` is constructed without `disaster_stop_enabled`
- **THEN** `disaster_stop_enabled` SHALL default to `False` and no disaster stops SHALL be registered
