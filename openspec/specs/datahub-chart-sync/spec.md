## Purpose

Synchronized multi-pane chart layout for the Data Hub: shared time scale, crosshair alignment, primary OHLC pane, secondary indicator panes, and fixed height allocation so overlays and pane indicators behave consistently.

## Requirements

### Requirement: Multi-pane chart stack with synchronized time scale
The Data Hub SHALL render all chart panes (primary OHLC pane and secondary indicator panes) inside a single `ChartStack` component. All panes SHALL share the same visible logical range so that scrolling or zooming one pane scrolls/zooms all other panes identically.

#### Scenario: Scrolling the primary pane scrolls secondary panes
- **WHEN** the user scrolls the time axis on the primary OHLC pane
- **THEN** all secondary indicator panes SHALL update their visible range to match the primary pane within the same animation frame

#### Scenario: Zooming a secondary pane zooms the primary pane
- **WHEN** the user pinch-zooms or scroll-zooms on any secondary indicator pane
- **THEN** the primary pane and all other secondary panes SHALL update their zoom level to match

#### Scenario: No sync loop
- **WHEN** a pane's visible range is programmatically set by the sync mechanism
- **THEN** that pane SHALL NOT fire its own range-change listener to avoid infinite sync loops

### Requirement: Crosshair synchronization across panes
When the user hovers on any pane, all other panes SHALL display a vertical crosshair line at the same time position.

#### Scenario: Hovering on primary pane syncs secondary crosshairs
- **WHEN** the user moves the mouse cursor over the primary OHLC pane
- **THEN** each secondary indicator pane SHALL display a vertical crosshair line at the corresponding time position

#### Scenario: Hovering on secondary pane syncs primary crosshair
- **WHEN** the user moves the mouse cursor over a secondary indicator pane
- **THEN** the primary OHLC pane and all other secondary panes SHALL display a vertical crosshair line at the corresponding time position

#### Scenario: Cursor leaves chart area
- **WHEN** the user moves the mouse cursor out of all chart panes
- **THEN** all crosshair indicators SHALL be cleared

### Requirement: Primary pane always present
The `ChartStack` SHALL always render exactly one primary pane containing the OHLC candlestick series only (no integrated volume). Volume SHALL be available as a secondary chart indicator.

#### Scenario: No indicators added
- **WHEN** no overlay indicators are active
- **THEN** the chart stack SHALL display the primary OHLC pane (without volume) and the always-visible secondary chart pane

#### Scenario: All overlay indicators removed
- **WHEN** the user removes all overlay indicators
- **THEN** the primary OHLC pane SHALL remain visible with no overlays

### Requirement: Always-visible secondary chart with dropdown selector
The `ChartStack` SHALL always render a dedicated secondary chart pane below the primary pane. This pane SHALL have a dropdown selector to choose which indicator to display. The default indicator SHALL be Volume. The dropdown SHALL list all pane-type indicators from the registry.

#### Scenario: Default secondary chart shows Volume
- **WHEN** data is loaded and no secondary indicator has been changed
- **THEN** the secondary chart SHALL display Volume as a histogram

#### Scenario: Switching secondary chart indicator
- **WHEN** the user selects "RSI" from the secondary chart dropdown
- **THEN** the secondary chart SHALL re-render with the RSI indicator

#### Scenario: Secondary chart parameter editing
- **WHEN** the user selects an indicator with configurable parameters (e.g., RSI) in the secondary chart
- **THEN** parameter inputs SHALL appear next to the dropdown allowing the user to adjust values (e.g., RSI period)

#### Scenario: Secondary chart syncs with primary
- **WHEN** the user scrolls or zooms the primary pane
- **THEN** the secondary chart SHALL scroll and zoom in sync

### Requirement: Dynamic secondary pane creation and removal
Pane-type indicators SHALL each render in their own secondary pane below the primary pane. Adding a pane-type indicator SHALL create a new pane; removing it SHALL destroy that pane.

#### Scenario: Adding a pane indicator
- **WHEN** the user adds an RSI indicator
- **THEN** a new pane SHALL appear below the primary pane displaying the RSI line

#### Scenario: Removing a pane indicator
- **WHEN** the user removes the only active RSI indicator
- **THEN** the RSI pane SHALL be destroyed and the chart stack height SHALL decrease accordingly

#### Scenario: Multiple pane indicators
- **WHEN** the user adds RSI and MACD indicators
- **THEN** two secondary panes SHALL appear below the primary pane, each with its own y-axis scale

### Requirement: Pane height allocation
The primary pane SHALL have a fixed height of 340px. Each secondary pane SHALL have a fixed height of 140px. The chart stack's total height SHALL be 340 + (140 × number of secondary panes) pixels.

#### Scenario: Two secondary panes
- **WHEN** two pane-type indicators are active
- **THEN** the chart stack total height SHALL be 620px (340 + 140 + 140)

### Requirement: Maximum pane limit
The chart stack SHALL allow a maximum of 6 simultaneous panes (1 primary + 5 secondary). Attempting to add a 6th secondary pane SHALL be rejected.

#### Scenario: Adding beyond the limit
- **WHEN** 5 secondary panes are active and the user attempts to add another pane-type indicator
- **THEN** the addition SHALL be rejected and the user SHALL see a message indicating the maximum pane limit is reached
