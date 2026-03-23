## Why

The Data Hub charting system is rigid: the main OHLC chart and secondary indicator chart are independent, meaning scrolling or zooming one does not affect the other. Indicators are limited to a hardcoded set of three overlays (SMA, EMA, Bollinger) with single-instance restrictions, while secondary indicators are a separate one-at-a-time dropdown. Users expect TradingView-style behavior — synchronized panes, stacking multiple indicators, and configuring parameters per indicator — which the current architecture cannot support without a ground-up refactor.

## What Changes

- **Synchronized multi-pane chart container**: Replace the current independent `OHLCVChart` + `SecondaryChart` with a single `ChartStack` component that manages N chart panes sharing a synchronized time scale via lightweight-charts' `subscribeVisibleLogicalRangeChange` / `setVisibleLogicalRange` API. The primary (OHLC + volume) pane always exists; users can add/remove secondary panes.
- **Indicator registry**: Introduce a typed indicator registry (`INDICATOR_REGISTRY`) that catalogs all available indicators — both overlays (rendered on the price pane) and pane-based (rendered in their own sub-chart). Each entry declares: compute function, default params, series type, color, and whether it's an overlay or pane indicator. This replaces the scattered hardcoded indicator logic.
- **Dynamic indicator panel in sidebar**: Replace the fixed SMA/EMA/Bollinger checkboxes with an "Add Indicator" flow: a searchable dropdown listing all registered indicators, with per-instance parameter editing and a remove button. Users can add multiple instances of the same indicator (e.g., SMA(20) + SMA(50) + SMA(200)).
- **Crosshair sync**: When the user hovers on any pane, the crosshair position syncs across all panes.
- **Remove hardcoded secondary chart selector**: The inline `<select>` in the secondary `ChartCard` title is replaced by the sidebar-driven indicator management.

## Capabilities

### New Capabilities

- `datahub-chart-sync`: Multi-pane chart synchronization — time scale, crosshair, and visible range synced across all chart panes in the Data Hub.
- `indicator-registry`: Client-side indicator registry with typed definitions, compute functions, default parameters, and series rendering config for both overlay and pane indicators.

### Modified Capabilities

- `dashboard`: Data Hub page layout changes — sidebar indicator section refactored from fixed checkboxes to dynamic indicator list; chart area refactored from independent charts to synchronized chart stack.

## Impact

- **Frontend only** — no backend API changes.
- **Files affected**:
  - `frontend/src/pages/DataHub.tsx` — sidebar and chart area restructured
  - `frontend/src/components/charts/OHLCVChart.tsx` — becomes part of `ChartStack` or is refactored to expose chart instance refs
  - `frontend/src/components/charts/SecondaryChart.tsx` — removed; replaced by generic `IndicatorPane` within `ChartStack`
  - `frontend/src/lib/indicators.ts` — expanded with registry pattern; existing `sma`, `ema`, `bollingerBands`, `atr` reused
  - New: `frontend/src/components/charts/ChartStack.tsx` — orchestrates multi-pane sync
  - New: `frontend/src/lib/indicatorRegistry.ts` — typed indicator definitions
- **Dependencies**: No new npm packages — uses existing `lightweight-charts` v5.x APIs.
- **Risk**: Low — isolated to Data Hub page, no shared state leaks to Backtest or Trading pages.
