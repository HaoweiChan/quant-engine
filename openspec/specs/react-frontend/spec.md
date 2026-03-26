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
The frontend SHALL provide a horizontal tab bar with four primary tabs in lifecycle order: Data Hub, Strategy, Backtest, Trading. The active tab SHALL show a `#5a8af2` bottom border. The Strategy tab SHALL contain sub-tabs: Code Editor, Optimizer, Grid Search, Monte Carlo. The Trading tab SHALL contain sub-tabs: Accounts, War Room, Blotter, Risk.

#### Scenario: Tab switches page content
- **WHEN** the user clicks a primary tab
- **THEN** the page content SHALL update via client-side routing without a full page reload

#### Scenario: Default tab on load
- **WHEN** the frontend first loads
- **THEN** the Data Hub tab SHALL be active

#### Scenario: Sub-tab state preserved across primary tab switches
- **WHEN** the user selects Monte Carlo under Strategy, switches to Backtest, then returns to Strategy
- **THEN** the Monte Carlo sub-tab SHALL still be selected

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
The frontend SHALL use Zustand stores for application state: `marketDataStore` (cached OHLCV, indicators), `backtestStore` (results, progress), `tradingStore` (accounts, sessions, WS connection), and `uiStore` (active tabs, sidebar state, filters).

#### Scenario: OHLCV data cached across tab switches
- **WHEN** the user loads OHLCV data on Data Hub, switches to Backtest, then returns to Data Hub
- **THEN** the previously loaded OHLCV data SHALL still be available without re-fetching

#### Scenario: WebSocket connection state tracked
- **WHEN** the WebSocket connection to `/ws/live-feed` drops
- **THEN** the `tradingStore` SHALL update its `connected` state to `false` and display a disconnection indicator

### Requirement: WebSocket hooks for real-time data
The frontend SHALL provide React hooks (`useLiveFeed`, `useBacktestProgress`, `useRiskAlerts`) that manage WebSocket connections with automatic reconnection using exponential backoff. The `useLiveFeed` hook SHALL process incoming tick messages by calling `processLiveTick()` on `marketDataStore` to drive live bar aggregation and chart updates.

#### Scenario: Auto-reconnect on disconnect
- **WHEN** the WebSocket connection to `/ws/live-feed` is lost
- **THEN** the hook SHALL attempt reconnection with exponential backoff (1s, 2s, 4s, 8s, max 30s)

#### Scenario: Live feed updates trading store
- **WHEN** a tick message arrives on the live feed WebSocket
- **THEN** the `tradingStore` SHALL update the relevant position's latest price and unrealized PnL

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

### Requirement: Backtest page
The Backtest page SHALL expose strategy selection, contract/date range, strategy parameters, and a Run Backtest button. Results SHALL display equity curve (vs buy-and-hold), drawdown chart, return distribution histogram, stat cards (Sharpe, Max DD, Win Rate, Total Trades, Total PnL, B&H PnL, Alpha), and a trade log. The page SHALL also display a collapsible "Run History" panel showing past optimization and backtest runs for the selected strategy.

#### Scenario: Run backtest and display results
- **WHEN** the user configures parameters and clicks Run Backtest
- **THEN** the frontend SHALL POST to `/api/backtest/run` and render all result charts and metrics upon response

#### Scenario: Backtest progress feedback
- **WHEN** a backtest is running
- **THEN** the frontend SHALL display a loading indicator with progress updates if connected to `/ws/backtest-progress`

#### Scenario: Run history loads on strategy selection
- **WHEN** the user selects a strategy in the Backtest page
- **THEN** the frontend SHALL call `fetchParamRuns(strategy)` via `GET /api/params/runs/{strategy}` and display the results in the Run History panel

#### Scenario: Run history panel content
- **WHEN** run history data is loaded for a strategy with past runs
- **THEN** each run entry SHALL display: run date, source (mcp/dashboard), search type (grid/random/single), number of trials, best Sharpe, best PnL, and an "Activate" button for sweep runs that have candidates

#### Scenario: Run history empty state
- **WHEN** run history data is loaded for a strategy with no past runs
- **THEN** the panel SHALL display a message: "No optimization history for this strategy"

#### Scenario: Run history panel is collapsible
- **WHEN** the user clicks the Run History panel header
- **THEN** the panel body SHALL toggle between expanded and collapsed states
- **AND** the default state SHALL be collapsed to keep the page clean

#### Scenario: Activate candidate from history
- **WHEN** the user clicks "Activate" on a run history entry that has candidates
- **THEN** the frontend SHALL POST to `/api/params/activate/{candidate_id}` and update the active params in the sidebar

### Requirement: Strategy sub-tabs
The Strategy tab SHALL contain sub-tabs for Code Editor (file browser + code editor), Optimizer (param grid + IS/OOS results + heatmap), Grid Search (2D parameter sweep + heatmap), and Monte Carlo (simulated equity paths + PnL distribution + percentile table).

#### Scenario: Code editor loads and saves files
- **WHEN** the user selects a file in the Code Editor
- **THEN** the editor SHALL load the file content and support save/revert operations via API calls

#### Scenario: Optimizer streams progress
- **WHEN** the user starts an optimizer run
- **THEN** the frontend SHALL poll `/api/optimizer/status` and display progress until completion

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
