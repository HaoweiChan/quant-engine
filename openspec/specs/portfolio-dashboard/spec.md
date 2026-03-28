# portfolio-dashboard

## Purpose
TBD — synced from change `multi-strategy-portfolio`.

## Requirements

### Requirement: Portfolio sub-tab in Strategy page
The Strategy page SHALL include a "Portfolio" sub-tab alongside the existing Backtest, Stress Test, Tear Sheet, and Param Sweep tabs.

#### Scenario: Tab visible
- **WHEN** the Strategy page loads
- **THEN** a "Portfolio" tab SHALL appear in the sub-tab bar

#### Scenario: Default state
- **WHEN** the Portfolio tab is selected and no analysis has been run
- **THEN** the page SHALL show strategy selection dropdowns and a disabled "Merge & Analyze" button

### Requirement: Strategy selection controls
The Portfolio tab SHALL provide 2-3 strategy selection dropdowns populated from the strategy registry, with weight inputs for each.

```
┌────────────────────────────────────────────────────┐
│ Strategy A: [dropdown ▾]  Weight: [33] %           │
│ Strategy B: [dropdown ▾]  Weight: [33] %           │
│ + Add Strategy C                                   │
│                                                    │
│ [Merge & Analyze]                                  │
└────────────────────────────────────────────────────┘
```

#### Scenario: Two strategies by default
- **WHEN** the Portfolio tab loads
- **THEN** it SHALL show two strategy dropdowns with equal weights

#### Scenario: Add third strategy
- **WHEN** user clicks "+ Add Strategy C"
- **THEN** a third dropdown and weight input SHALL appear
- **AND** weights SHALL auto-adjust to equal split

#### Scenario: Remove third strategy
- **WHEN** user removes the third strategy
- **THEN** it SHALL revert to two dropdowns with weights re-equalized

#### Scenario: Dropdown options
- **WHEN** a strategy dropdown is opened
- **THEN** it SHALL list all strategies from the registry with their display names

#### Scenario: Duplicate strategy prevented
- **WHEN** user selects the same strategy in two dropdowns
- **THEN** the "Merge & Analyze" button SHALL remain disabled with a warning

### Requirement: Merge & Analyze action
Clicking "Merge & Analyze" SHALL call `POST /api/portfolio/backtest` and display results.

#### Scenario: Successful merge
- **WHEN** the merge completes
- **THEN** the results section SHALL display: combined equity curve chart, side-by-side metrics table, and correlation matrix

#### Scenario: Loading state
- **WHEN** merge is in progress
- **THEN** a loading indicator SHALL appear on the button and results area

#### Scenario: Error handling
- **WHEN** the API returns an error
- **THEN** an error message SHALL be displayed in the results area

### Requirement: Combined equity curve visualization
The results section SHALL show a line chart with the merged portfolio equity curve overlaid with individual strategy curves.

#### Scenario: Chart elements
- **WHEN** results are displayed
- **THEN** the chart SHALL show: one line per individual strategy (dimmed), one bold line for the merged portfolio, x-axis as trading days, y-axis as equity value

#### Scenario: Legend
- **WHEN** the chart renders
- **THEN** a legend SHALL identify each strategy line and the portfolio line by color

### Requirement: Side-by-side metrics table
The results section SHALL show a table comparing individual strategy metrics and the merged portfolio metrics.

#### Scenario: Table columns
- **WHEN** results are displayed for 2 strategies
- **THEN** the table SHALL have columns: Metric, Strategy A, Strategy B, Portfolio
- **AND** rows for: Total Return, Sharpe, Sortino, Max Drawdown, Calmar, Annual Vol

#### Scenario: Portfolio column highlights
- **WHEN** the portfolio metric is better than both individual strategies (e.g., higher Sharpe)
- **THEN** the portfolio cell SHALL have a green highlight indicating diversification benefit

### Requirement: Correlation matrix display
The results section SHALL show the inter-strategy return correlation as a small heatmap or table.

#### Scenario: Two-strategy correlation
- **WHEN** 2 strategies are analyzed
- **THEN** a 2×2 matrix SHALL be displayed with diagonal=1.0 and off-diagonal as the correlation coefficient

#### Scenario: Color coding
- **WHEN** correlation is displayed
- **THEN** values near 1.0 SHALL be red (high correlation = less diversification), values near 0.0 SHALL be green (good diversification), values near -1.0 SHALL be blue (strong diversification)

### Requirement: Portfolio stress test action
The results section SHALL include a "Run Portfolio Stress Test" button that calls `POST /api/portfolio/stress-test`.

#### Scenario: Button availability
- **WHEN** merge results are displayed
- **THEN** the "Run Portfolio Stress Test" button SHALL be enabled

#### Scenario: Stress results display
- **WHEN** portfolio stress test completes
- **THEN** the page SHALL display the fan chart and risk metrics (VaR, CVaR, P(Ruin)) using the same visualization components as the single-strategy Stress Test page

#### Scenario: Stress test without merge first
- **WHEN** no merge has been run yet
- **THEN** the "Run Portfolio Stress Test" button SHALL be disabled
