## MODIFIED Requirements

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
