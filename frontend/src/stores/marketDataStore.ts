import { create } from "zustand";
import type { OHLCVBar } from "@/lib/api";

interface MarketDataState {
  bars: OHLCVBar[];
  lastLiveTick: OHLCVBar | null;
  prevClose: number | null;
  symbol: string;
  tfMinutes: number;
  start: string;
  end: string;
  loading: boolean;
  error: string | null;
  setBars: (bars: OHLCVBar[]) => void;
  processLiveTick: (tick: { price: number; volume: number; timestamp: string }) => void;
  setQuery: (q: { symbol?: string; tfMinutes?: number; start?: string; end?: string }) => void;
  setLoading: (v: boolean) => void;
  setError: (e: string | null) => void;
}

export const useMarketDataStore = create<MarketDataState>((set, get) => ({
  bars: [],
  lastLiveTick: null,
  prevClose: null,
  symbol: "TX",
  tfMinutes: 60,
  start: "2025-03-01",
  end: "2026-03-14",
  loading: false,
  error: null,
  setBars: (bars) => set({
    bars,
    error: null,
    lastLiveTick: bars.length > 0 ? bars[bars.length - 1] : null,
  }),
  processLiveTick: (tick) => {
    const state = get();
    if (state.bars.length === 0) return;

    const tickTime = new Date(tick.timestamp).getTime();
    const tfMs = state.tfMinutes * 60_000;

    if (state.lastLiveTick) {
      const lastTickTime = new Date(state.lastLiveTick.timestamp).getTime();
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
        const newBarTime = tickTime % tfMs === 0
          ? new Date(tickTime).toISOString()
          : new Date(Math.floor(tickTime / tfMs) * tfMs + tfMs).toISOString();
        const prevClose = state.lastLiveTick.close;
        set({
          prevClose,
          bars: [...state.bars, completedBar],
          lastLiveTick: {
            timestamp: newBarTime,
            open: tick.price,
            high: tick.price,
            low: tick.price,
            close: tick.price,
            volume: tick.volume,
          },
        });
      }
    } else {
      const lastBar = state.bars[state.bars.length - 1];
      if (lastBar) {
        const lastBarTime = new Date(lastBar.timestamp).getTime();
        if (tickTime < lastBarTime + tfMs) {
          const prevClose = lastBar.close;
          set({
            prevClose,
            lastLiveTick: {
              ...lastBar,
              high: Math.max(lastBar.high, tick.price),
              low: Math.min(lastBar.low, tick.price),
              close: tick.price,
              volume: lastBar.volume + tick.volume,
            },
          });
        } else {
          const completedBar = { ...lastBar };
          const newBarTime = tickTime % tfMs === 0
            ? new Date(tickTime).toISOString()
            : new Date(Math.floor(tickTime / tfMs) * tfMs + tfMs).toISOString();
          const prevClose = lastBar.close;
          set({
            prevClose,
            bars: [...state.bars, completedBar],
            lastLiveTick: {
              timestamp: newBarTime,
              open: tick.price,
              high: tick.price,
              low: tick.price,
              close: tick.price,
              volume: tick.volume,
            },
          });
        }
      }
    }
  },
  setQuery: (q) => set(q),
  setLoading: (loading) => set({ loading }),
  setError: (error) => set({ error, loading: false }),
}));
