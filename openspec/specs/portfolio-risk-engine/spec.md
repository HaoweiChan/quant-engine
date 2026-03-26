## Purpose

Portfolio-level risk engine providing pre-trade exposure limits, Value-at-Risk (VaR) calculations, factor exposure monitoring, and margin stress testing.

## Requirements

### Requirement: Pre-trade risk matrix
The risk engine SHALL enforce configurable pre-trade limits on every order.

```python
@dataclass
class PreTradeRiskConfig:
    max_gross_exposure_pct: float = 0.80
    max_adv_participation_pct: float = 0.05
    max_beta_absolute: float = 2.0
    max_concentration_pct: float = 0.50
    max_var_pct: float = 0.05
    enabled: bool = True

@dataclass
class PreTradeResult:
    approved: bool
    violations: list[str]
    risk_metrics: dict[str, float]
```

#### Scenario: Order within all limits
- **WHEN** all risk limits are satisfied
- **THEN** `PreTradeResult.approved` SHALL be `True`

#### Scenario: Gross exposure breach
- **WHEN** total gross exposure would exceed `max_gross_exposure_pct × equity`
- **THEN** order SHALL be rejected with `"gross_exposure_exceeded"`

#### Scenario: VaR limit breach
- **WHEN** post-trade 1-day VaR would exceed `max_var_pct × equity`
- **THEN** order SHALL be rejected with `"var_limit_exceeded"`

#### Scenario: Concentration breach
- **WHEN** single instrument exceeds `max_concentration_pct` of portfolio
- **THEN** order SHALL be rejected with `"concentration_exceeded"`

#### Scenario: Pre-trade disabled
- **WHEN** `enabled` is `False`
- **THEN** all orders SHALL be approved

### Requirement: Parametric VaR engine
The risk engine SHALL compute VaR using variance-covariance method at both 1-day and 10-day horizons.

```python
@dataclass
class VaRResult:
    var_99_1d: float
    var_95_1d: float
    var_99_10d: float
    var_95_10d: float
    expected_shortfall_99: float
    position_var: dict[str, float]
    correlation_matrix: list[list[float]] | None
    timestamp: datetime

class VaREngine:
    def __init__(self, lookback_days: int = 252) -> None: ...
    def compute(self, positions: list[Position], returns: dict[str, list[float]]) -> VaRResult: ...
    def compute_incremental(self, new_order: Order, current_var: VaRResult) -> float: ...
```

#### Scenario: Single-instrument VaR
- **WHEN** portfolio has one instrument with annualized volatility σ
- **THEN** 99% 1-day VaR SHALL equal `position_value × σ/√252 × 2.326`

#### Scenario: 10-day VaR from 1-day
- **WHEN** 10-day VaR is computed
- **THEN** it SHALL equal `1-day VaR × √10` (parametric scaling)

#### Scenario: Multi-instrument VaR
- **WHEN** portfolio has multiple instruments
- **THEN** VaR SHALL account for correlation matrix

#### Scenario: Incremental VaR
- **WHEN** `compute_incremental()` is called
- **THEN** it SHALL return marginal VaR from adding the order without full matrix recomputation

#### Scenario: Insufficient history
- **WHEN** fewer than 30 daily returns are available
- **THEN** VaR SHALL use `2 × ATR-based volatility` as conservative fallback with warning flag

### Requirement: Historical VaR crosscheck
Run as daily batch; alert on divergence from parametric.

#### Scenario: Daily batch
- **WHEN** daily job runs
- **THEN** it SHALL compute 99% HVaR from actual return distribution

#### Scenario: Divergence alert
- **WHEN** HVaR differs from parametric VaR by >30%
- **THEN** alert SHALL be emitted with both values

### Requirement: Margin stress testing
Configurable stress scenarios for margin and volatility extremes.

#### Scenario: Margin doubling
- **WHEN** stress test runs with margin 2×
- **THEN** report SHALL show whether account faces margin call

#### Scenario: Volatility spike (3×)
- **WHEN** stress test inflates volatility 3×
- **THEN** report SHALL show new VaR level

#### Scenario: Correlation breakdown
- **WHEN** all correlations set to 1.0
- **THEN** report SHALL show undiversified VaR

### Requirement: Factor exposure tracking
Track portfolio beta relative to benchmark.

#### Scenario: Beta computation
- **WHEN** positions are evaluated
- **THEN** aggregate portfolio beta vs benchmark SHALL be computed

#### Scenario: Beta limit enforcement
- **WHEN** beta exceeds `max_beta_absolute`
- **THEN** pre-trade check SHALL reject orders increasing beta

#### Scenario: TAIFEX Phase 1
- **WHEN** single TAIFEX instrument
- **THEN** TAIEX SHALL be the benchmark
