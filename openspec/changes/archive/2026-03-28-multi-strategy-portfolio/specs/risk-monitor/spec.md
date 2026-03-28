## MODIFIED Requirements

### Requirement: Risk Monitor interface
Risk Monitor SHALL expose `check()`, `set_position_engine_mode()`, `force_close_all()`, and `get_portfolio_risk()` methods. Extended with portfolio risk engine access and combined position limit enforcement.

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
    def set_position_engine_mode(self, mode: str) -> None: ...
    def force_close_all(self) -> None: ...
```

#### Scenario: Periodic check
- **WHEN** `check()` is called with current `AccountState`
- **THEN** it SHALL return a `RiskAction` indicating the appropriate response

#### Scenario: Check with portfolio risk
- **WHEN** `check()` is called and `portfolio_risk` is available
- **THEN** it SHALL evaluate both operational AND portfolio risk checks

#### Scenario: Portfolio risk optional (backward compatible)
- **WHEN** `portfolio_risk` is `None`
- **THEN** only operational checks SHALL run

#### Scenario: Direct mode control
- **WHEN** `set_position_engine_mode()` is called
- **THEN** Position Engine's mode SHALL be updated immediately

#### Scenario: Combined position limit check
- **WHEN** `check()` is called and `config.max_combined_positions` is set
- **THEN** it SHALL sum open positions across ALL strategies bound to the account
- **AND** if total exceeds `max_combined_positions`, return `RiskAction.HALT_NEW_ENTRIES`

#### Scenario: Combined limit not set (backward compatible)
- **WHEN** `config.max_combined_positions` is `None`
- **THEN** combined position limit check SHALL be skipped

### Requirement: Extended risk config
New portfolio risk thresholds in config, extended with combined position limit.

```python
@dataclass
class RiskConfig:
    # ... existing fields ...
    max_var_pct: float = 0.05
    max_beta_absolute: float = 2.0
    max_concentration_pct: float = 0.50
    portfolio_risk_enabled: bool = False
    max_combined_positions: int | None = None  # NEW: max total positions across all strategies
```

#### Scenario: Disabled by default
- **WHEN** default config
- **THEN** `portfolio_risk_enabled` SHALL be `False`

#### Scenario: Combined position limit default
- **WHEN** default config
- **THEN** `max_combined_positions` SHALL be `None` (no limit)

#### Scenario: Combined position limit configured
- **WHEN** `max_combined_positions` is set to 6
- **THEN** risk monitor SHALL reject new entries when total open positions across all strategies on the account reach 6
