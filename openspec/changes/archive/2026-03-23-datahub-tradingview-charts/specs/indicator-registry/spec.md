## ADDED Requirements

### Requirement: Typed indicator registry
The frontend SHALL maintain a typed indicator registry (`INDICATOR_REGISTRY`) as an array of `IndicatorDef` objects. Each entry SHALL declare: a unique string `id`, a human-readable `label`, a `type` of `"overlay"` or `"pane"`, an array of `ParamDef` objects for configurable parameters, and a `compute` function.

#### Scenario: Registry contains all standard indicators
- **WHEN** the application loads
- **THEN** the registry SHALL include at minimum the following indicators: SMA, EMA, Bollinger Bands, RSI, MACD, Bias Ratio, ATR, OBV, Volume, VWAP

#### Scenario: Each indicator has at least one configurable parameter
- **WHEN** the registry is queried for an indicator's parameters
- **THEN** the indicator SHALL expose at least one `ParamDef` with a `name`, `label`, `default` value, and `min`/`max` bounds
- **EXCEPT** for indicators where no parameter is meaningful (e.g., OBV, Volume) which MAY have zero parameters

### Requirement: Overlay vs pane indicator types
Each indicator in the registry SHALL be classified as either `"overlay"` (rendered on the primary price pane) or `"pane"` (rendered in its own secondary pane). Overlay indicators share the price pane's y-axis. Pane indicators have their own independent y-axis.

#### Scenario: SMA is an overlay indicator
- **WHEN** the user adds an SMA indicator
- **THEN** the SMA line SHALL render on the primary OHLC pane sharing the price y-axis

#### Scenario: RSI is a pane indicator
- **WHEN** the user adds an RSI indicator
- **THEN** the RSI SHALL render in its own secondary pane with a 0-100 y-axis range

#### Scenario: Volume is a pane indicator
- **WHEN** the user adds a Volume indicator
- **THEN** the volume histogram SHALL render in its own secondary pane

### Requirement: Compute function contract
Each indicator's `compute` function SHALL accept `(bars: OHLCVBar[], params: Record<string, number>)` and return an array of `SeriesOutput` objects. Each `SeriesOutput` SHALL contain: `label` (string), `type` ("line" or "histogram"), `color` (CSS color string), and `data` (array of `{ time: number, value: number, color?: string }` points).

#### Scenario: SMA compute returns one line series
- **WHEN** SMA is computed with period 20 over 100 bars
- **THEN** the result SHALL be a single `SeriesOutput` with type `"line"` and 81 valid data points (100 - 20 + 1)

#### Scenario: MACD compute returns three series
- **WHEN** MACD is computed with fast=12, slow=26, signal=9
- **THEN** the result SHALL contain exactly three `SeriesOutput` entries: MACD line (type "line"), Signal line (type "line"), and Histogram (type "histogram")

#### Scenario: Bollinger Bands compute returns two overlay lines
- **WHEN** Bollinger Bands is computed with period 20, stdDev 2
- **THEN** the result SHALL contain two `SeriesOutput` entries: Upper band (type "line") and Lower band (type "line")

### Requirement: Multiple instances of the same indicator
The system SHALL allow the user to add multiple instances of the same indicator with different parameters. Each instance SHALL be independently configurable and removable.

#### Scenario: Two SMA instances with different periods
- **WHEN** the user adds SMA(20) and SMA(50)
- **THEN** the primary pane SHALL display two distinct SMA overlay lines with different colors

#### Scenario: Removing one instance does not affect the other
- **WHEN** the user removes SMA(20) while SMA(50) is active
- **THEN** SMA(50) SHALL remain visible and unaffected

### Requirement: Adding a new indicator to the registry
Adding a new indicator type SHALL require only adding a new entry to the `INDICATOR_REGISTRY` array. No changes to chart components or sidebar components SHALL be necessary.

#### Scenario: Developer adds a Stochastic indicator
- **WHEN** a developer adds a Stochastic entry to `INDICATOR_REGISTRY` with `type: "pane"` and a `compute` function
- **THEN** the indicator SHALL automatically appear in the "Add Indicator" dropdown and render correctly when selected, without any other code changes

### Requirement: Distinct visual identity per instance
Each active indicator instance SHALL be assigned a distinguishable color. When the same indicator type has multiple instances, each instance SHALL use a different color from a predefined palette.

#### Scenario: Two SMA instances get different colors
- **WHEN** the user adds SMA(20) and SMA(50)
- **THEN** SMA(20) and SMA(50) SHALL render with two visually distinct colors
