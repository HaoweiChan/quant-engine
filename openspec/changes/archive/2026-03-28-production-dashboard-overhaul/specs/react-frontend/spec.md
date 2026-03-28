## MODIFIED Requirements

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

## REMOVED Requirements

### Requirement: Backtest page
**Reason**: The standalone Backtest page is merged into the Strategy tab as the "Tear Sheet" sub-tab. All functionality (strategy selection, param configuration, run backtest, results display, run history) moves into the Strategy context with shared global parameters.
**Migration**: Navigate to Strategy → Tear Sheet. URL `/backtest` auto-redirects to `/strategy?tab=tearsheet`.
