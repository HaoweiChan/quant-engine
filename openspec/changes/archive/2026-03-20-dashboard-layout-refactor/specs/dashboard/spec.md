## MODIFIED Requirements

### Requirement: Tab navigation
The dashboard SHALL provide a horizontal primary tab bar with four tabs: Data Hub, Backtest, Optimization, Trading. The active tab SHALL be indicated by a `#5a8af2` bottom border. Inactive tabs SHALL use `#445` text color. The Optimization and Trading tabs SHALL each contain a secondary tab bar for sub-navigation. Secondary tabs SHALL use a lighter visual weight (smaller font, subtler styling) to differentiate from primary navigation.

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

### Requirement: Historical Data page
The Historical Data page is replaced by the Data Hub page. See "Data Hub page" under ADDED Requirements.

## ADDED Requirements

### Requirement: Data Hub page
The Data Hub page SHALL consolidate market data browsing, CSV export, and Sinopac crawling into a single view. The sidebar SHALL contain: a contract dropdown (showing TAIFEX futures with display name and description), timeframe selector (1 min / 5 min / 15 min / 1 hour / 1 day), date range inputs (From/To), a "Preview & Download" button for CSV export, a separator, and a "Crawl from Sinopac" section with contract/date-range inputs and a "Start Crawl" button. The main area SHALL display: a database coverage summary (per-symbol bar counts and date ranges), 5 stat cards (First Bar, Last Bar, Latest Close, Period Return, Avg Volume), a price close line chart, a High/Low dual-line chart, a Volume bar chart, a raw data table (last 100 bars), and an export preview section with download button when previewed.

#### Scenario: No database file present
- **WHEN** `taifex_data.db` does not exist
- **THEN** the page SHALL display an error card with the database path and a message to use the Crawl section

#### Scenario: Data loads and charts render
- **WHEN** a valid contract/timeframe/date range is selected and data exists
- **THEN** all charts SHALL render with the dark Plotly theme and stat cards SHALL populate

#### Scenario: Export preview and download
- **WHEN** the user clicks "Preview & Download"
- **THEN** the main area SHALL show a close preview chart, bar count stats, a sample data table (last 50 bars), and a download button for the CSV file

#### Scenario: Crawl progress display
- **WHEN** the user clicks "Start Crawl"
- **THEN** a crawl console SHALL appear in the main area showing real-time progress, status, and log output
- **THEN** the console SHALL poll every 2 seconds until the crawl completes or errors

#### Scenario: Coverage summary always visible
- **WHEN** the Data Hub page loads
- **THEN** the database coverage summary SHALL be visible at the top of the main area regardless of whether charts have been loaded

### Requirement: Optimization tab structure
The Optimization primary tab SHALL contain a secondary `dcc.Tabs` bar with two sub-tabs: Grid Search and Monte Carlo. Each sub-tab SHALL render its own sidebar and main content layout. The secondary tab bar SHALL appear below the primary tab bar with visually lighter styling.

#### Scenario: Grid Search sub-tab content
- **WHEN** the Grid Search sub-tab is active
- **THEN** the page SHALL display the full Grid Search interface (axis parameter selectors, range controls, heatmap, results table) with its own sidebar

#### Scenario: Monte Carlo sub-tab content
- **WHEN** the Monte Carlo sub-tab is active
- **THEN** the page SHALL display the full Monte Carlo interface (path count, simulation days, scenario selector, simulation paths chart, distribution, percentile table) with its own sidebar

### Requirement: Trading tab structure
The Trading primary tab SHALL contain a secondary `dcc.Tabs` bar with two sub-tabs: Live/Paper and Risk Monitor. Each sub-tab SHALL render its own sidebar and main content layout. The secondary tab bar SHALL appear below the primary tab bar with visually lighter styling.

#### Scenario: Live/Paper sub-tab content
- **WHEN** the Live/Paper sub-tab is active
- **THEN** the page SHALL display the full live/paper trading interface (equity, positions, signals, trades) with auto-refresh

#### Scenario: Risk Monitor sub-tab content
- **WHEN** the Risk Monitor sub-tab is active
- **THEN** the page SHALL display the full risk monitoring interface (margin ratio, drawdown, thresholds, alert history)

## REMOVED Requirements

### Requirement: Historical Data page
**Reason**: Merged into the new Data Hub page which consolidates browsing, export, and crawl functionality.
**Migration**: All Historical Data page functionality is preserved in the Data Hub page. The contract dropdown replaces the plain symbol dropdown with richer display names.
