## MODIFIED Requirements

### Requirement: Drawdown circuit breaker
Risk Monitor SHALL force liquidation of all open positions and halt trading when realized plus unrealized daily loss reaches 2% of configured AUM.

#### Scenario: Daily loss cap breach triggers liquidation
- **WHEN** computed daily loss is greater than or equal to `0.02 * aum`
- **THEN** `check()` SHALL return `RiskAction.CLOSE_ALL`, execute force-close through broker access, and transition engine mode to `halted`

#### Scenario: Halt persists after liquidation
- **WHEN** liquidation is completed from a daily loss cap breach
- **THEN** the system SHALL remain halted for new entries until manual operator confirmation

#### Scenario: Loss cap configured from runtime config
- **WHEN** Risk Monitor starts
- **THEN** the 2% limit SHALL be loaded from configuration as `daily_loss_limit_pct` with default `0.02`

### Requirement: Price feed staleness detection
Risk Monitor SHALL treat price feed staleness beyond 3 seconds during active TAIFEX session as a critical safety condition.

#### Scenario: Critical stale price feed
- **WHEN** the most recent price data is older than 3 seconds during active trading hours
- **THEN** `check()` SHALL return `RiskAction.HALT_NEW_ENTRIES`, cancel all working entry orders, and emit a critical alert

#### Scenario: Feed stale while holding positions
- **WHEN** feed staleness exceeds 3 seconds and there are open positions
- **THEN** the monitor SHALL keep protective exits enabled while blocking new entries and SHALL escalate alert severity

#### Scenario: Recovery from stale feed
- **WHEN** feed freshness returns within threshold for a continuous recovery window
- **THEN** the system SHALL remain in guarded mode and require manual confirmation before re-enabling new entries
