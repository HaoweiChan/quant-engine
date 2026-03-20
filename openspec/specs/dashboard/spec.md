## Purpose

A Dash-based monitoring and analysis dashboard for the quant engine. Organized into five lifecycle-ordered tabs — Data Hub, Strategy, Backtest, Optimization, Trading — with sub-navigation for multi-view tabs. Renders dark-themed charts, stat cards, and data tables for market data browsing/export, in-browser strategy editing, backtesting, parameter grid search, Monte Carlo simulation, live/paper trading, and risk monitoring.

## Requirements

### Requirement: Dark terminal color palette
The dashboard SHALL render on a deep navy background (`#07071a`) with a darker sidebar (`#09091e`) and card surfaces (`#0a0a22`). All text SHALL default to `#ccc`. Labels and decorators SHALL use `#556`. Accent colors SHALL follow: profit/gain `#69f0ae`, loss/stop `#ff5252`, price line `#5a8af2`, entry signals `#4fc3f7`, pyramid adds `#ce93d8`, W/L ratio `#ffd54f`.

#### Scenario: Page loads with correct background
- **WHEN** the user opens the dashboard URL
- **THEN** the browser viewport background SHALL be `#07071a` with no white flash

#### Scenario: Chart surfaces use card color
- **WHEN** any chart is rendered
- **THEN** its paper and plot background SHALL be `#0a0a22` with grid lines `#111130`

### Requirement: Typography from Google Fonts
The dashboard SHALL load IBM Plex Serif (headings), IBM Plex Sans (body text), and JetBrains Mono (all numeric values, labels, stat cards) from Google Fonts via `app.index_string`. Fonts SHALL fall back to system monospace / sans-serif if Google Fonts is unreachable.

#### Scenario: Stat card values use monospace font
- **WHEN** a stat card is displayed
- **THEN** the value SHALL use JetBrains Mono and the label SHALL be uppercase with letter-spacing 1px

#### Scenario: Page headings use serif font
- **WHEN** the dashboard header is rendered
- **THEN** the title "Quant Engine Dashboard" SHALL use IBM Plex Serif at 17px weight 600

### Requirement: Tab navigation
The dashboard SHALL provide a horizontal primary tab bar with five tabs in lifecycle order: Data Hub, Strategy, Backtest, Optimization, Trading. The active tab SHALL be indicated by a `#5a8af2` bottom border. Inactive tabs SHALL use `#445` text color. The Optimization and Trading tabs SHALL each contain a secondary tab bar for sub-navigation. Secondary tabs SHALL use a lighter visual weight (9px font, `#6B7280` text, subtler border) to differentiate from primary navigation.

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

### Requirement: Stat card component
Every page that displays metrics SHALL render them as stat cards arranged in a horizontal flex row. Each card SHALL have: an uppercase label in `#445` at 7px, a colored value at 15px weight 700 in JetBrains Mono, and an optional sub-label in `#444` at 7px. Card background SHALL be `#0d0d26` with border `1px solid #1a1a38` and `border-radius: 5px`.

#### Scenario: Positive value shown in green
- **WHEN** a stat card displays a positive P&L value
- **THEN** the value color SHALL be `#69f0ae`

#### Scenario: Negative value shown in red
- **WHEN** a stat card displays a negative P&L value
- **THEN** the value color SHALL be `#ff5252`

### Requirement: Dark Plotly charts
All charts SHALL use a shared Plotly layout base with: `paper_bgcolor` and `plot_bgcolor` set to `#0a0a22`, grid lines `#111130`, axis lines `#1a1a30`, tick font JetBrains Mono at 8px `#444`. Line charts SHALL use `#5a8af2` for price and `#69f0ae` for equity/return curves. Area charts for drawdown SHALL use a red fill `rgba(255,82,82,0.15)`. Bar charts for distribution SHALL color bars green for positive bins and red for negative bins.

#### Scenario: Equity curve chart appearance
- **WHEN** the equity curve chart renders on Live/Paper or Backtest
- **THEN** the line stroke SHALL be `#69f0ae` and background SHALL be `#0a0a22`

#### Scenario: Drawdown area chart appearance
- **WHEN** the drawdown chart renders
- **THEN** the filled area SHALL use a red-tinted gradient and values SHALL be negative percentages

#### Scenario: Return distribution bar chart
- **WHEN** the return distribution histogram renders
- **THEN** bins with midpoint >= 0 SHALL be `#1a5a3a` and bins with midpoint < 0 SHALL be `#5a1a1a`

### Requirement: Dark data tables
All tabular data SHALL be rendered with `dash_table.DataTable` using dark styling: header background `#131332`, header text `#556` at 9px, cell background `#0a0a22`, cell text `#ccc` at 9px, border color `#1e1e40`, JetBrains Mono font. Tables SHALL fill container width and hide the index column.

#### Scenario: Trade log table renders with dark theme
- **WHEN** the trade log table is displayed
- **THEN** rows SHALL alternate between `#0a0a22` and `#0e0e28` backgrounds with no light-colored borders

#### Scenario: Table is scrollable for large datasets
- **WHEN** a table has more rows than the visible area
- **THEN** the table SHALL scroll vertically within a fixed-height container

### Requirement: Left sidebar for page controls
The dashboard SHALL have a left sidebar of 234px width with `#09091e` background. The sidebar SHALL contain page-specific controls (date pickers, dropdowns, number inputs, action buttons). Sidebar section labels SHALL be uppercase at 8px JetBrains Mono `#445` with `letter-spacing: 1.5px`. Input fields SHALL have `#12122a` background, `#222248` border, `#ccc` text, and JetBrains Mono font.

#### Scenario: Sidebar controls update main content
- **WHEN** the user changes a control in the sidebar (e.g., adjusts Stop ATR Mult)
- **THEN** the corresponding chart or table in the main area SHALL update reactively via Dash callback

#### Scenario: Sidebar is visible on all pages
- **WHEN** any tab is active
- **THEN** the left sidebar SHALL remain visible at 234px width

### Requirement: Data Hub page
The Data Hub page SHALL consolidate market data browsing, CSV export, and Sinopac crawling into a single view. The sidebar SHALL contain: a contract dropdown (showing TAIFEX futures with display name and description), timeframe selector (1 min / 5 min / 15 min / 1 hour / 1 day), date range inputs (From/To), a "Preview & Download" button for CSV export, and a "Crawl from Sinopac" section with crawl contract/date-range inputs and a "Start Crawl" button. The main area SHALL display: a database coverage summary, 5 stat cards (First Bar, Last Bar, Latest Close, Period Return, Avg Volume), a price close line chart, a High/Low dual-line chart, a Volume bar chart, a raw data table (last 100 bars), and export preview/download sections.

#### Scenario: No database file present
- **WHEN** `taifex_data.db` does not exist
- **THEN** the page SHALL display an error card with the database path and a message to use the Crawl section

#### Scenario: Data loads and charts render
- **WHEN** valid contract/timeframe/date range is selected and data exists
- **THEN** all charts SHALL render with the dark Plotly theme and stat cards SHALL populate

#### Scenario: Export preview and download
- **WHEN** the user clicks "Preview & Download"
- **THEN** the main area SHALL show a close preview chart, bar count stats, a sample data table (last 50 bars), and a download button for the CSV file

#### Scenario: Crawl progress display
- **WHEN** the user clicks "Start Crawl"
- **THEN** a crawl console SHALL appear in the main area showing real-time progress, status, and log output

#### Scenario: Coverage summary always visible
- **WHEN** the Data Hub page loads
- **THEN** the database coverage summary SHALL be visible at the top of the main area

### Requirement: Live / Paper Trading page
The Live/Paper page (sub-tab under Trading) SHALL display: 4 stat cards (Equity, Unrealized PnL, Drawdown, Engine Mode), an equity curve chart, a current positions table, a current signal JSON display, and a recent trades table. The page SHALL auto-refresh on a `dcc.Interval` every 30 seconds (using mock data in dev mode).

#### Scenario: Equity metric shows delta
- **WHEN** the Live/Paper page renders
- **THEN** the Equity stat card SHALL show the current equity value and the day-over-day change as a sub-label

#### Scenario: Engine mode badge
- **WHEN** the Engine Mode stat card renders
- **THEN** its color SHALL be `#4fc3f7` to indicate informational status

### Requirement: Backtest page
The Backtest page SHALL expose position engine settings in the sidebar (Max Pyramid Levels, Stop ATR Mult, Trail ATR Mult, Add Trigger ATR, Margin Limit, Kelly Fraction, Entry Conf Threshold, Max Loss, Re-Entry Strategy). It SHALL display 5 performance metric stat cards (Sharpe, Max Drawdown, Win Rate, Total Trades, Total PnL), an equity curve chart, a drawdown area chart, a return distribution histogram, and a trade log table.

#### Scenario: Run Backtest button
- **WHEN** the user clicks "Run Backtest"
- **THEN** the charts and metrics SHALL update based on the current sidebar parameter values

#### Scenario: Total PnL colored by sign
- **WHEN** total PnL is positive
- **THEN** the stat card value SHALL be `#69f0ae`; when negative it SHALL be `#ff5252`

### Requirement: Grid Search page
The Grid Search page (sub-tab under Optimization) SHALL allow selecting X-axis and Y-axis parameters from the 7 position engine parameters. It SHALL expose search range controls (min, max, steps) for each axis and a MC sims/cell input. A metric selector (E[Return %], Sharpe, Win Rate %, Std Dev) SHALL control the heatmap coloring. The heatmap SHALL use green for positive Sharpe/Return values and red for negative, with white text and hover details. Best and Worst cells SHALL be highlighted in annotated cards.

#### Scenario: Heatmap cell hover
- **WHEN** the user hovers over a heatmap cell
- **THEN** a tooltip SHALL display Δ, λ, E[Ret], Win Rate, and Sharpe for that cell

#### Scenario: Metric selector updates heatmap
- **WHEN** the user selects a different metric
- **THEN** the heatmap color scale SHALL update without re-running the simulation

### Requirement: Monte Carlo page
The Monte Carlo page (sub-tab under Optimization) SHALL expose Number of Paths (100–5000), Simulation Days (30–504), and Scenario selector. It SHALL display: a sample paths line chart (max 50 paths), a PnL distribution histogram, 4 stat cards (Median PnL, P5, P95, P(Loss)), and a percentile table.

#### Scenario: Sample paths chart
- **WHEN** 1000 paths are simulated
- **THEN** up to 50 paths SHALL be displayed on the chart with `rgba(90,138,242,0.3)` semi-transparent stroke

#### Scenario: Distribution histogram sign-coloring
- **WHEN** the PnL distribution histogram renders
- **THEN** bins with positive midpoints SHALL be `#1a5a3a` and negative bins SHALL be `#5a1a1a`

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

### Requirement: Risk Monitor page
The Risk Monitor page (sub-tab under Trading) SHALL display 4 stat cards (Margin Ratio, Drawdown, Max Loss Limit, Engine Mode), a drawdown over time area chart, a margin ratio history line chart with threshold reference line at 30%, a risk thresholds table, and an alert history table.

#### Scenario: Margin ratio threshold reference line
- **WHEN** the margin ratio chart renders
- **THEN** a dashed reference line SHALL appear at y=0.30 in `#ff5252` color

#### Scenario: Alert action color coding
- **WHEN** the alert history table renders
- **THEN** rows with Action "CLOSE_ALL" or "REDUCE_HALF" SHALL have a red-tinted cell background; "NORMAL" rows SHALL have green-tinted
