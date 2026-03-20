## MODIFIED Requirements

### Requirement: Position dataclass
The system SHALL define a `Position` dataclass tracking an individual open position within the engine. **Position now includes trade direction.**

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

## ADDED Requirements

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
