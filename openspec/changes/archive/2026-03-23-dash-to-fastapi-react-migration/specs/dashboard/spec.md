## REMOVED Requirements

### Requirement: Dark Plotly charts
**Reason**: All charts are replaced by TradingView Lightweight Charts (canvas-rendered, client-side zoom/pan) and Recharts (histograms/heatmaps). Plotly's SVG rendering and server-side callback model are eliminated.
**Migration**: Chart data is served via FastAPI REST endpoints; rendering moves to the React frontend using TradingView Lightweight Charts for financial data and Recharts for statistical visualizations.

### Requirement: Dark data tables
**Reason**: `dash_table.DataTable` is replaced by a React table component (e.g., TanStack Table or shadcn/ui DataTable) with equivalent dark styling.
**Migration**: Table data is served via FastAPI REST endpoints; rendering uses React components with the same dark theme colors.

### Requirement: Dropdown search bar dark theme
**Reason**: Dash `dcc.Dropdown` components with custom dark CSS are replaced by shadcn/ui Select/Combobox components that natively support dark themes via Tailwind CSS.
**Migration**: All dropdown components are reimplemented as shadcn/ui components in the React frontend.

## MODIFIED Requirements

### Requirement: Tab navigation
The dashboard SHALL provide a horizontal primary tab bar with four tabs in lifecycle order: Data Hub, Strategy, Backtest, Trading. The active tab SHALL be indicated by a `#5a8af2` bottom border. Inactive tabs SHALL use `#445` text color. The Strategy tab SHALL contain a secondary tab bar with three sub-tabs: Code Editor, Optimizer, Monte Carlo. The Trading tab SHALL contain a secondary tab bar with four sub-tabs: Accounts, War Room, Blotter, Risk. Secondary tabs SHALL use a lighter visual weight (9px font, `#6B7280` text, subtler border) to differentiate from primary navigation. Tab switching SHALL be handled entirely client-side via React Router or Zustand state with zero server round-trips.

#### Scenario: Tab switches page content
- **WHEN** the user clicks a primary tab
- **THEN** the main content area SHALL update to show that tab's content via client-side routing without any network request

#### Scenario: Default tab on load
- **WHEN** the dashboard first loads
- **THEN** the Data Hub tab SHALL be active

#### Scenario: Sub-tab navigation within Strategy
- **WHEN** the user clicks the Strategy primary tab
- **THEN** a secondary tab bar SHALL appear with sub-tabs: Code Editor, Optimizer, Monte Carlo
- **THEN** Code Editor SHALL be the default active sub-tab

#### Scenario: Sub-tab navigation within Trading
- **WHEN** the user clicks the Trading primary tab
- **THEN** a secondary tab bar SHALL appear with four sub-tabs: Accounts, War Room, Blotter, Risk
- **THEN** Accounts SHALL be the default active sub-tab

#### Scenario: Sub-tab preserves state on primary tab switch
- **WHEN** the user selects the Monte Carlo sub-tab under Strategy, switches to Backtest, then switches back to Strategy
- **THEN** the Monte Carlo sub-tab SHALL still be selected

### Requirement: Left sidebar for page controls
The dashboard SHALL have a left sidebar of 234px width with `#09091e` background. The sidebar SHALL contain page-specific controls (date pickers, dropdowns, number inputs, action buttons). Sidebar section labels SHALL be uppercase at 8px JetBrains Mono `#445` with `letter-spacing: 1.5px`. Input fields SHALL have `#12122a` background, `#222248` border, `#ccc` text, and JetBrains Mono font. All sidebar control interactions that only affect local display state (filter, sort, tab selection) SHALL execute client-side with zero server round-trips.

#### Scenario: Sidebar controls update main content
- **WHEN** the user changes a control in the sidebar
- **THEN** the corresponding chart or table in the main area SHALL update reactively — via local state for display-only changes, or via API call for data-fetching changes

#### Scenario: Sidebar is visible on all pages
- **WHEN** any tab is active
- **THEN** the left sidebar SHALL remain visible at 234px width

### Requirement: Data Hub page
The Data Hub page SHALL consolidate market data browsing, CSV export, and Sinopac crawling into a single view. The sidebar SHALL contain: a contract dropdown, timeframe selector, date range inputs, a "Preview & Download" button, and a crawl section. The main area SHALL display: database coverage summary, stat cards, price chart (TradingView Lightweight Charts), High/Low chart, Volume chart, raw data table, and export sections. OHLCV data SHALL be bulk-loaded in a single API call and cached client-side; subsequent timeframe changes on cached data SHALL be computed locally without additional API calls.

#### Scenario: No database file present
- **WHEN** the `/api/coverage` endpoint returns an empty array
- **THEN** the page SHALL display an error card suggesting the user use the Crawl section

#### Scenario: Data loads and charts render
- **WHEN** valid contract/timeframe/date range is selected and data exists
- **THEN** all charts SHALL render using TradingView Lightweight Charts and stat cards SHALL populate from the cached data

#### Scenario: Export preview and download
- **WHEN** the user clicks "Preview & Download"
- **THEN** the main area SHALL show a close preview chart, bar count stats, a sample data table, and a download button

#### Scenario: Crawl progress display
- **WHEN** the user clicks "Start Crawl"
- **THEN** a crawl console SHALL appear showing real-time progress from `/api/crawl/status`

### Requirement: Backtest page
The Backtest page SHALL expose strategy and parameter selection in the sidebar and display results via TradingView Lightweight Charts (equity curve with buy-and-hold overlay, drawdown area) and Recharts (return distribution histogram). The backtest SHALL be triggered via `POST /api/backtest/run`. Progress SHALL be displayed via loading indicator or WebSocket streaming.

#### Scenario: Run Backtest button
- **WHEN** the user clicks "Run Backtest"
- **THEN** the frontend SHALL POST parameters to the API and render results on response

#### Scenario: Total PnL colored by sign
- **WHEN** total PnL is positive
- **THEN** the stat card value SHALL be `#69f0ae`; when negative it SHALL be `#ff5252`

### Requirement: Strategy tab structure
The Strategy primary tab SHALL contain sub-tabs: Code Editor, Optimizer, and Monte Carlo. Each sub-tab SHALL render its own sidebar and main content. The Code Editor SHALL use a browser-based code editor component (Monaco or CodeMirror). The Optimizer and Monte Carlo SHALL fetch data via API and render results client-side.

#### Scenario: Code Editor sub-tab content
- **WHEN** the Code Editor sub-tab is active
- **THEN** the page SHALL display a file browser sidebar, a code editor component, and a validation panel

#### Scenario: Optimizer sub-tab content
- **WHEN** the Optimizer sub-tab is active
- **THEN** the page SHALL display param grid inputs, heatmap visualization, IS/OOS equity curves, and top-10 results table

#### Scenario: Monte Carlo sub-tab content
- **WHEN** the Monte Carlo sub-tab is active
- **THEN** the page SHALL display path simulation charts, PnL distribution, and percentile tables

### Requirement: Trading tab structure
The Trading primary tab SHALL contain sub-tabs: Accounts, War Room, Blotter, and Risk. The War Room SHALL receive real-time updates via WebSocket push instead of `dcc.Interval` polling. The Blotter and Risk sub-tabs SHALL refresh data via API polling or WebSocket as appropriate.

#### Scenario: Accounts sub-tab content
- **WHEN** the Accounts sub-tab is active
- **THEN** the page SHALL display an account table, add account flow, and detail modal for credentials and guards

#### Scenario: War Room sub-tab content
- **WHEN** the War Room sub-tab is active
- **THEN** the page SHALL display account overview cards, equity sparklines, and strategy session monitors updated in real-time via WebSocket

#### Scenario: Blotter sub-tab content
- **WHEN** the Blotter sub-tab is active
- **THEN** the page SHALL display a unified fill feed table with filter controls

#### Scenario: Risk sub-tab content
- **WHEN** the Risk sub-tab is active
- **THEN** the page SHALL display aggregated risk metrics (margin, drawdown, alerts) updated via WebSocket or API polling
