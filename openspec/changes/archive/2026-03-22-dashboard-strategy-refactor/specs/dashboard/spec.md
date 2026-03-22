## MODIFIED Requirements

### Requirement: Tab navigation
The dashboard SHALL provide a horizontal primary tab bar with four tabs in lifecycle order: Data Hub, Strategy, Backtest, Trading. The Strategy tab SHALL contain a secondary tab bar with three sub-tabs: Code Editor, Optimizer, Monte Carlo. The Optimization primary tab is removed.

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
- **THEN** a secondary tab bar SHALL appear with two sub-tabs: Live/Paper and Risk Monitor
- **THEN** Live/Paper SHALL be the default active sub-tab

### Requirement: Dropdown search bar dark theme
All Dash dropdown components with search enabled SHALL render the search input with the dashboard's dark background (`INPUT_BG`), dark text color (`TEXT`), and a dark `color-scheme` to suppress browser autofill light backgrounds.

#### Scenario: Search bar matches dark theme
- **WHEN** the user opens a dropdown with a search input
- **THEN** the search input background SHALL be `INPUT_BG` (#1E2130), text color SHALL be `TEXT` (#E0E0E0), and caret SHALL be visible against the dark background

#### Scenario: Browser autofill does not flash white
- **WHEN** the browser applies autofill styling to a dropdown search input
- **THEN** the background SHALL remain dark due to `color-scheme: dark` on the root element

### Requirement: Strategy selector in Optimizer
The Optimizer sub-tab (under Strategy) SHALL include a "Strategy" dropdown in the sidebar that lists all discoverable strategy factories from `src/strategies/`. Each option SHALL display the strategy's human-readable name. Selecting a strategy SHALL load its param grid definition into the sidebar inputs.

#### Scenario: Strategy dropdown populates at startup
- **WHEN** the Optimizer sub-tab loads
- **THEN** the Strategy dropdown SHALL list all strategies discovered from `src/strategies/` via `create_*_engine` factory function pattern

#### Scenario: Selecting a strategy loads its param grid
- **WHEN** the user selects a different strategy from the dropdown
- **THEN** the sidebar param inputs SHALL update to show that strategy's tunable parameters with their default values

#### Scenario: Only one strategy available
- **WHEN** only one strategy factory exists in `src/strategies/`
- **THEN** that strategy SHALL be pre-selected in the dropdown

### Requirement: Save optimized params from results
The Optimizer results view SHALL include a "Save as Default Params" button that writes the best parameter set to a TOML config file. A success or error message SHALL appear after the save.

#### Scenario: Save button appears after optimization
- **WHEN** optimization results are displayed
- **THEN** a "Save as Default Params" button SHALL appear in the best-params section

#### Scenario: Save confirms success
- **WHEN** the user clicks "Save as Default Params"
- **THEN** the TOML file SHALL be written and a green "Saved to configs/<name>.toml" message SHALL appear

#### Scenario: Save shows error on failure
- **WHEN** the TOML write fails (e.g., permission error)
- **THEN** a red error message SHALL appear with the failure reason
