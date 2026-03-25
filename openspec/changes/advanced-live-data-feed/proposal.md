## Why

The WebSocket live feed infrastructure exists (`/ws/live-feed` broadcasts ticks, `useLiveFeed` hook connects) but the frontend does nothing with incoming ticks — the `onmessage` handler is a stub. The OHLCV chart uses `setData()` O(N) on every render, which will freeze the browser under live tick injection. We need to complete the tick-to-chart pipeline with client-side bar aggregation and O(1) chart updates so the Trading tab displays a live-updating candle chart during market hours.

## What Changes

- Add `lastLiveTick` and `processLiveTick()` to `marketDataStore` for client-side bar aggregation (tick → OHLCV bar building with timeframe rollover)
- Wire `useLiveFeed` hook to call `processLiveTick` on incoming tick messages instead of the current no-op stub
- Split `OHLCVChart` rendering into two paths: O(N) `setData()` for historical bulk load, O(1) `.update()` for live tick-driven candle/volume updates
- Add a live price display component showing current price, tick direction, and symbol — driven by the same live tick stream
- Add connection status indicator for the WebSocket feed

## Capabilities

### New Capabilities
- `live-bar-aggregation`: Client-side tick-to-OHLCV bar building in the market data store, with timeframe boundary rollover and volume accumulation
- `live-chart-update`: Decoupled chart rendering — historical setData path vs live O(1) update path using lightweight-charts `.update()` method
- `live-price-display`: Real-time price ticker component showing current price, tick direction indicator, and symbol label

### Modified Capabilities
- `react-frontend`: The `useLiveFeed` hook requirements change from passive connection to active tick processing; `marketDataStore` gains live tick state
- `fastapi-backend`: No spec-level requirement changes — existing WebSocket broadcast contract is sufficient

## Impact

- **Frontend stores**: `marketDataStore.ts` gains new state fields and `processLiveTick` action
- **Frontend hooks**: `useLiveFeed.ts` wired to store instead of no-op
- **Frontend charts**: `OHLCVChart.tsx` gains a second useEffect for live updates
- **New component**: Live price display widget for the Trading tab header area
- **No backend changes**: Existing `Broadcaster` and tick format are sufficient
- **No new dependencies**: Uses existing `lightweight-charts` `.update()` API and Zustand
