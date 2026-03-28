## 1. Market Data Store — Live Tick State

- [x] 1.1 Add `lastLiveTick: OHLCVBar | null` field to `marketDataStore` (initialized to `null`). Update `setBars()` to set `lastLiveTick` to the last bar of the provided array (or `null` if empty).
- [x] 1.2 Implement `processLiveTick({ price, volume, timestamp })` action: aggregate tick into current bar (update high/low/close/volume on `lastLiveTick` without modifying `bars`), or roll over to new bar when timeframe boundary is crossed (append completed bar to `bars`, create new `lastLiveTick` with timestamp floored to boundary).
- [x] 1.3 Add `prevClose: number | null` field to store to track previous close for tick direction calculation. Update on each `processLiveTick` call before overwriting `lastLiveTick.close`.

## 2. Live Feed Hook — Tick Processing

- [x] 2.1 Wire `useLiveFeed` `onmessage` handler to call `marketDataStore.processLiveTick()` for `type: "tick"` messages, extracting `{ price, volume, timestamp }` from the message payload. Remove the stub comment.
- [x] 2.2 Ensure non-tick messages (`type: "order"`, `type: "pong"`) and malformed messages are silently ignored (existing behavior preserved).

## 3. Chart Component — O(1) Live Updates

- [x] 3.1 Add `lastLiveTick` subscription from `marketDataStore` in `OHLCVChart` component.
- [x] 3.2 Add a second `useEffect` hook dependent on `lastLiveTick` that calls `candleSeriesRef.current.update()` with the live bar's OHLCV values and `volSeriesRef.current.update()` with directional volume color. Guard against `null` `lastLiveTick` and uninitialized chart refs.
- [x] 3.3 Verify the existing historical `useEffect` (dependent on `data`) is unchanged and only triggers on bulk loads — no interference with the live path.

## 4. Live Price Ticker Component

- [x] 4.1 Create `LivePriceTicker` component at `frontend/src/components/trading/LivePriceTicker.tsx`. Subscribe to `lastLiveTick`, `prevClose`, and `symbol` from `marketDataStore`. Display current close price, direction arrow (green up / red down / neutral), and symbol label. Show dash (`—`) when no live data.
- [x] 4.2 Add WebSocket connection status indicator reading `wsConnected` from `tradingStore`. Display green "LIVE" badge when connected, red "OFFLINE" when disconnected, amber "RECONNECTING" during backoff.
- [x] 4.3 Mount `LivePriceTicker` in the Trading tab header area (War Room or parent layout).

## 5. Tests

- [x] 5.1 Unit test `processLiveTick` — aggregation within timeframe: verify high/low/close/volume updates, `bars` array unchanged.
- [x] 5.2 Unit test `processLiveTick` — rollover to new bar: verify old bar appended to `bars`, new `lastLiveTick` created with floored timestamp.
- [x] 5.3 Unit test `processLiveTick` — early return when `bars` is empty.
- [x] 5.4 Unit test `setBars` — verify `lastLiveTick` set to last bar, or `null` for empty array.
- [x] 5.5 Component test `LivePriceTicker` — renders price, direction arrow, symbol, and connection status badge for connected/disconnected states.
- [x] 5.6 Component test `OHLCVChart` — verify `.update()` is called (not `setData()`) when `lastLiveTick` changes.
