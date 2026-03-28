## Purpose

Vite + React + TypeScript client for the quant dashboard: dark theme parity with the legacy Dash UI, TradingView Lightweight Charts, Zustand state, WebSocket hooks, and tabbed flows for Data Hub, Strategy, Backtest, and Trading.

## Requirements

### Requirement: Vite + React + TypeScript project scaffold
The frontend SHALL be a Vite-powered React application with TypeScript strict mode, located in `frontend/` at the project root. It SHALL use Tailwind CSS for styling and shadcn/ui for component primitives.

#### Scenario: Development server starts
- **WHEN** the developer runs `npm run dev` in the `frontend/` directory
- **THEN** a Vite dev server SHALL start with hot module replacement on port 5173

#### Scenario: Production build succeeds
- **WHEN** the developer runs `npm run build`
- **THEN** the build SHALL produce optimized static assets in `frontend/dist/` with no TypeScript errors

### Requirement: Dark terminal color palette
The frontend SHALL implement the same dark terminal aesthetic as the current Dash dashboard: deep navy background (`#07071a`), darker sidebar (`#09091e`), card surfaces (`#0a0a22`), text default `#ccc`. All accent colors SHALL match the existing theme (green `#69f0ae`, red `#ff5252`, blue `#5a8af2`, cyan `#4fc3f7`, gold `#ffd54f`).

#### Scenario: Page loads with correct background
- **WHEN** the user opens the frontend URL
- **THEN** the browser viewport background SHALL be `#07071a` with no white flash

#### Scenario: Cards use dark surface color
- **WHEN** any card or chart container renders
- **THEN** its background SHALL be `#0a0a22` with border `1px solid #1a1a38`

### Requirement: Typography from Google Fonts
The frontend SHALL load IBM Plex Serif (headings), IBM Plex Sans (body), and JetBrains Mono (all numeric values, stat cards, labels) from Google Fonts. Fonts SHALL fall back to system fonts if Google Fonts is unreachable.

#### Scenario: Stat card values use monospace
- **WHEN** a stat card is displayed
- **THEN** the value SHALL use JetBrains Mono and the label SHALL be uppercase with letter-spacing

### Requirement: Tab navigation with four primary tabs
The frontend SHALL provide a horizontal tab bar with three primary tabs in lifecycle order: Data Hub, Strategy, Trading. The active tab SHALL show a `#5a8af2` bottom border. The Strategy tab SHALL contain sub-tabs: Code Editor, Tear Sheet, Param Sweep, Stress Test. The Trading tab SHALL contain sub-tabs: Accounts, War Room, Blotter, Risk. A route redirect SHALL map `/backtest` to `/strategy?tab=tearsheet` for backward compatibility.

#### Scenario: Tab switches page content
- **WHEN** the user clicks a primary tab
- **THEN** the page content SHALL update via client-side routing without a full page reload

#### Scenario: Default tab on load
- **WHEN** the frontend first loads
- **THEN** the Data Hub tab SHALL be active

#### Scenario: Sub-tab state preserved across primary tab switches
- **WHEN** the user selects Stress Test under Strategy, switches to Trading, then returns to Strategy
- **THEN** the Stress Test sub-tab SHALL still be selected

#### Scenario: Backtest URL redirects to Tear Sheet
- **WHEN** the user navigates to `/backtest`
- **THEN** the router SHALL redirect to `/strategy?tab=tearsheet` with no 404

### Requirement: TradingView Lightweight Charts for financial data
All OHLCV price charts, equity curves, and drawdown charts SHALL use TradingView Lightweight Charts with canvas rendering. Chart zoom, pan, crosshair, and time range selection SHALL execute entirely client-side with zero server requests.

#### Scenario: Price chart renders with dark theme
- **WHEN** an OHLCV chart renders
- **THEN** the chart background SHALL be `#0a0a22`, grid lines `#111130`, and the price line `#5a8af2`

#### Scenario: Chart zoom and pan are local
- **WHEN** the user zooms or pans a chart
- **THEN** the operation SHALL complete instantly with no network request to the server

#### Scenario: Crosshair shows values
- **WHEN** the user hovers over a chart
- **THEN** a crosshair SHALL display the date, open, high, low, close, and volume for the hovered bar

### Requirement: Client-side indicator calculation
The frontend SHALL calculate technical indicators (MA, EMA, ATR, Bollinger Bands) locally in the browser from loaded OHLCV data. Toggling indicators SHALL NOT trigger a server request.

#### Scenario: Add moving average overlay
- **WHEN** the user enables a 20-period MA overlay on a price chart
- **THEN** the MA line SHALL appear on the chart calculated from the cached OHLCV data with zero server round-trip

#### Scenario: Change indicator parameters
- **WHEN** the user changes the MA period from 20 to 50
- **THEN** the MA line SHALL update instantly from cached data

### Requirement: Zustand state stores
The frontend SHALL use Zustand stores for application state: `marketDataStore` (cached OHLCV, indicators), `backtestStore` (results, progress), `tradingStore` (accounts, sessions, WS connection), `uiStore` (active tabs, sidebar state, filters), and `strategyStore` (global parameter context: strategy, symbol, dates, cost assumptions, full param vector θ).

#### Scenario: OHLCV data cached across tab switches
- **WHEN** the user loads OHLCV data on Data Hub, switches to Strategy, then returns to Data Hub
- **THEN** the previously loaded OHLCV data SHALL still be available without re-fetching

#### Scenario: WebSocket connection state tracked
- **WHEN** the WebSocket connection to `/ws/live-feed` drops
- **THEN** the `tradingStore` SHALL update its `connected` state to `false` and display a disconnection indicator

#### Scenario: Strategy store shared across sub-tabs
- **WHEN** the user changes `symbol` in the global sidebar
- **THEN** all Strategy sub-tabs (Tear Sheet, Param Sweep, Stress Test) SHALL reflect the updated symbol

### Requirement: WebSocket hooks for real-time data
The frontend SHALL provide React hooks (`useLiveFeed`, `useBacktestProgress`, `useRiskAlerts`) that manage WebSocket connections with automatic reconnection using exponential backoff. The `useLiveFeed` hook SHALL process incoming tick messages by calling `processLiveTick()` on `marketDataStore` to drive live bar aggregation and chart updates.

#### Scenario: Auto-reconnect on disconnect
- **WHEN** the WebSocket connection to `/ws/live-feed` is lost
- **THEN** the hook SHALL attempt reconnection with exponential backoff (1s, 2s, 4s, 8s, max 30s)

#### Scenario: Live feed processes tick messages
- **WHEN** a message with `type: "tick"` arrives on the live feed WebSocket containing `{ price, volume, timestamp }`
- **THEN** the `useLiveFeed` hook SHALL call `marketDataStore.processLiveTick({ price, volume, timestamp })`

#### Scenario: Live feed ignores non-tick messages
- **WHEN** a message with `type: "order"` or `type: "pong"` arrives on the live feed WebSocket
- **THEN** the `useLiveFeed` hook SHALL NOT call `processLiveTick`

#### Scenario: Malformed message handling
- **WHEN** a malformed or unparseable message arrives on the live feed WebSocket
- **THEN** the hook SHALL silently ignore the message without throwing or logging to the console

### Requirement: Data Hub page
The Data Hub page SHALL display database coverage, contract/timeframe/date selectors in a sidebar, and render OHLCV charts (price, high/low, volume) with stat cards (First Bar, Last Bar, Latest Close, Period Return, Avg Volume). It SHALL support CSV export and crawl management.

#### Scenario: OHLCV data loads and charts render
- **WHEN** the user selects a contract, timeframe, and date range with available data
- **THEN** all charts SHALL render using TradingView Lightweight Charts and stat cards SHALL populate

#### Scenario: Bulk data load pattern
- **WHEN** the user loads OHLCV data
- **THEN** the full dataset SHALL be fetched in one API call and cached in `marketDataStore`; subsequent timeframe changes SHALL recompute locally when possible

### Requirement: Strategy sub-tabs
The Strategy tab SHALL contain sub-tabs for Code Editor (file browser + code editor), Tear Sheet (single backtest with full metrics, equity curve, drawdown, trade log — formerly the standalone Backtest page), Param Sweep (unified Grid Search + Optimizer with method selector), and Stress Test (block-bootstrap Monte Carlo with VaR/CVaR). All sub-tabs except Code Editor SHALL read parameters from `useStrategyStore`.

#### Scenario: Code editor loads and saves files
- **WHEN** the user selects a file in the Code Editor
- **THEN** the editor SHALL load the file content and support save/revert operations via API calls

#### Scenario: Tear Sheet runs backtest with global params
- **WHEN** the user clicks "Run" on the Tear Sheet tab
- **THEN** the request SHALL use strategy, symbol, dates, params, and cost assumptions from `useStrategyStore`

#### Scenario: Param Sweep selects sweep parameters from global context
- **WHEN** the user opens the Param Sweep tab
- **THEN** the parameter list SHALL show all parameters from `useStrategyStore.params`, allowing the user to mark 1-2 as sweep variables while the rest remain locked at their global values

#### Scenario: Stress Test uses global params for baseline backtest
- **WHEN** the user runs a stress test
- **THEN** the system SHALL first run a baseline backtest using the global param vector, then bootstrap the resulting daily returns

### Requirement: Trading sub-tabs
The Trading tab SHALL contain sub-tabs for Accounts (table + add/edit modal with credential management), War Room (account overview cards + equity sparklines + session monitors with WebSocket updates), Blotter (unified fill feed), and Risk (aggregated margin/drawdown/alerts).

#### Scenario: War Room receives real-time updates
- **WHEN** the War Room tab is active and the `/ws/live-feed` WebSocket is connected
- **THEN** account equity, positions, and session data SHALL update in real-time without polling

#### Scenario: Account modal saves credentials
- **WHEN** the user fills in API credentials and clicks Save in the account modal
- **THEN** the frontend SHALL POST to `/api/accounts` and display success/error feedback

### Requirement: Stat card component
Every page displaying metrics SHALL render them as stat cards in a horizontal flex row. Each card SHALL have an uppercase label, a colored value in JetBrains Mono, and an optional sub-label. Card styling SHALL match the existing dashboard theme (`#0d0d26` background, `#1a1a38` border).

#### Scenario: Positive value shown in green
- **WHEN** a stat card displays a positive P&L value
- **THEN** the value color SHALL be `#69f0ae`

#### Scenario: Negative value shown in red
- **WHEN** a stat card displays a negative P&L value
- **THEN** the value color SHALL be `#ff5252`

### Requirement: Left sidebar for page controls
Each page SHALL have a left sidebar (234px width, `#09091e` background) containing page-specific controls (date pickers, dropdowns, number inputs, action buttons). Sidebar inputs SHALL have dark styling matching the existing theme.

#### Scenario: Sidebar controls update page content
- **WHEN** the user changes a sidebar control
- **THEN** the page content SHALL update reactively via local state or API call as appropriate

### Requirement: Monte Carlo mode selector
The Stress Test sub-tab SHALL provide a mode selector allowing the user to choose the simulation type before running.

#### Scenario: Available modes
- **WHEN** the Stress Test page loads
- **THEN** the mode selector SHALL display options: "Block Bootstrap" (default, existing), "Trade Resampling", "GBM Price Simulation", "Parameter Sensitivity"

#### Scenario: Default mode
- **WHEN** no mode has been selected
- **THEN** "Block Bootstrap" SHALL be pre-selected with the existing method sub-selector (Stationary/Circular/GARCH)

#### Scenario: Mode-specific controls
- **WHEN** the user selects "GBM Price Simulation"
- **THEN** additional controls SHALL appear: "Fat Tails" toggle, "Degrees of Freedom" input (default 5)
- **WHEN** the user selects "Trade Resampling"
- **THEN** an additional "Block Size" input SHALL appear (default 1)
- **WHEN** the user selects "Parameter Sensitivity"
- **THEN** "Perturbation Offsets" multi-select SHALL appear (±5%, ±10%, ±20%)
- **WHEN** the user selects "Block Bootstrap"
- **THEN** the existing method sub-selector (Stationary/Circular/GARCH) SHALL appear

### Requirement: Backward-compatible API call
The Stress Test sub-tab SHALL call `POST /api/monte-carlo` with a `mode` parameter, extending the existing request.

#### Scenario: Run button triggers API call
- **WHEN** the user clicks "Run Stress Test"
- **THEN** the frontend SHALL POST to `/api/monte-carlo` with `{ strategy, symbol, start, end, params, initial_capital, mode, n_paths, n_days, ...mode_specific_fields }` and display a loading spinner

#### Scenario: Backend error displayed
- **WHEN** the API returns an error response
- **THEN** the frontend SHALL display the error message in a toast notification

### Requirement: MDD distribution chart
The Stress Test page SHALL display a histogram of maximum drawdown values across all simulated paths.

#### Scenario: MDD histogram renders
- **WHEN** MC results contain `mdd_values`
- **THEN** a histogram SHALL render showing the distribution of MDD values (x-axis: drawdown %, y-axis: frequency)

#### Scenario: P95 MDD line
- **WHEN** the MDD histogram renders
- **THEN** a vertical dashed line SHALL mark the 95th percentile MDD with a label showing the value

#### Scenario: Median MDD line
- **WHEN** the MDD histogram renders
- **THEN** a vertical solid line SHALL mark the median MDD

#### Scenario: Dark theme consistency
- **WHEN** the MDD chart renders
- **THEN** it SHALL use the same dark theme palette as other charts (background `#0a0a22`, text `#ccc`, accent `#ff5252` for the P95 line)

### Requirement: Multi-threshold ruin probability display
The Stress Test page SHALL display ruin probability for each configured threshold.

#### Scenario: Ruin gauge cards
- **WHEN** MC results contain `ruin_thresholds`
- **THEN** for each threshold (e.g., -30%, -50%, -100%) the page SHALL display a stat card showing the probability as a percentage with color coding: green (<5%), gold (5-20%), red (>20%)

#### Scenario: Empty ruin thresholds
- **WHEN** `ruin_thresholds` is empty or all values are 0
- **THEN** the display SHALL show "No ruin risk detected" in green

### Requirement: Parameter sensitivity heatmap
The Stress Test page SHALL display a heatmap showing Sortino ratio change across parameter perturbations when `mode="sensitivity"`.

#### Scenario: Heatmap renders
- **WHEN** MC results contain `param_sensitivity`
- **THEN** a heatmap SHALL render with parameters on the Y-axis, perturbation offsets on the X-axis, and Sortino ratio as cell color

#### Scenario: Color scale
- **WHEN** the heatmap renders
- **THEN** cells SHALL use a diverging color scale: green for Sortino above baseline, red for below baseline, neutral for near-baseline

#### Scenario: Cell hover tooltip
- **WHEN** the user hovers over a heatmap cell
- **THEN** a tooltip SHALL show: parameter name, offset percentage, perturbed value, and Sortino ratio

#### Scenario: Sensitivity hidden for non-sensitivity modes
- **WHEN** `mode` is not `"sensitivity"`
- **THEN** the heatmap panel SHALL not be displayed

### Requirement: Fan chart retains existing functionality
The existing fan chart SVG panel SHALL continue to render for all modes that produce equity path bands.

#### Scenario: Bands from backend
- **WHEN** `MonteCarloReport.bands` is received from the API
- **THEN** the fan chart SHALL render those percentile bands directly

#### Scenario: Percentile stat cards
- **WHEN** results contain VaR/CVaR/prob_ruin
- **THEN** the page SHALL display risk metric stat cards (existing behavior preserved)

### Requirement: Sharpe/Sortino distribution panel
The Stress Test page SHALL display distributions of Sharpe and Sortino ratios when available.

#### Scenario: Distributions render
- **WHEN** MC results contain `sharpe_values` and `sortino_values`
- **THEN** the page SHALL display two histograms: Sharpe ratio distribution and Sortino ratio distribution

#### Scenario: Median lines
- **WHEN** Sharpe/Sortino histograms render
- **THEN** each histogram SHALL show a vertical median line with a label
