## MODIFIED Requirements

### Requirement: Data Hub page
The Data Hub page SHALL consolidate market data browsing, CSV export, and Sinopac crawling into a single view. The sidebar SHALL contain: a contract dropdown (showing TAIFEX futures with display name and description), timeframe selector (1 min / 5 min / 15 min / 1 hour / 1 day), date range inputs (From/To), a "Load Data" button, a dynamic indicator management section with "Add Indicator" capability for overlay indicators, and action buttons (Export CSV, Crawl Data). The main area SHALL display: a database coverage summary, 5 stat cards (First Bar, Last Bar, Latest Close, Period Return, Avg Volume), a synchronized chart stack consisting of a primary OHLC pane (no volume) with overlay indicators and an always-visible secondary chart pane with a dropdown indicator selector (Volume by default) with inline parameter editing, and a raw data table (last 100 bars).

#### Scenario: No database file present
- **WHEN** `taifex_data.db` does not exist
- **THEN** the page SHALL display an error card with the database path and a message to use the Crawl section

#### Scenario: Data loads and charts render
- **WHEN** valid contract/timeframe/date range is selected and data exists
- **THEN** the chart stack SHALL render the primary OHLC pane and any active indicator panes, all with synchronized time scales

#### Scenario: Coverage summary always visible
- **WHEN** the Data Hub page loads
- **THEN** the database coverage summary SHALL be visible at the top of the main area

#### Scenario: Adding an overlay indicator from sidebar
- **WHEN** the user clicks "Add Indicator" and selects "SMA"
- **THEN** an SMA entry SHALL appear in the sidebar indicator list and the SMA line SHALL render on the primary OHLC pane

#### Scenario: Adding a pane indicator from sidebar
- **WHEN** the user clicks "Add Indicator" and selects "RSI"
- **THEN** an RSI entry SHALL appear in the sidebar indicator list and a new RSI pane SHALL appear below the primary pane

#### Scenario: Removing an indicator from sidebar
- **WHEN** the user clicks the remove button next to an active indicator in the sidebar
- **THEN** that indicator SHALL be removed from the chart (overlay removed from price pane, or pane destroyed)

#### Scenario: Editing indicator parameters
- **WHEN** the user clicks the edit control on an active SMA indicator and changes the period from 20 to 50
- **THEN** the SMA overlay on the price pane SHALL re-compute and re-render with period 50

#### Scenario: Export preview and download
- **WHEN** the user clicks "Export CSV"
- **THEN** a CSV file with all loaded bar data SHALL be downloaded

#### Scenario: Crawl progress display
- **WHEN** the user clicks "Crawl Data"
- **THEN** a crawl status indicator SHALL appear in the sidebar showing progress and status
