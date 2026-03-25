## Context

The quant-engine dashboard currently fetches historical OHLCV bars via REST (`GET /api/ohlcv`) and renders them with `lightweight-charts` `setData()`. A WebSocket live feed (`/ws/live-feed`) broadcasts raw ticks from the Shioaji callback bridge, but the frontend discards them — `useLiveFeed.ts` has a stub `onmessage` handler.

The doc at `docs/live-data-feed.md` identifies this gap and prescribes a 3-step fix: store-level bar aggregation, hook wiring, and O(1) chart updates. This design follows that approach with minor adjustments for the agreed scope (client-side aggregation, low tick rate, chart + price display, single symbol).

```
┌─────────────┐     REST /api/ohlcv      ┌────────────────────┐
│   Backend    │ ──────────────────────── │  marketDataStore   │
│  (FastAPI)   │                          │  .bars (historical)│
│              │  WS /ws/live-feed        │  .lastLiveTick     │
│  Broadcaster │ ─── tick JSON ─────────► │  .processLiveTick()│
└─────────────┘                          └────────┬───────────┘
                                                  │
                              ┌────────────────────┼────────────────┐
                              │                    │                │
                        ┌─────▼─────┐    ┌────────▼───────┐  ┌────▼──────┐
                        │ OHLCVChart│    │ LivePriceTicker │  │ useLiveFeed│
                        │ .update() │    │ price + arrow   │  │ (hook)    │
                        │ O(1)/tick │    │                 │  │ → store   │
                        └───────────┘    └────────────────┘  └───────────┘
```

## Goals / Non-Goals

**Goals:**
- Complete the tick-to-chart pipeline so live candles update in real-time during market hours
- Use O(1) `lightweight-charts` `.update()` for live ticks, avoiding O(N) `setData()` re-renders
- Show a live price ticker (current price, tick direction) in the Trading tab
- Keep `lastLiveTick` isolated from the `bars` array to prevent unnecessary React reconciliation
- Indicate WebSocket connection status in the UI

**Non-Goals:**
- Server-side bar aggregation — ticks stay raw, client builds bars
- Multi-symbol subscription — single active symbol at a time
- Order book depth, live PnL recalculation, or live indicator recomputation
- High-frequency tick buffering or rAF batching (low tick rate assumed, <5/sec)
- Backend changes — existing `Broadcaster` and tick message format are sufficient

## Decisions

### Decision 1: Client-side bar aggregation in Zustand store

**Choice:** Add `processLiveTick()` to `marketDataStore` that aggregates ticks into the current bar or rolls over to a new bar based on `tfMinutes`.

**Alternatives considered:**
- *Server-side aggregation*: Would require backend changes, adds latency, couples timeframe logic to the server. Rejected — scope says no backend changes and low tick rate doesn't justify the complexity.
- *Aggregation in the chart component*: Would mix rendering with data logic. Rejected — violates separation of concerns.

**Rationale:** The store is the single source of truth for market data. Aggregation logic there keeps the hook thin (just wiring) and the chart component pure (just rendering).

### Decision 2: Isolated `lastLiveTick` state field

**Choice:** Store the mutating current bar in `lastLiveTick` separately from the `bars` array. Only append to `bars` on timeframe rollover.

**Rationale:** Zustand shallow-compares top-level fields. If we mutated `bars[bars.length-1]` on every tick, React would reconcile the entire array. By isolating `lastLiveTick`, only the chart's live-update effect and price ticker re-render — the rest of the UI stays untouched.

### Decision 3: Dual-path chart rendering

**Choice:** Two `useEffect` hooks in `OHLCVChart`:
1. **Historical effect** — triggers on `data` changes, calls `setData()` O(N) once
2. **Live effect** — triggers on `lastLiveTick` changes, calls `.update()` O(1) per tick

**Rationale:** This matches `lightweight-charts`' intended API. `.update()` with an existing timestamp mutates the current candle; with a new timestamp, it appends. No need for custom merge logic.

### Decision 4: Price ticker as a simple subscribed component

**Choice:** A `LivePriceTicker` component that subscribes to `lastLiveTick` from the store and displays price + direction arrow (comparing to previous close).

**Alternatives considered:**
- *Derive from WebSocket directly*: Would bypass the store, creating two sources of truth. Rejected.
- *Include in chart tooltip*: Not persistent/visible enough for quick glance. Rejected.

## Risks / Trade-offs

**[Risk] Tick arrives before historical bars loaded** → `processLiveTick` returns early if `bars` is empty. First ticks during initial load are safely dropped — no data corruption.

**[Risk] Timeframe boundary alignment** → Ticks may not land exactly on boundary. The rollover check uses `tickTime >= currentBarTime + tfMs` which is correct for forward-looking boundaries. For production accuracy, the new bar's timestamp should be floored to the timeframe boundary.

**[Risk] Stale `lastLiveTick` after symbol/timeframe change** → When `setBars` is called with new historical data (symbol or timeframe switch), reset `lastLiveTick` to the last bar of the new dataset. This prevents ghost candles from the previous symbol.

**[Trade-off] No tick buffering** → At low tick rates (<5/sec), directly calling `.update()` per tick is fine. If tick rates increase in the future, a rAF-batched approach would be needed — but that's explicitly a non-goal for now.
