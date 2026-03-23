## Purpose

A FastAPI-backed, React monitoring and analysis dashboard for the quant engine. Organized into four lifecycle-ordered primary tabs — Data Hub, Strategy, Backtest, Trading — with the Strategy tab containing Code Editor, Optimizer, and Monte Carlo sub-views, and sub-navigation on Trading. Uses TradingView Lightweight Charts and Recharts for visuals, React tables for tabular data, and shadcn/ui for selects. Renders the dark terminal theme (navy surfaces, stat cards) for market data browsing/export, in-browser strategy editing, backtesting, parameter grid search, Monte Carlo simulation, live trading via War Room, and risk monitoring.

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
The dashboard SHALL load IBM Plex Serif (headings), IBM Plex Sans (body text), and JetBrains Mono (all numeric values, labels, stat cards) from Google Fonts (e.g., in the React app `index.html` or equivalent). Fonts SHALL fall back to system monospace / sans-serif if Google Fonts is unreachable.

#### Scenario: Stat card values use monospace font
- **WHEN** a stat card is displayed
- **THEN** the value SHALL use JetBrains Mono and the label SHALL be uppercase with letter-spacing 1px

#### Scenario: Page headings use serif font
- **WHEN** the dashboard header is rendered
- **THEN** the title "Quant Engine Dashboard" SHALL use IBM Plex Serif at 17px weight 600

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
The Optimizer results view SHALL save the full optimization result to the param registry database via the API, replacing the TOML-only save. A success or error message SHALL appear after the save.

#### Scenario: Save button appears after optimization
- **WHEN** optimization results are displayed
- **THEN** a "Save as Default Params" button SHALL appear in the best-params section

#### Scenario: Save persists to registry
- **WHEN** the user clicks "Save as Default Params"
- **THEN** the full optimization result SHALL be persisted to the param registry via the API
- **AND** the best candidate SHALL be activated
- **AND** a green success message SHALL appear with the run ID and candidate count

#### Scenario: Save shows error on failure
- **WHEN** the save fails (e.g., database error)
- **THEN** a red error message SHALL appear with the failure reason

### Requirement: Stat card component
Every page that displays metrics SHALL render them as stat cards arranged in a horizontal flex row. Each card SHALL have: an uppercase label in `#445` at 7px, a colored value at 15px weight 700 in JetBrains Mono, and an optional sub-label in `#444` at 7px. Card background SHALL be `#0d0d26` with border `1px solid #1a1a38` and `border-radius: 5px`.

#### Scenario: Positive value shown in green
- **WHEN** a stat card displays a positive P&L value
- **THEN** the value color SHALL be `#69f0ae`

#### Scenario: Negative value shown in red
- **WHEN** a stat card displays a negative P&L value
- **THEN** the value color SHALL be `#ff5252`

### Requirement: Left sidebar for page controls
The dashboard SHALL have a left sidebar of 234px width with `#09091e` background. The sidebar SHALL contain page-specific controls (date pickers, dropdowns, number inputs, action buttons). Sidebar section labels SHALL be uppercase at 8px JetBrains Mono `#445` with `letter-spacing: 1.5px`. Input fields SHALL have `#12122a` background, `#222248` border, `#ccc` text, and JetBrains Mono font. All sidebar control interactions that only affect local display state (filter, sort, tab selection) SHALL execute client-side with zero server round-trips.

#### Scenario: Sidebar controls update main content
- **WHEN** the user changes a control in the sidebar
- **THEN** the corresponding chart or table in the main area SHALL update reactively — via local state for display-only changes, or via API call for data-fetching changes

#### Scenario: Sidebar is visible on all pages
- **WHEN** any tab is active
- **THEN** the left sidebar SHALL remain visible at 234px width

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

### Requirement: Backtest page
The Backtest page SHALL load the active optimized parameters from the param registry as sidebar defaults when a strategy is selected. It SHALL expose position engine settings in the sidebar (Max Pyramid Levels, Stop ATR Mult, Trail ATR Mult, Add Trigger ATR, Margin Limit, Kelly Fraction, Entry Conf Threshold, Max Loss, Re-Entry Strategy). It SHALL display 5 performance metric stat cards (Sharpe, Max Drawdown, Win Rate, Total Trades, Total PnL), an equity curve chart, a drawdown area chart, a return distribution histogram, and a trade log table. The backtest SHALL be triggered via `POST /api/backtest/run`. Progress SHALL be displayed via loading indicator or WebSocket streaming.

#### Scenario: Sidebar loads optimized params
- **WHEN** the user selects a strategy on the Backtest page
- **THEN** the sidebar parameter inputs SHALL be populated with the active optimized params from the registry
- **AND** if no optimized params exist, it SHALL fall back to PARAM_SCHEMA defaults from `GET /api/strategies`

#### Scenario: Optimized params indicator
- **WHEN** the Backtest sidebar displays params loaded from the registry
- **THEN** a visual indicator (label or badge) SHALL show that the params are from an optimization run, including the run date and objective

#### Scenario: Run Backtest button
- **WHEN** the user clicks "Run Backtest"
- **THEN** the frontend SHALL POST parameters to the API and the charts and metrics SHALL update based on the current sidebar parameter values

#### Scenario: Total PnL colored by sign
- **WHEN** total PnL is positive
- **THEN** the stat card value SHALL be `#69f0ae`; when negative it SHALL be `#ff5252`

### Requirement: Grid Search page
The Grid Search page (Optimizer sub-tab under Strategy) SHALL allow selecting X-axis and Y-axis parameters from the 7 position engine parameters. It SHALL expose search range controls (min, max, steps) for each axis and a MC sims/cell input. A metric selector (E[Return %], Sharpe, Win Rate %, Std Dev) SHALL control the heatmap coloring. The heatmap SHALL use green for positive Sharpe/Return values and red for negative, with white text and hover details. Best and Worst cells SHALL be highlighted in annotated cards.

#### Scenario: Heatmap cell hover
- **WHEN** the user hovers over a heatmap cell
- **THEN** a tooltip SHALL display Δ, λ, E[Ret], Win Rate, and Sharpe for that cell

#### Scenario: Metric selector updates heatmap
- **WHEN** the user selects a different metric
- **THEN** the heatmap color scale SHALL update without re-running the simulation

### Requirement: Monte Carlo page
The Monte Carlo page (sub-tab under Strategy) SHALL expose Number of Paths (100–5000), Simulation Days (30–504), and Scenario selector. It SHALL display: a sample paths line chart (max 50 paths), a PnL distribution histogram, 4 stat cards (Median PnL, P5, P95, P(Loss)), and a percentile table.

#### Scenario: Sample paths chart
- **WHEN** 1000 paths are simulated
- **THEN** up to 50 paths SHALL be displayed on the chart with `rgba(90,138,242,0.3)` semi-transparent stroke

#### Scenario: Distribution histogram sign-coloring
- **WHEN** the PnL distribution histogram renders
- **THEN** bins with positive midpoints SHALL be `#1a5a3a` and negative bins SHALL be `#5a1a1a`

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

### Requirement: Active params API endpoints
The dashboard API SHALL expose endpoints for reading and managing active optimized parameters from the param registry.

#### Scenario: Get active params
- **WHEN** `GET /api/params/active/{strategy}` is called
- **THEN** it SHALL return the currently active candidate's params, label, run metadata, and `activated_at` timestamp
- **AND** if no active candidate exists, it SHALL return PARAM_SCHEMA defaults with `"source": "defaults"`

#### Scenario: Get run history
- **WHEN** `GET /api/params/runs/{strategy}` is called
- **THEN** it SHALL return a list of past optimization runs with `run_id`, `run_at`, `objective`, `best_params`, best metrics summary, `tag`, and candidate count

#### Scenario: Activate a candidate
- **WHEN** `POST /api/params/activate/{candidate_id}` is called
- **THEN** the specified candidate SHALL become active for its strategy
- **AND** the response SHALL confirm the activation with the candidate's params and strategy name

#### Scenario: Invalid candidate ID
- **WHEN** `POST /api/params/activate/{candidate_id}` is called with a non-existent ID
- **THEN** the API SHALL return HTTP 404 with an error message
