## Purpose

Independent watchdog process that reads broker account state and enforces system-wide risk limits. Has the highest execution priority — can unilaterally close positions, halt the engine, or override operating modes via direct broker API access.

## Requirements

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

### Requirement: Independent process
Risk Monitor SHALL run as a separate, independent process. It SHALL NOT import `PositionEngine` or any Prediction Engine code.

#### Scenario: Module isolation
- **WHEN** the Risk Monitor module is loaded
- **THEN** it SHALL NOT import from `core.position_engine`, `prediction/`, or `execution/`

#### Scenario: Direct broker access
- **WHEN** Risk Monitor needs account data
- **THEN** it SHALL read `AccountState` directly from the broker API, not from Position Engine

### Requirement: Drawdown circuit breaker
Risk Monitor SHALL close all positions when drawdown reaches the maximum loss threshold.

#### Scenario: Max drawdown triggers close-all
- **WHEN** `drawdown_pct >= max_loss / capital`
- **THEN** `check()` SHALL return `RiskAction.CLOSE_ALL` and Risk Monitor SHALL execute `force_close_all()` via direct broker API

### Requirement: Margin ratio monitoring
Risk Monitor SHALL reduce positions when margin ratio drops below a safety threshold.

#### Scenario: Low margin triggers reduction
- **WHEN** `margin_ratio < 0.30`
- **THEN** `check()` SHALL return `RiskAction.REDUCE_HALF`

### Requirement: Signal staleness detection
Risk Monitor SHALL degrade Position Engine to rule-only mode when signal data is stale.

#### Scenario: Stale signal
- **WHEN** the most recent `MarketSignal` timestamp is older than 2 hours
- **THEN** Risk Monitor SHALL call `set_position_engine_mode("rule_only")`

### Requirement: Price feed staleness detection
Risk Monitor SHALL halt new entries when the price feed is stale.

#### Scenario: Stale price feed
- **WHEN** the most recent price data is older than 5 minutes during trading hours
- **THEN** `check()` SHALL return `RiskAction.HALT_NEW_ENTRIES`

### Requirement: Anomaly detection
Risk Monitor SHALL detect market anomalies and halt new entries.

#### Scenario: Spread spike anomaly
- **WHEN** bid-ask spread suddenly exceeds a configurable threshold (e.g., 10× normal spread)
- **THEN** `check()` SHALL return `RiskAction.HALT_NEW_ENTRIES`

#### Scenario: Volume collapse anomaly
- **WHEN** trading volume drops to near zero during active trading hours
- **THEN** `check()` SHALL return `RiskAction.HALT_NEW_ENTRIES`

### Requirement: Highest execution priority
Risk Monitor SHALL have the highest execution priority in the system. It is the only module that can unilaterally close positions or halt the system.

#### Scenario: Override Position Engine
- **WHEN** Risk Monitor returns `CLOSE_ALL`
- **THEN** it SHALL force-close all positions via direct broker API, bypassing Position Engine and Execution Engine entirely

#### Scenario: Emergency halt persists
- **WHEN** Risk Monitor sets Position Engine to `"halted"`
- **THEN** only Risk Monitor (or manual intervention) SHALL be able to restore the mode — Position Engine SHALL NOT self-restore

### Requirement: Alert system
Risk Monitor SHALL emit alerts on all risk actions via structured logging and notification channels.

#### Scenario: Risk event logging
- **WHEN** `check()` returns any action other than `NORMAL`
- **THEN** the event SHALL be logged via structlog with full context (account state, action, trigger reason)

#### Scenario: Notification dispatch
- **WHEN** a `CLOSE_ALL` or `HALT_NEW_ENTRIES` action is triggered
- **THEN** an alert SHALL be dispatched via the configured notification channel (e.g., Telegram)

### Requirement: Configurable risk thresholds
All Risk Monitor thresholds SHALL be loaded from configuration, not hardcoded.

#### Scenario: Thresholds from config
- **WHEN** Risk Monitor is constructed
- **THEN** it SHALL load margin_ratio_threshold, signal_staleness_window, feed_staleness_window, spread_spike_multiplier, and max_loss from TOML config

#### Scenario: Override defaults
- **WHEN** a custom config provides different threshold values
- **THEN** Risk Monitor SHALL use those values instead of any hardcoded defaults

### Requirement: Phase 1 async task mode
In Phase 1, Risk Monitor SHALL run as an async task within the same process, with the ability to be extracted to a separate process in Phase 2.

#### Scenario: Async check loop
- **WHEN** Risk Monitor starts in Phase 1 mode
- **THEN** it SHALL run a periodic check loop at a configurable interval (default 30s) as an asyncio task

#### Scenario: Process extraction readiness
- **WHEN** Risk Monitor is designed
- **THEN** its interface SHALL not depend on in-process state -- all inputs come via AccountState and all outputs are RiskAction + mode changes, making future process extraction straightforward

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
