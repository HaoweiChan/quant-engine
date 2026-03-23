## 1. Indicator Registry

- [x] 1.1 Create `frontend/src/lib/indicatorRegistry.ts` with `IndicatorDef`, `ParamDef`, `SeriesOutput`, and `ActiveIndicator` TypeScript interfaces
- [x] 1.2 Wrap existing indicator functions (`sma`, `ema`, `bollingerBands`) from `indicators.ts` into registry entries with type `"overlay"`, default params, and compute functions
- [x] 1.3 Wrap existing pane indicators (`computeRSI`, `computeMACD`, `computeBias`, `computeATR`, `computeOBV`, Volume) from `SecondaryChart.tsx` into registry entries with type `"pane"` and move compute functions to `indicators.ts`
- [x] 1.4 Add VWAP as a new overlay indicator in the registry (compute function: cumulative (price × volume) / cumulative volume, resets daily)
- [x] 1.5 Define a color palette array for auto-assigning distinct colors to indicator instances; ensure same-type multi-instances get different colors

## 2. ChartPane Component

- [x] 2.1 Create `frontend/src/components/charts/ChartPane.tsx` — a thin wrapper around a single `lightweight-charts` instance that exposes its `IChartApi` ref via `useImperativeHandle`
- [x] 2.2 ChartPane accepts props: `height`, `series` (array of `SeriesOutput`), and optional candlestick data for the primary pane; renders the series on the chart
- [x] 2.3 ChartPane handles resize (window `resize` event) and calls `fitContent()` on mount; applies the existing dark theme options (`colors.card`, `colors.grid`, `attributionLogo: false`)

## 3. ChartStack Component

- [x] 3.1 Create `frontend/src/components/charts/ChartStack.tsx` that renders a primary `ChartPane` (candlestick + volume + overlay indicators) and N secondary `ChartPane` components (one per pane-type indicator)
- [x] 3.2 Implement logical range sync: subscribe to `subscribeVisibleLogicalRangeChange` on each chart, propagate `setVisibleLogicalRange` to all other charts, with a `syncing` ref guard to prevent infinite loops
- [x] 3.3 Implement crosshair sync: subscribe to `subscribeCrosshairMove` on each chart, call `setCrosshairPosition` on all other charts for the corresponding time; clear crosshair on mouse leave
- [x] 3.4 Wire the primary pane to always show candlestick + volume data from `bars` prop; filter `activeIndicators` by type `"overlay"` and compute their series for the primary pane
- [x] 3.5 For each pane-type indicator, compute its series and pass to a dedicated secondary `ChartPane`; destroy pane when indicator is removed
- [x] 3.6 Enforce maximum 6 panes (1 primary + 5 secondary); reject additions beyond the limit

## 4. Dynamic Sidebar Indicator Panel

- [x] 4.1 In `DataHub.tsx`, replace the fixed SMA/EMA/Bollinger checkbox section with a dynamic indicator list powered by `useState<ActiveIndicator[]>`
- [x] 4.2 Add an "Add Indicator" button that opens a searchable dropdown listing all entries from `INDICATOR_REGISTRY` by label
- [x] 4.3 Each active indicator renders as a sidebar row: color dot, label with current params, edit toggle, and remove (×) button
- [x] 4.4 Clicking the edit toggle expands inline inputs for each `ParamDef` of that indicator instance; changing a param updates the `ActiveIndicator` state
- [x] 4.5 Clicking the remove button removes the indicator instance from state (which triggers `ChartStack` re-render)
- [x] 4.6 Show a subtle message when the user tries to add a 6th pane-type indicator, indicating the maximum pane limit is reached

## 5. Integration & Cleanup

- [x] 5.1 Update `DataHub.tsx` main area: replace `OHLCVChart` + `SecondaryChart` with the new `ChartStack` component, passing `bars` and `activeIndicators`
- [x] 5.2 Remove `frontend/src/components/charts/SecondaryChart.tsx` — all its logic is now in the indicator registry and ChartStack
- [x] 5.3 Move indicator compute functions that were defined inside `SecondaryChart.tsx` (RSI, MACD, Bias, ATR, OBV) to `frontend/src/lib/indicators.ts` so they are shared
- [x] 5.4 Remove the inline secondary chart selector `<select>` from the `ChartCard` title area in `DataHub.tsx`
- [x] 5.5 Verify that `ChartCard.tsx` title prop still accepts `ReactNode` (already changed) and update if needed

## 6. Browser Verification (Phase 1)

- [x] 6.1 Load Data Hub, add SMA(20) + SMA(50) overlays — verify two distinct lines on the OHLC pane
- [x] 6.2 Add RSI pane indicator — verify new pane appears below OHLC pane with 0-100 y-axis
- [x] 6.3 Scroll/zoom primary pane — verify all panes scroll and zoom together
- [x] 6.4 Hover on secondary pane — verify crosshair appears on primary pane at same time position
- [x] 6.5 Remove all indicators — verify only the primary OHLC + volume pane remains
- [x] 6.6 Try adding 6 pane indicators — verify the 6th is rejected with a message

## 7. Phase 2: Remove volume from primary + always-visible secondary chart

- [x] 7.1 Remove volume data from the primary ChartPane in `ChartStack.tsx` — stop passing `volume` prop so the OHLC pane shows only candlesticks
- [x] 7.2 Add an always-visible secondary chart pane below the primary in `ChartStack.tsx` with a dropdown selector for choosing the indicator (Volume default, RSI, MACD, Bias, ATR, OBV)
- [x] 7.3 Add inline parameter inputs next to the secondary chart dropdown for indicators with configurable params (e.g., RSI period, MACD fast/slow/signal)
- [x] 7.4 Wire the secondary chart pane into the logical range and crosshair sync system so it scrolls/zooms with the primary
- [x] 7.5 The secondary chart is separate from the sidebar "Add Indicator" pane indicators — sidebar overlays go on the price pane, the secondary chart is its own fixed slot

## 8. Browser Verification (Phase 2)

- [x] 8.1 Load Data Hub — verify primary chart shows only OHLC candlesticks (no volume overlay)
- [x] 8.2 Verify the secondary chart shows Volume by default below the primary
- [x] 8.3 Switch secondary chart to RSI — verify RSI renders and parameter input appears
- [x] 8.4 Change RSI period from 14 to 21 — verify chart updates
- [x] 8.5 Scroll primary chart — verify secondary chart scrolls in sync
- [x] 8.6 Add SMA overlay from sidebar — verify it appears on primary pane while secondary chart remains
