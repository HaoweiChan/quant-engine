## MODIFIED Requirements

### Requirement: Tab navigation
The dashboard SHALL provide a horizontal primary tab bar with four tabs in lifecycle order: Data Hub, Strategy, Backtest, Trading. The active tab SHALL be indicated by a `#5a8af2` bottom border. Inactive tabs SHALL use `#445` text color. The Strategy tab SHALL contain a secondary tab bar with three sub-tabs: Code Editor, Optimizer, Monte Carlo. The Trading tab SHALL contain a secondary tab bar with four sub-tabs: Accounts, War Room, Blotter, Risk. Secondary tabs SHALL use a lighter visual weight (9px font, `#6B7280` text, subtler border) to differentiate from primary navigation.

#### Scenario: Tab switches page content
- **WHEN** the user clicks a primary tab
- **THEN** the main content area SHALL update to show that tab's content without a full page reload

#### Scenario: Default tab on load
- **WHEN** the dashboard first loads
- **THEN** the Data Hub tab SHALL be active

#### Scenario: Sub-tab navigation within Strategy
- **WHEN** the user clicks the Strategy primary tab
- **THEN** a secondary tab bar SHALL appear with three sub-tabs: Code Editor, Optimizer, Monte Carlo
- **THEN** Code Editor SHALL be the default active sub-tab

#### Scenario: Sub-tab navigation within Trading
- **WHEN** the user clicks the Trading primary tab
- **THEN** a secondary tab bar SHALL appear with four sub-tabs: Accounts, War Room, Blotter, Risk
- **THEN** Accounts SHALL be the default active sub-tab

#### Scenario: Sub-tab preserves state on primary tab switch
- **WHEN** the user selects the Monte Carlo sub-tab under Strategy, switches to Backtest, then switches back to Strategy
- **THEN** the Monte Carlo sub-tab SHALL still be selected

### Requirement: Trading tab structure
The Trading primary tab SHALL contain a secondary `dcc.Tabs` bar with four sub-tabs: Accounts, War Room, Blotter, and Risk. Each sub-tab SHALL render its own sidebar and main content layout. The secondary tab bar SHALL appear below the primary tab bar with visually lighter styling.

#### Scenario: Accounts sub-tab content
- **WHEN** the Accounts sub-tab is active
- **THEN** the page SHALL display the account management interface (account table, add account flow, detail modal for credentials and guards)

#### Scenario: War Room sub-tab content
- **WHEN** the War Room sub-tab is active
- **THEN** the page SHALL display the full war room interface (account overview cards, strategy session monitors, polling controls) with auto-refresh

#### Scenario: Blotter sub-tab content
- **WHEN** the Blotter sub-tab is active
- **THEN** the page SHALL display a unified activity feed table with all fills, signals, and events across all accounts, with filter controls in the sidebar

#### Scenario: Risk sub-tab content
- **WHEN** the Risk sub-tab is active
- **THEN** the page SHALL display aggregated risk monitoring (margin utilization per account, drawdown per session, thresholds, alert history)

## REMOVED Requirements

### Requirement: Live / Paper Trading page
**Reason**: Replaced by the War Room sub-tab which provides the same functionality (equity curve, positions, signals) plus multi-account and multi-strategy support.
**Migration**: All functionality from the Live/Paper page is available in the War Room's Strategy Session Monitor cards. Mock data mode is replaced by `MockGateway`.

### Requirement: Risk Monitor page
**Reason**: Replaced by the Risk sub-tab under Trading, which aggregates risk metrics across all accounts and sessions instead of showing single-account mock data.
**Migration**: Risk metrics are now sourced from live `AccountSnapshot` data via the broker gateway. Alert history integrates with the existing `src/alerting/` module.
