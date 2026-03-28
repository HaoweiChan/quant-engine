## ADDED Requirements

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

## MODIFIED Requirements

### Requirement: Strategy sub-tabs
The Strategy tab SHALL contain sub-tabs for Code Editor, Tear Sheet (single backtest), Param Sweep (grid/random/walk-forward optimization), and Stress Test (mode selector + fan chart + MDD distribution + ruin probability + parameter sensitivity heatmap + Sharpe/Sortino distributions).

#### Scenario: Stress Test displays mode-specific panels
- **WHEN** the user runs a stress test in any mode
- **THEN** the page SHALL display the panels relevant to that mode (fan chart for all path-producing modes, sensitivity heatmap for sensitivity mode, etc.)
