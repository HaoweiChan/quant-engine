## MODIFIED Requirements

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
