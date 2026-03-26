## Purpose

Volume-aware fill simulation that models real market microstructure: spread crossing, market impact (square-root model), partial fills, and configurable latency delays. Replaces the naive `ClosePriceFillModel` as the default backtest fill model.

## Requirements

### Requirement: Square-root market impact model
The fill model SHALL compute market impact using the square-root impact formula: `impact = k * sigma * sqrt(Q / V)` where `k` is a calibration constant, `sigma` is daily volatility, `Q` is order size in contracts, and `V` is average daily volume.

```python
@dataclass
class ImpactParams:
    k: float = 1.0
    sigma_source: str = "daily"
    adv_lookback: int = 20
    spread_bps: float = 1.0
    min_latency_ms: float = 5.0
    max_latency_ms: float = 50.0

class MarketImpactFillModel(FillModel):
    def __init__(self, params: ImpactParams | None = None) -> None: ...
    def simulate(self, order: Order, bar: dict[str, float], timestamp: datetime) -> Fill: ...
    def estimate_impact(self, order_size: float, volatility: float, adv: float) -> float: ...
```

#### Scenario: Impact scales with order size
- **WHEN** an order for 10 contracts is simulated against a bar with ADV=50,000 and sigma=0.015
- **THEN** the impact SHALL be `k * 0.015 * sqrt(10/50000)` applied adversely (added for buys, subtracted for sells)

#### Scenario: Impact scales with volatility
- **WHEN** volatility doubles from sigma=0.01 to sigma=0.02 with the same order size and ADV
- **THEN** the computed impact SHALL approximately double

#### Scenario: Zero-size order has zero impact
- **WHEN** order size Q=0 (edge case)
- **THEN** impact SHALL be 0.0

### Requirement: Spread crossing cost
The fill model SHALL add half-spread crossing cost to every fill. The spread SHALL be sourced from bar data if available, or fall back to a configured default.

#### Scenario: Spread from bar data
- **WHEN** the bar dict contains a `spread` key
- **THEN** the fill model SHALL use `bar["spread"] / 2` as the half-spread cost

#### Scenario: Spread from config fallback
- **WHEN** the bar dict does not contain a `spread` key
- **THEN** the fill model SHALL use `params.spread_bps * bar["close"] / 10000` as the half-spread cost

#### Scenario: Adverse spread direction
- **WHEN** a buy order is filled
- **THEN** the half-spread cost SHALL be added to the fill price
- **WHEN** a sell order is filled
- **THEN** the half-spread cost SHALL be subtracted from the fill price

### Requirement: Latency delay simulation
The fill model SHALL simulate a configurable latency delay between signal generation and order execution.

#### Scenario: Configurable delay range
- **WHEN** `min_latency_ms` and `max_latency_ms` are configured
- **THEN** each simulated fill SHALL have a random latency drawn uniformly from `[min_latency_ms, max_latency_ms]`

#### Scenario: Latency affects fill price
- **WHEN** latency is simulated on a bar with open != close
- **THEN** the fill price SHALL be interpolated between open and close proportional to the latency fraction of the bar duration, adding uncertainty

#### Scenario: Deterministic replay with seed
- **WHEN** a random seed is provided
- **THEN** the latency draws SHALL be reproducible for deterministic backtest replay

### Requirement: Partial fill simulation
The fill model SHALL support partial fills when order size exceeds a configurable fraction of bar volume.

#### Scenario: Full fill within volume
- **WHEN** order size is less than `max_adv_participation * bar["volume"]`
- **THEN** the fill SHALL be complete (fill_qty == order.lots)

#### Scenario: Partial fill exceeds volume threshold
- **WHEN** order size exceeds `max_adv_participation * bar["volume"]`
- **THEN** the fill SHALL be partial, with `fill_qty = max_adv_participation * bar["volume"]` and `remaining_qty = order.lots - fill_qty`

#### Scenario: Zero-volume bar
- **WHEN** `bar["volume"]` is 0 or missing
- **THEN** the fill SHALL be rejected with reason `"no_liquidity"` and fill_qty=0

### Requirement: Enhanced Fill type
The `Fill` dataclass SHALL be extended to carry impact, spread cost, and latency metadata.

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
    latency_ms: float = 0.0
    fill_qty: float = 0.0
    remaining_qty: float = 0.0
    is_partial: bool = False
```

#### Scenario: Backward-compatible fields
- **WHEN** existing code reads `fill.fill_price` and `fill.slippage`
- **THEN** those fields SHALL still be populated (slippage now equals impact + spread_cost + any price movement during latency)

#### Scenario: Impact breakdown available
- **WHEN** a fill is created by `MarketImpactFillModel`
- **THEN** `market_impact`, `spread_cost`, and `latency_ms` SHALL each be individually populated for analysis

### Requirement: Backward compatibility with legacy fill models
The `ClosePriceFillModel` and `OpenPriceFillModel` SHALL continue to work but SHALL be marked as deprecated.

#### Scenario: Legacy model still functional
- **WHEN** `ClosePriceFillModel` is explicitly passed to `BacktestRunner`
- **THEN** it SHALL produce fills at close price as before

#### Scenario: Deprecation warning
- **WHEN** `ClosePriceFillModel` is used
- **THEN** a deprecation warning SHALL be emitted via `warnings.warn()`

#### Scenario: Default changed
- **WHEN** `BacktestRunner` is constructed with `fill_model=None`
- **THEN** it SHALL default to `MarketImpactFillModel()` instead of `ClosePriceFillModel()`
