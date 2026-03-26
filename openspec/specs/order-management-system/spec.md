## Purpose

Order Management System (OMS) that sits between Position Engine and Execution Engine. Converts target-level orders into optimally-sliced child orders using TWAP, VWAP, and POV algorithms to minimize market impact and execution costs.

## Requirements

### Requirement: OMS interface
The OMS SHALL expose a method to schedule order execution and return sliced child orders.

```python
@dataclass
class SlicedOrder:
    parent_order: Order
    child_orders: list[ChildOrder]
    algorithm: str
    estimated_impact: float
    schedule: list[datetime]

@dataclass
class ChildOrder:
    order: Order
    scheduled_time: datetime
    slice_pct: float

class OrderManagementSystem:
    def __init__(
        self,
        impact_model: MarketImpactFillModel,
        volume_profile: VolumeProfile | None = None,
        config: OMSConfig | None = None,
    ) -> None: ...

    def schedule(self, orders: list[Order], market_data: dict) -> list[SlicedOrder]: ...
    def is_passthrough(self, order: Order) -> bool: ...
```

#### Scenario: Small order passthrough
- **WHEN** an order's lot size is below the configured `passthrough_threshold` (default: 1% of ADV)
- **THEN** `is_passthrough()` SHALL return `True` and `schedule()` SHALL return a single-child `SlicedOrder` with no slicing

#### Scenario: Large order sliced
- **WHEN** an order's lot size exceeds `passthrough_threshold`
- **THEN** `schedule()` SHALL decompose the order into child orders according to the selected algorithm

### Requirement: TWAP algorithm
The OMS SHALL support Time-Weighted Average Price execution that distributes order quantity evenly across time slices.

#### Scenario: Even time distribution
- **WHEN** TWAP is selected with `n_slices=10` for a 100-lot order
- **THEN** 10 child orders of 10 lots each SHALL be created, evenly spaced across the execution window

#### Scenario: Configurable execution window
- **WHEN** `execution_window_minutes` is set to 30
- **THEN** child orders SHALL be scheduled at regular intervals within a 30-minute window

### Requirement: VWAP algorithm
The OMS SHALL support Volume-Weighted Average Price execution that distributes order quantity proportional to historical volume profile.

#### Scenario: Volume-proportional distribution
- **WHEN** VWAP is selected and the volume profile shows 40% of volume in first half, 60% in second half
- **THEN** child orders SHALL allocate approximately 40% of quantity to the first half and 60% to the second half of the execution window

#### Scenario: Missing volume profile fallback
- **WHEN** no volume profile is available for the instrument
- **THEN** VWAP SHALL fall back to TWAP (even distribution)

### Requirement: POV algorithm
The OMS SHALL support Percentage-of-Volume execution that limits each child order to a configurable fraction of concurrent market volume.

#### Scenario: Volume participation rate
- **WHEN** POV is selected with `participation_rate=0.05` (5% of volume)
- **THEN** each child order SHALL be sized to not exceed 5% of the observed bar volume

#### Scenario: Low volume adaptation
- **WHEN** market volume drops below expected levels
- **THEN** child order sizes SHALL shrink proportionally, extending the total execution time

### Requirement: Algorithm selection
The OMS SHALL automatically select the optimal algorithm based on order characteristics and market conditions.

#### Scenario: Default algorithm selection
- **WHEN** no algorithm is explicitly specified
- **THEN** the OMS SHALL select based on: urgency (market orders -> TWAP), size (> 5% ADV -> VWAP), and market regime (high volatility -> POV)

#### Scenario: Explicit override
- **WHEN** an order's metadata contains `oms_algorithm`
- **THEN** the OMS SHALL use the specified algorithm regardless of auto-selection

### Requirement: OMS configuration
All OMS parameters SHALL be configurable via TOML.

```python
@dataclass
class OMSConfig:
    passthrough_threshold_pct: float = 0.01
    default_algorithm: str = "auto"
    twap_default_slices: int = 10
    vwap_lookback_days: int = 20
    pov_participation_rate: float = 0.05
    max_execution_window_minutes: int = 60
    enabled: bool = True
```

#### Scenario: OMS disabled passthrough
- **WHEN** `oms.enabled` is `False` in config
- **THEN** all orders SHALL pass through unmodified (backward compatible)

#### Scenario: Config from TOML
- **WHEN** OMS is initialized
- **THEN** it SHALL load parameters from the strategy's TOML config file
