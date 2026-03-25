## MODIFIED Requirements

### Requirement: Risk Monitor interface
Extended with portfolio risk engine access.

```python
class RiskMonitor:
    def __init__(
        self,
        config: RiskConfig,
        portfolio_risk: PortfolioRiskEngine | None = None,
        on_mode_change: Callable[[str], None] | None = None,
        on_force_close: Callable[[], list[Any]] | None = None,
    ) -> None: ...

    def check(self, account: AccountState) -> RiskAction: ...
    def get_portfolio_risk(self) -> VaRResult | None: ...
```

#### Scenario: Check with portfolio risk
- **WHEN** `check()` is called and `portfolio_risk` is available
- **THEN** it SHALL evaluate both operational AND portfolio risk checks

#### Scenario: Portfolio risk optional (backward compatible)
- **WHEN** `portfolio_risk` is `None`
- **THEN** only operational checks SHALL run

## ADDED Requirements

### Requirement: VaR-based risk check
VaR breach SHALL halt new entries.

#### Scenario: VaR limit breach
- **WHEN** 99% 1-day VaR exceeds `max_var_pct × equity`
- **THEN** return `RiskAction.HALT_NEW_ENTRIES`

#### Scenario: VaR check priority
- **WHEN** VaR breaches
- **THEN** it SHALL be priority 4.5 (between spread spike and signal staleness)

### Requirement: Factor exposure check
Beta breach SHALL halt new entries.

#### Scenario: Beta limit breach
- **WHEN** absolute beta exceeds `max_beta_absolute`
- **THEN** return `RiskAction.HALT_NEW_ENTRIES`

### Requirement: Concentration check
Position concentration breach SHALL halt new entries.

#### Scenario: Concentration breach
- **WHEN** single instrument exceeds `max_concentration_pct × equity`
- **THEN** return `RiskAction.HALT_NEW_ENTRIES`

### Requirement: Extended risk config
New portfolio risk thresholds in config.

```python
@dataclass
class RiskConfig:
    # ... existing fields ...
    max_var_pct: float = 0.05
    max_beta_absolute: float = 2.0
    max_concentration_pct: float = 0.50
    portfolio_risk_enabled: bool = False
```

#### Scenario: Disabled by default
- **WHEN** default config
- **THEN** `portfolio_risk_enabled` SHALL be `False`

### Requirement: Risk event enrichment
Events SHALL include portfolio metrics when available.

#### Scenario: Enriched logging
- **WHEN** risk event emitted with portfolio risk available
- **THEN** details SHALL include VaR, beta, and concentration
