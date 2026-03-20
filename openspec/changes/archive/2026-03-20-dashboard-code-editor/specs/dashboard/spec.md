## MODIFIED Requirements

### Requirement: Tab navigation
The dashboard SHALL provide a horizontal primary tab bar with five tabs: Data Hub, Strategy, Backtest, Optimization, Trading. The active tab SHALL be indicated by a `#5a8af2` bottom border. Inactive tabs SHALL use `#445` text color. The Optimization and Trading tabs SHALL each contain a secondary tab bar for sub-navigation. Secondary tabs SHALL use a lighter visual weight (9px font, `#6B7280` text, subtler border) to differentiate from primary navigation.

#### Scenario: Tab switches page content
- **WHEN** the user clicks a primary tab
- **THEN** the main content area SHALL update to show that tab's content without a full page reload

#### Scenario: Default tab on load
- **WHEN** the dashboard first loads
- **THEN** the Data Hub tab SHALL be active

#### Scenario: Sub-tab navigation within Optimization
- **WHEN** the user clicks the Optimization primary tab
- **THEN** a secondary tab bar SHALL appear with two sub-tabs: Grid Search and Monte Carlo
- **THEN** Grid Search SHALL be the default active sub-tab

#### Scenario: Sub-tab navigation within Trading
- **WHEN** the user clicks the Trading primary tab
- **THEN** a secondary tab bar SHALL appear with two sub-tabs: Live/Paper and Risk Monitor
- **THEN** Live/Paper SHALL be the default active sub-tab

#### Scenario: Sub-tab preserves state on primary tab switch
- **WHEN** the user selects the Monte Carlo sub-tab under Optimization, switches to Backtest, then switches back to Optimization
- **THEN** the Monte Carlo sub-tab SHALL still be selected

#### Scenario: Strategy tab content
- **WHEN** the user clicks the Strategy tab
- **THEN** the main content area SHALL display the code editor interface with file browser sidebar and Ace editor
