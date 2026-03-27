## ADDED Requirements

### Requirement: Monte Carlo mode selector
The Monte Carlo sub-tab SHALL provide a mode selector allowing the user to choose the simulation type before running.

#### Scenario: Available modes
- **WHEN** the Monte Carlo page loads
- **THEN** the sidebar SHALL display a dropdown with modes: "Bootstrap (Daily Returns)", "Trade Resampling", "GBM Price Simulation", "Parameter Sensitivity"

#### Scenario: Default mode
- **WHEN** no mode has been selected
- **THEN** "Bootstrap (Daily Returns)" SHALL be pre-selected

#### Scenario: Mode-specific controls
- **WHEN** the user selects "GBM Price Simulation"
- **THEN** the sidebar SHALL show additional controls: "Fat Tails" toggle, "Degrees of Freedom" input (default 5)
- **WHEN** the user selects "Trade Resampling"
- **THEN** the sidebar SHALL show "Block Size" input (default 1)
- **WHEN** the user selects "Parameter Sensitivity"
- **THEN** the sidebar SHALL show "Perturbation Offsets" multi-select (±5%, ±10%, ±20%)

### Requirement: MC run delegates to backend
The Monte Carlo sub-tab SHALL call `POST /api/mc/run` with the selected mode and parameters, replacing the current frontend-only bootstrap computation.

#### Scenario: Run button triggers API call
- **WHEN** the user clicks "Run" on the Monte Carlo page
- **THEN** the frontend SHALL POST to `/api/mc/run` with `{ strategy, symbol, start, end, params, initial_capital, bar_agg, mode, n_paths, sim_days, ...mode_specific_fields }` and display a loading spinner

#### Scenario: Backend error displayed
- **WHEN** the API returns an error response
- **THEN** the frontend SHALL display the error message in a toast notification

### Requirement: MDD distribution chart
The Monte Carlo page SHALL display a histogram of maximum drawdown values across all simulated paths.

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

### Requirement: Ruin probability display
The Monte Carlo page SHALL display ruin probability for each configured threshold.

#### Scenario: Ruin gauge cards
- **WHEN** MC results contain `ruin_thresholds`
- **THEN** for each threshold (e.g., -30%, -50%, -100%) the page SHALL display a stat card showing the probability as a percentage with color coding: green (<5%), gold (5-20%), red (>20%)

#### Scenario: Empty ruin thresholds
- **WHEN** `ruin_thresholds` is empty or all values are 0
- **THEN** the display SHALL show "No ruin risk detected" in green

### Requirement: Parameter sensitivity heatmap
The Monte Carlo page SHALL display a heatmap showing Sortino ratio change across parameter perturbations when `mode="sensitivity"`.

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

### Requirement: Simulated equity paths panel retains existing functionality
The existing Simulated Equity Paths SVG panel SHALL continue to render for all modes that produce equity paths.

#### Scenario: Paths from backend
- **WHEN** `MonteCarloReport.paths` is received from the API
- **THEN** the SVG panel SHALL render those paths directly (no client-side simulation)

#### Scenario: Percentile stat cards
- **WHEN** results contain `percentiles`
- **THEN** the page SHALL display P5, P25, P50, P75, P95 final PnL and Return % stat cards

### Requirement: Sharpe/Sortino distribution panel
The Monte Carlo page SHALL display distributions of Sharpe and Sortino ratios when available.

#### Scenario: Distributions render
- **WHEN** MC results contain `sharpe_values` and `sortino_values`
- **THEN** the page SHALL display two histograms: Sharpe ratio distribution and Sortino ratio distribution

#### Scenario: Median lines
- **WHEN** Sharpe/Sortino histograms render
- **THEN** each histogram SHALL show a vertical median line with a label

## MODIFIED Requirements

### Requirement: Strategy sub-tabs
The Strategy tab SHALL contain sub-tabs for Code Editor (file browser + code editor), Optimizer (param grid + IS/OOS results + heatmap), Grid Search (2D parameter sweep + heatmap), and Monte Carlo (mode selector + simulated equity paths + MDD distribution + ruin probability + parameter sensitivity heatmap + PnL distribution + percentile table).

#### Scenario: Code editor loads and saves files
- **WHEN** the user selects a file in the Code Editor
- **THEN** the editor SHALL load the file content and support save/revert operations via API calls

#### Scenario: Optimizer streams progress
- **WHEN** the user starts an optimizer run
- **THEN** the frontend SHALL poll `/api/optimizer/status` and display progress until completion

#### Scenario: Monte Carlo displays mode-specific panels
- **WHEN** the user runs Monte Carlo in any mode
- **THEN** the page SHALL display the panels relevant to that mode (equity paths for all, sensitivity heatmap for sensitivity mode, etc.)
