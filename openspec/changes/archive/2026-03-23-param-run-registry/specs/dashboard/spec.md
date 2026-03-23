## ADDED Requirements

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

## MODIFIED Requirements

### Requirement: Backtest page
The Backtest page SHALL load the active optimized parameters from the param registry as sidebar defaults when a strategy is selected. It SHALL expose position engine settings in the sidebar (Max Pyramid Levels, Stop ATR Mult, Trail ATR Mult, Add Trigger ATR, Margin Limit, Kelly Fraction, Entry Conf Threshold, Max Loss, Re-Entry Strategy). It SHALL display 5 performance metric stat cards (Sharpe, Max Drawdown, Win Rate, Total Trades, Total PnL), an equity curve chart, a drawdown area chart, a return distribution histogram, and a trade log table.

#### Scenario: Sidebar loads optimized params
- **WHEN** the user selects a strategy on the Backtest page
- **THEN** the sidebar parameter inputs SHALL be populated with the active optimized params from the registry
- **AND** if no optimized params exist, it SHALL fall back to PARAM_SCHEMA defaults from `GET /api/strategies`

#### Scenario: Optimized params indicator
- **WHEN** the Backtest sidebar displays params loaded from the registry
- **THEN** a visual indicator (label or badge) SHALL show that the params are from an optimization run, including the run date and objective

#### Scenario: Run Backtest button
- **WHEN** the user clicks "Run Backtest"
- **THEN** the charts and metrics SHALL update based on the current sidebar parameter values

#### Scenario: Total PnL colored by sign
- **WHEN** total PnL is positive
- **THEN** the stat card value SHALL be `#69f0ae`; when negative it SHALL be `#ff5252`

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
