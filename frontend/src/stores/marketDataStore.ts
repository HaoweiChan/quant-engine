import { create } from "zustand";
import type { OHLCVBar } from "@/lib/api";

interface MarketDataState {
  bars: OHLCVBar[];
  symbol: string;
  tfMinutes: number;
  start: string;
  end: string;
  loading: boolean;
  error: string | null;
  setBars: (bars: OHLCVBar[]) => void;
  setQuery: (q: { symbol?: string; tfMinutes?: number; start?: string; end?: string }) => void;
  setLoading: (v: boolean) => void;
  setError: (e: string | null) => void;
}

export const useMarketDataStore = create<MarketDataState>((set) => ({
  bars: [],
  symbol: "TX",
  tfMinutes: 60,
  start: "2025-03-01",
  end: "2026-03-14",
  loading: false,
  error: null,
  setBars: (bars) => set({ bars, error: null }),
  setQuery: (q) => set(q),
  setLoading: (loading) => set({ loading }),
  setError: (error) => set({ error, loading: false }),
}));
