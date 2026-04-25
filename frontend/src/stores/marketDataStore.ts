import { createStore } from "zustand/vanilla";
import { useStore } from "zustand";
import type { OHLCVBar } from "@/lib/api";
import { parseTimestampMs, formatTaipeiTimestamp, normalizeToNaiveTaipei } from "@/lib/time";


// Re-export parseTimestampMs as parseBarTimestamp for backward compatibility
const parseBarTimestamp = parseTimestampMs;

function createLiveBar(tick: { price: number; volume: number }, tickTime: number, tfMs: number): OHLCVBar {
  // Left-aligned bucketing: bar timestamp = start of the bucket
  // E.g., for a 1h bucket, a tick at 09:30 goes into the 09:00 bar
  const newBarEpoch = Math.floor(tickTime / tfMs) * tfMs;
  const newBarTime = formatTaipeiTimestamp(newBarEpoch);
  return {
    timestamp: newBarTime,
    open: tick.price,
    high: tick.price,
    low: tick.price,
    close: tick.price,
    volume: tick.volume,
  };
}


export interface MarketDataState {
  bars: OHLCVBar[];
  lastLiveTick: OHLCVBar | null;
  prevClose: number | null;
  symbol: string;
  tfMinutes: number;
  start: string;
  end: string;
  loading: boolean;
  loadingOlder: boolean;
  error: string | null;
  setBars: (bars: OHLCVBar[]) => void;
  prependBars: (olderBars: OHLCVBar[]) => void;
  processLiveTick: (tick: { price: number; volume: number; timestamp: string }) => void;
  setQuery: (q: { symbol?: string; tfMinutes?: number; start?: string; end?: string }) => void;
  setLoading: (v: boolean) => void;
  setLoadingOlder: (v: boolean) => void;
  setError: (e: string | null) => void;
}

export function createMarketDataStore() {
  return createStore<MarketDataState>((set, get) => ({
    bars: [],
    lastLiveTick: null,
    prevClose: null,
    symbol: "TX",
    tfMinutes: 60,
    start: "2025-03-01",
    end: "2026-03-14",
    loading: false,
    loadingOlder: false,
    error: null,
    setBars: (bars) => set({
      bars,
      error: null,
      // Don't initialize lastLiveTick to last completed bar - it should only
      // be set when actual live tick data arrives via processLiveTick.
      // This prevents duplicate timestamps when boundary crosses.
      lastLiveTick: null,
    }),
    prependBars: (olderBars) => {
      const state = get();
      if (olderBars.length === 0) return;
      const existing = new Set(state.bars.map((b) => b.timestamp));
      const fresh = olderBars.filter((b) => !existing.has(b.timestamp));
      if (fresh.length === 0) return;
      set({ bars: [...fresh, ...state.bars], start: olderBars[0].timestamp.slice(0, 10) });
    },
    processLiveTick: (tick) => {
      const state = get();
      // Normalize offset-tagged timestamps (e.g. +08:00) to naive Taipei format
      // so epoch comparisons with naive DB bar timestamps work correctly.
      const normalizedTs = normalizeToNaiveTaipei(tick.timestamp);
      const tickTime = parseBarTimestamp(normalizedTs);
      if (!Number.isFinite(tickTime)) return;
      const tfMs = state.tfMinutes * 60_000;
      if (state.bars.length === 0) {
        const seededBar = createLiveBar(tick, tickTime, tfMs);
        set({ bars: [seededBar], lastLiveTick: seededBar, prevClose: null });
        return;
      }

      if (state.lastLiveTick) {
        const lastTickTime = parseBarTimestamp(state.lastLiveTick.timestamp);
        if (!Number.isFinite(lastTickTime)) return;
        const boundaryTime = lastTickTime + tfMs;

        if (tickTime < boundaryTime) {
          const prevClose = state.lastLiveTick.close;
          set({
            prevClose,
            lastLiveTick: {
              ...state.lastLiveTick,
              high: Math.max(state.lastLiveTick.high, tick.price),
              low: Math.min(state.lastLiveTick.low, tick.price),
              close: tick.price,
              volume: state.lastLiveTick.volume + tick.volume,
            },
          });
        } else {
          const completedBar = { ...state.lastLiveTick };
          const newBar = createLiveBar(tick, tickTime, tfMs);
          const prevClose = state.lastLiveTick.close;
          set({
            prevClose,
            bars: [...state.bars, completedBar],
            lastLiveTick: newBar,
          });
        }
      } else {
        const lastBar = state.bars[state.bars.length - 1];
        if (lastBar) {
          const lastBarTime = parseBarTimestamp(lastBar.timestamp);
          if (!Number.isFinite(lastBarTime)) return;
          if (tickTime < lastBarTime + tfMs) {
            // Tick is within the same bar period as the last historical bar.
            // The historical bar already has complete volume from the database,
            // so we only update OHLC prices - do NOT add tick.volume to avoid
            // double-counting volume that's already in the historical data.
            const prevClose = lastBar.close;
            set({
              prevClose,
              lastLiveTick: {
                ...lastBar,
                high: Math.max(lastBar.high, tick.price),
                low: Math.min(lastBar.low, tick.price),
                close: tick.price,
                // Keep historical volume unchanged - don't add tick.volume
              },
            });
          } else {
            // Tick is in a new bar period - start fresh with just this tick's volume
            const newBar = createLiveBar(tick, tickTime, tfMs);
            const prevClose = lastBar.close;
            set({ prevClose, lastLiveTick: newBar });
          }
        }
      }
    },
    setQuery: (q) => {
      const state = get();
      // Clear bars when timeframe changes to prevent stale data display
      if (q.tfMinutes !== undefined && q.tfMinutes !== state.tfMinutes) {
        set({ ...q, bars: [], lastLiveTick: null, prevClose: null });
      } else {
        set(q);
      }
    },
    setLoading: (loading) => set({ loading }),
    setLoadingOlder: (loadingOlder) => set({ loadingOlder }),
    setError: (error) => set({ error, loading: false }),
  }));
}

// Default singleton for backward compatibility
const defaultStore = createMarketDataStore();

// Export type for consumers that create their own instance
export type MarketDataStore = ReturnType<typeof createMarketDataStore>;

// Hook overloads: supports both useMarketDataStore() and useMarketDataStore(selector)
export function useMarketDataStore(): MarketDataState;
export function useMarketDataStore<T>(selector: (s: MarketDataState) => T): T;
export function useMarketDataStore<T>(selector?: (s: MarketDataState) => T) {
  // eslint-disable-next-line react-hooks/rules-of-hooks
  return useStore(defaultStore, selector as (s: MarketDataState) => T);
}

// Expose getState / setState / subscribe on the hook for backward compatibility
// (tests and components use useMarketDataStore.getState(), .setState(), etc.)
useMarketDataStore.getState = defaultStore.getState;
useMarketDataStore.setState = defaultStore.setState;
useMarketDataStore.subscribe = defaultStore.subscribe;
