# global-param-context

## Purpose
TBD — synced from change `production-dashboard-overhaul`.

## Requirements

### Requirement: Zustand strategy store with global parameter state
The frontend SHALL provide a `useStrategyStore` Zustand store in `frontend/src/stores/strategyStore.ts` holding the unified research state: `strategy` (slug), `symbol`, `startDate`, `endDate`, `slippageBps`, `commissionBps`, and `params` (full parameter vector θ as `Record<string, number>`). All Strategy sub-tabs SHALL read from this store instead of maintaining local copies.

#### Scenario: Store initializes with defaults
- **WHEN** the Strategy page mounts for the first time
- **THEN** `useStrategyStore` SHALL have `strategy` set to the first available strategy slug, `symbol` set to `"TX"`, `startDate`/`endDate` set to a sensible default range (e.g., 6 months trailing), `slippageBps` set to `5`, `commissionBps` set to `2`, and `params` populated from the selected strategy's default param values

#### Scenario: Strategy selection populates param vector
- **WHEN** the user selects a different strategy in the global sidebar
- **THEN** the store SHALL update `strategy`, reset `params` to the new strategy's default values from its `param_grid`, and preserve `symbol`, `startDate`, `endDate`, `slippageBps`, `commissionBps`

#### Scenario: Param change propagates to all tabs
- **WHEN** the user modifies a parameter value in the global sidebar
- **THEN** all rendered sub-tabs (Tear Sheet, Param Sweep, Stress Test) SHALL reflect the updated value without requiring a re-run

#### Scenario: Cost assumptions visible at all times
- **WHEN** the Strategy page is active
- **THEN** the sidebar SHALL display `slippageBps` and `commissionBps` inputs with labels "Slippage (bps)" and "Commission (bps)" so the user never runs a zero-cost backtest unknowingly

### Requirement: Global parameter sidebar on Strategy page
The Strategy page SHALL render a persistent left sidebar (234px, `#09091e` background) containing: strategy selector dropdown, symbol selector, date range pickers (start/end), slippage bps input, commission bps input, and a dynamically generated list of all parameters for the selected strategy with their current values and editable inputs.

#### Scenario: Sidebar renders all strategy parameters
- **WHEN** the user selects a strategy with 5 parameters (e.g., `fast_period`, `slow_period`, `atr_multiplier`, `lots`, `bar_agg`)
- **THEN** the sidebar SHALL display 5 labeled number inputs, one for each parameter, with current values from `useStrategyStore.params`

#### Scenario: Param inputs respect grid bounds
- **WHEN** a strategy defines `param_grid` with `fast_period: { min: 1, max: 50, step: 1 }`
- **THEN** the sidebar input for `fast_period` SHALL enforce `min=1`, `max=50`, `step=1` as HTML number input attributes

#### Scenario: Sidebar is fixed during tab switching
- **WHEN** the user switches between Code Editor, Tear Sheet, Param Sweep, and Stress Test
- **THEN** the sidebar SHALL remain visible and its contents SHALL not re-render or reset

### Requirement: Param inputs locked during execution
The global parameter sidebar SHALL disable all inputs while a backtest, sweep, or stress test is running to prevent mid-execution state inconsistency.

#### Scenario: Inputs disable during backtest
- **WHEN** a backtest is running (loading state in `useBacktestStore`)
- **THEN** all sidebar inputs (strategy, symbol, dates, params, costs) SHALL be visually disabled with reduced opacity and non-interactive

#### Scenario: Inputs re-enable after completion
- **WHEN** the backtest/sweep/stress-test completes or errors
- **THEN** all sidebar inputs SHALL return to interactive state

### Requirement: Run provenance logging
Every execution (backtest, param sweep, stress test) SHALL compute and attach a provenance record containing: `param_hash` (SHA-256 of JSON-serialized sorted parameter dict), `date_range` (start and end dates), `cost_model` (slippage_bps and commission_bps), and `git_commit` (short SHA from `/api/meta`).

#### Scenario: Provenance sent with backtest request
- **WHEN** the user clicks "Run Backtest" on the Tear Sheet tab
- **THEN** the POST to `/api/backtest/run` SHALL include a `provenance` field with `param_hash`, `date_range`, `cost_model`, and `git_commit`

#### Scenario: Provenance hash is deterministic
- **WHEN** two runs use identical parameter values `{ fast: 10, slow: 20 }`
- **THEN** both runs SHALL produce the same `param_hash` value

#### Scenario: Git commit fetched from meta endpoint
- **WHEN** the Strategy page loads
- **THEN** the frontend SHALL call `GET /api/meta` and cache the returned `git_commit` short SHA for use in all provenance records

### Requirement: Backend meta endpoint
The API SHALL expose `GET /api/meta` returning `{ "git_commit": "<short-sha>", "version": "<semver>" }`.

#### Scenario: Meta returns current commit
- **WHEN** `GET /api/meta` is called
- **THEN** the response SHALL include the current Git HEAD short-sha (7 chars) and the project version string

#### Scenario: Meta works in non-git environment
- **WHEN** the server is running outside a git repository (e.g., Docker without `.git`)
- **THEN** `git_commit` SHALL be `"unknown"` and `version` SHALL still return the configured version
