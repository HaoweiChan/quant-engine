## Context

The Data Hub page currently uses two independent `lightweight-charts` instances: `OHLCVChart` (candlestick + volume) and `SecondaryChart` (switchable single indicator). These charts do not share a time scale — scrolling or zooming one has no effect on the other. The indicator system is hardcoded: three overlay toggles (SMA/EMA/Bollinger) with fixed single-instance checkboxes, and a dropdown selector for one secondary indicator at a time.

Users expect TradingView-like behavior: synchronized panes, stacking multiple indicators simultaneously, and per-instance parameter editing. This design describes the architecture to achieve that.

**Current state:**

```
┌─────────────────────────────────────────┐
│  Sidebar                                │
│  ┌──────────────────────┐               │
│  │ [x] SMA  period: 20  │  (hardcoded) │
│  │ [x] EMA  period: 12  │  (hardcoded) │
│  │ [x] BB   period: 20  │  (hardcoded) │
│  └──────────────────────┘               │
├─────────────────────────────────────────┤
│  OHLCVChart   (independent timeScale)   │
│  SecondaryChart (independent timeScale) │
│       └─ dropdown: Volume | RSI | ...   │
└─────────────────────────────────────────┘
```

**Target state:**

```
┌─────────────────────────────────────────┐
│  Sidebar                                │
│  ┌──────────────────────┐               │
│  │ [+ Add Indicator]     │  (dynamic)   │
│  │  SMA(20) [x]          │              │
│  │  SMA(50) [x]          │              │
│  │  RSI(14) [x]          │  pane        │
│  │  MACD(12/26/9) [x]    │  pane        │
│  └──────────────────────┘               │
├─────────────────────────────────────────┤
│  ChartStack (shared logicalRange)       │
│  ┌── Price pane ────────────────────┐   │
│  │  Candlestick + Vol + SMA + SMA   │   │
│  ├── RSI pane ──────────────────────┤   │
│  │  RSI(14) line                     │   │
│  ├── MACD pane ─────────────────────┤   │
│  │  MACD histogram + signal + line   │   │
│  └──────────────────────────────────┘   │
└─────────────────────────────────────────┘
```

## Goals / Non-Goals

**Goals:**
- Synchronized scrolling, zooming, and crosshair across all chart panes
- An extensible indicator registry where adding a new indicator requires only a registry entry (no component changes)
- Multiple simultaneous indicator instances with per-instance parameter editing
- Clean separation: registry knows how to compute; `ChartStack` knows how to render/sync

**Non-Goals:**
- Custom drawing tools (trend lines, Fibonacci, annotations)
- Server-side indicator computation — all indicators remain client-side
- Sharing indicator state with Backtest or Trading pages (Data Hub only)
- Real-time streaming / WebSocket data (Data Hub is load-on-demand)
- Persisting user indicator preferences across sessions (can be added later)

## Decisions

### Decision 1: Sync via logical range, not time range

**Choice**: Use `subscribeVisibleLogicalRangeChange()` + `setVisibleLogicalRange()` for time scale synchronization between panes.

**Alternatives considered**:
- `subscribeVisibleTimeRangeChange()` + `setVisibleRange()` — requires all panes to have identical timestamp arrays. Breaks when an indicator has fewer data points (e.g., RSI starts at bar 14). Also known to cause null-reference errors when called before data is loaded.
- Single chart with multiple price scales — lightweight-charts supports this, but it forces all panes into one chart canvas, making independent y-axis scaling impossible and creating visual clutter.

**Rationale**: Logical range uses bar indices, not timestamps, which is robust when panes have different numbers of valid data points. The lightweight-charts docs and community recommend this approach for multi-pane setups.

### Decision 2: Crosshair sync via `subscribeCrosshairMove`

**Choice**: Designate the primary (OHLC) chart as the "leader". Subscribe to `subscribeCrosshairMove` on the leader. On each move event, call `setCrosshairPosition(price, time, series)` on follower panes (and vice-versa for follower-to-leader).

**Rationale**: Two-way sync ensures hovering on any pane syncs all others. The performance is acceptable because crosshair events fire at pointer-move rate, and `setCrosshairPosition` is a cheap DOM update.

### Decision 3: Typed indicator registry with `IndicatorDef` interface

**Choice**: Define a `IndicatorDef` interface:

```typescript
interface IndicatorDef {
  id: string;                          // e.g. "sma", "rsi", "macd"
  label: string;                       // e.g. "SMA", "RSI (14)"
  type: "overlay" | "pane";           // overlay → drawn on price chart; pane → own sub-chart
  params: ParamDef[];                  // configurable parameters with defaults
  compute: (bars: OHLCVBar[], params: Record<string, number>) => SeriesOutput[];
}
```

Where `SeriesOutput` is:

```typescript
interface SeriesOutput {
  label: string;
  type: "line" | "histogram";
  color: string;
  data: { time: number; value: number; color?: string }[];
}
```

All existing indicator functions (`sma`, `ema`, `bollingerBands`, `computeRSI`, `computeMACD`, `computeBias`, `computeATR`, `computeOBV`) are wrapped in this interface. Adding a new indicator means one new entry in the registry array.

**Alternatives considered**:
- Keep indicators as ad-hoc functions dispatched by `if/else` in chart components — doesn't scale, hard to add new indicators, each new indicator requires chart component changes.

### Decision 4: `ChartStack` as the orchestrating component

**Choice**: A single `ChartStack` component that:
1. Receives `bars: OHLCVBar[]` and `activeIndicators: ActiveIndicator[]`
2. Always renders a primary pane (candlestick + volume + overlay indicators)
3. Renders one sub-pane per active pane-type indicator
4. Manages refs to all chart instances for sync wiring
5. Wires `subscribeVisibleLogicalRangeChange` and `subscribeCrosshairMove` across all panes in a `useEffect`

Each pane is a thin `<ChartPane>` component that creates a `lightweight-charts` instance and exposes its `IChartApi` ref upward via `useImperativeHandle`.

**Rationale**: Centralizing sync logic in one component prevents the complexity of distributed sync where each chart tries to manage its own listeners.

### Decision 5: Dynamic sidebar indicator panel

**Choice**: Replace fixed checkboxes with a list-based UI:
- "Add Indicator" button opens a searchable dropdown (filters registry by name)
- Each active indicator shows as a row: `[color dot] Label(params) [edit] [x]`
- Clicking "edit" expands inline param inputs
- Clicking "x" removes the indicator instance
- State is a `useState<ActiveIndicator[]>` array where each entry has: `{ id: string, registryId: string, params: Record<string, number> }`

### Decision 6: Pane height allocation

**Choice**: Primary pane gets a fixed height of 340px. Each secondary pane gets 140px. Total chart area grows as indicators are added, with the page scrolling naturally.

**Alternatives considered**:
- Flex-based proportional heights in a fixed container — causes panes to shrink to unusable sizes when many indicators are added.
- Draggable pane resize handles — nice but complex; deferred as a future enhancement.

## Risks / Trade-offs

- **[Performance with many panes]** → Each pane is a separate `<canvas>` element. Mitigated by downsampling (already in place at 4000 points) and by capping the maximum number of simultaneous panes to 6.
- **[Sync loop]** → Chart A's logical range change triggers Chart B's setter, which may fire Chart B's change listener. Mitigated by a `syncing` ref flag: skip setter calls while `syncing.current === true`.
- **[Overlay + pane ambiguity]** → Some indicators (e.g., Volume) could be either overlay or pane. Resolved by the registry's `type` field — each indicator has exactly one type. Volume defaults to pane.
- **[Breaking change to sidebar]** → The fixed SMA/EMA/BB checkboxes are removed. Users who relied on them will use the new "Add Indicator" flow instead. The same indicators are still available — the UX path changes, not the capability.
