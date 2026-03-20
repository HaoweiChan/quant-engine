## Purpose

Define the shared, market-agnostic data types that form the contracts between all modules in the quant engine. These types enforce the one-way signal flow and ensure every module communicates through well-defined interfaces.

## Requirements

### Requirement: MarketSnapshot dataclass
The system SHALL define a `MarketSnapshot` dataclass as the universal, market-agnostic input to Position Engine. Every market adapter produces this type from raw broker data.

```python
@dataclass
class MarketSnapshot:
    price: float
    atr: dict[str, float]       # {"daily": ..., "hourly": ..., "5m": ...}
    timestamp: datetime
    margin_per_unit: float      # from adapter config
    point_value: float          # from adapter config
    min_lot: float              # 1 for futures, 0.001 for crypto
    contract_specs: ContractSpecs
```

#### Scenario: Construct from adapter output
- **WHEN** a market adapter calls `to_snapshot()` on raw broker data
- **THEN** the returned `MarketSnapshot` SHALL have all fields populated with non-null values and `atr` SHALL contain at least a `"daily"` key

#### Scenario: Reject invalid price
- **WHEN** `price` is zero or negative
- **THEN** construction SHALL raise `ValueError`

#### Scenario: Reject missing daily ATR
- **WHEN** `atr` dict does not contain a `"daily"` key
- **THEN** construction SHALL raise `ValueError`

### Requirement: MarketSignal dataclass
The system SHALL define a `MarketSignal` dataclass as the sole output of Prediction Engine and the sole external signal input to Position Engine.

```python
@dataclass
class MarketSignal:
    timestamp: datetime
    direction: float            # -1.0 (strong short) to +1.0 (strong long)
    direction_conf: float       # 0.0 to 1.0
    regime: str                 # "trending" | "choppy" | "volatile" | "uncertain"
    trend_strength: float       # 0.0 to 1.0
    vol_forecast: float         # predicted N-day volatility in points
    suggested_stop_atr_mult: float | None
    suggested_add_atr_mult: float | None
    model_version: str
    confidence_valid: bool      # False → Position Engine must use rule-only mode
```

#### Scenario: Valid direction range
- **WHEN** a `MarketSignal` is constructed
- **THEN** `direction` SHALL be in range `[-1.0, 1.0]` and `direction_conf` SHALL be in range `[0.0, 1.0]`

#### Scenario: Invalid confidence forces rule-only
- **WHEN** `confidence_valid` is `False`
- **THEN** Position Engine SHALL treat this signal as absent and operate in `rule_only` mode

#### Scenario: Regime value validation
- **WHEN** `regime` is set to a value outside `{"trending", "choppy", "volatile", "uncertain"}`
- **THEN** construction SHALL raise `ValueError`

### Requirement: Order dataclass
The system SHALL define an `Order` dataclass as the output of Position Engine and input to Execution Engine.

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
    reason: str                 # "entry" | "add_level_2" | "stop_loss" | "trailing_stop" | "circuit_breaker"
    metadata: dict              # arbitrary context for logging
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

### Requirement: ContractSpecs dataclass
The system SHALL define a `ContractSpecs` dataclass containing market-specific contract details, provided by each Adapter. All values are loaded from adapter configuration — no hardcoded market-specific defaults.

```python
@dataclass
class ContractSpecs:
    symbol: str
    exchange: str
    currency: str
    point_value: float          # currency value per point, from adapter config
    margin_initial: float
    margin_maintenance: float
    min_tick: float
    trading_hours: TradingHours
    fee_per_contract: float
    tax_rate: float             # market-specific, from adapter config
    lot_types: dict[str, float] # abstract lot type → point value, from adapter config
```

#### Scenario: Lot types mapping
- **WHEN** a `ContractSpecs` is constructed
- **THEN** `lot_types` SHALL contain at least one entry mapping an abstract lot type name to its point value

#### Scenario: Margin values
- **WHEN** `margin_initial` or `margin_maintenance` is zero or negative
- **THEN** construction SHALL raise `ValueError`

### Requirement: PyramidConfig dataclass
The system SHALL define a `PyramidConfig` dataclass holding all tunable parameters for the Position Engine's pyramid strategy. The `max_loss` field SHALL have no default value and MUST be explicitly provided.

```python
@dataclass
class PyramidConfig:
    max_levels: int = 4
    add_trigger_atr: list[float] = field(default_factory=lambda: [4.0, 8.0, 12.0])
    lot_schedule: list[list[int]] = field(
        default_factory=lambda: [[3, 4], [2, 0], [1, 4], [1, 4]]
    )
    stop_atr_mult: float = 1.5
    trail_atr_mult: float = 3.0
    trail_lookback: int = 22
    margin_limit: float = 0.50
    kelly_fraction: float = 0.25
    entry_conf_threshold: float = 0.65
    max_loss: float             # no default — must be explicitly configured
```

#### Scenario: Default config is valid
- **WHEN** `PyramidConfig` is constructed with defaults (except `max_loss` which must be provided)
- **THEN** `len(add_trigger_atr)` SHALL equal `max_levels - 1` and `len(lot_schedule)` SHALL equal `max_levels`

#### Scenario: Lot schedule consistency
- **WHEN** `lot_schedule` has fewer entries than `max_levels`
- **THEN** validation SHALL raise `ValueError`

#### Scenario: max_loss must be positive
- **WHEN** `max_loss` is zero or negative
- **THEN** validation SHALL raise `ValueError`

### Requirement: AccountState dataclass
The system SHALL define an `AccountState` dataclass representing broker account status, read by Risk Monitor.

```python
@dataclass
class AccountState:
    equity: float
    unrealized_pnl: float
    realized_pnl: float
    margin_used: float
    margin_available: float
    margin_ratio: float         # margin_used / equity
    drawdown_pct: float         # (peak_equity - equity) / peak_equity
    positions: list[Position]
    timestamp: datetime
```

#### Scenario: Margin ratio derivation
- **WHEN** `AccountState` is constructed
- **THEN** `margin_ratio` SHALL equal `margin_used / equity` (within floating-point tolerance)

#### Scenario: Drawdown percentage range
- **WHEN** `AccountState` is constructed
- **THEN** `drawdown_pct` SHALL be in range `[0.0, 1.0]`

### Requirement: Position dataclass
The system SHALL define a `Position` dataclass tracking an individual open position within the engine. Position includes trade direction.

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
```

#### Scenario: Position tracks entry and stop
- **WHEN** a `Position` is created
- **THEN** it SHALL contain `entry_price`, `lots`, `contract_type`, `stop_level`, `pyramid_level`, `entry_timestamp`, and `direction`

#### Scenario: Stop level required
- **WHEN** `stop_level` is `None` on an open position
- **THEN** validation SHALL raise `ValueError`

#### Scenario: Direction defaults to long
- **WHEN** `Position` is constructed without explicit `direction`
- **THEN** `direction` SHALL default to `"long"`

#### Scenario: Direction validation
- **WHEN** `Position` is constructed with `direction` not in `{"long", "short"}`
- **THEN** validation SHALL raise `ValueError`

### Requirement: EngineConfig dataclass
The system SHALL define an `EngineConfig` dataclass holding engine-level parameters that are strategy-agnostic.

```python
@dataclass
class EngineConfig:
    max_loss: float
    margin_limit: float = 0.50
    trail_lookback: int = 22
```

#### Scenario: max_loss must be positive
- **WHEN** `EngineConfig` is constructed with `max_loss <= 0`
- **THEN** validation SHALL raise `ValueError`

#### Scenario: margin_limit range
- **WHEN** `EngineConfig` is constructed
- **THEN** `margin_limit` SHALL be in range `(0.0, 1.0]`

### Requirement: EngineState dataclass
The system SHALL define an `EngineState` dataclass representing the read-only snapshot of Position Engine's internal state.

#### Scenario: State exposes positions and mode
- **WHEN** `PositionEngine.get_state()` is called
- **THEN** the returned `EngineState` SHALL contain `positions: list[Position]`, `pyramid_level: int`, `mode: str`, and `total_unrealized_pnl: float`

### Requirement: RiskAction enum
The system SHALL define a `RiskAction` enum with values: `NORMAL`, `REDUCE_HALF`, `HALT_NEW_ENTRIES`, `CLOSE_ALL`.

```python
class RiskAction(Enum):
    NORMAL = "normal"
    REDUCE_HALF = "reduce_half"
    HALT_NEW_ENTRIES = "halt_new_entries"
    CLOSE_ALL = "close_all"
```

#### Scenario: Enum members
- **WHEN** `RiskAction` is used
- **THEN** it SHALL have exactly four members: `NORMAL`, `REDUCE_HALF`, `HALT_NEW_ENTRIES`, `CLOSE_ALL`

### Requirement: One-way signal dependency
Core types SHALL enforce that `MarketSignal` has no reference to `Position`, `AccountState`, or any position-related type. The signal flow is strictly one-way: Prediction Engine → Position Engine.

#### Scenario: Signal is position-agnostic
- **WHEN** a `MarketSignal` is constructed
- **THEN** it SHALL contain only prediction-derived fields (direction, regime, volatility, confidence) and SHALL NOT reference any position, PnL, or account data
