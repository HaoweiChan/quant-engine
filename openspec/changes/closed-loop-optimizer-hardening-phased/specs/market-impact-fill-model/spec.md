## MODIFIED Requirements

### Requirement: Spread crossing cost
The fill model SHALL account for both spread crossing and commission costs on every fill. Spread SHALL be sourced from bar data if available, or fall back to configured defaults; commission SHALL be configurable in basis points or fixed-per-contract terms.

#### Scenario: Spread from bar data
- **WHEN** the bar dict contains a `spread` key
- **THEN** the fill model SHALL use `bar["spread"] / 2` as the half-spread cost component

#### Scenario: Spread from config fallback
- **WHEN** the bar dict does not contain a `spread` key
- **THEN** the fill model SHALL use configured spread basis points to derive half-spread cost

#### Scenario: Commission applied to all fills
- **WHEN** an order fill is simulated
- **THEN** configured commission cost SHALL be applied regardless of side
- **AND** total execution drag SHALL include spread + impact + commission (+ latency effect where applicable)

### Requirement: Enhanced Fill type
The `Fill` dataclass SHALL carry an explicit commission field so optimization and reporting layers can evaluate net-of-cost performance.

```python
@dataclass
class Fill:
    order_type: str
    side: str
    symbol: str
    lots: float
    fill_price: float
    slippage: float
    timestamp: datetime
    reason: str
    market_impact: float = 0.0
    spread_cost: float = 0.0
    commission_cost: float = 0.0
    latency_ms: float = 0.0
    fill_qty: float = 0.0
    remaining_qty: float = 0.0
    is_partial: bool = False
```

#### Scenario: Net cost breakdown available
- **WHEN** a fill is produced by the market-impact model
- **THEN** `market_impact`, `spread_cost`, and `commission_cost` SHALL each be populated for downstream analysis

#### Scenario: Backward-compatible slippage field
- **WHEN** legacy code reads `fill.slippage`
- **THEN** it SHALL remain populated
- **AND** represent the aggregated adverse execution effect across configured cost components
