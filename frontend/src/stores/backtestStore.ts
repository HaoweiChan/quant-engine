import { create } from "zustand";
import type { BacktestResult } from "@/lib/api";

interface BacktestState {
  result: BacktestResult | null;
  loading: boolean;
  error: string | null;
  progress: number;
  progressMessage: string;
  setResult: (r: BacktestResult | null) => void;
  setLoading: (v: boolean) => void;
  setError: (e: string | null) => void;
  setProgress: (pct: number, msg: string) => void;
}

export const useBacktestStore = create<BacktestState>((set) => ({
  result: null,
  loading: false,
  error: null,
  progress: 0,
  progressMessage: "",
  setResult: (result) => set({ result, loading: false, error: null }),
  setLoading: (loading) => set({ loading }),
  setError: (error) => set({ error, loading: false }),
  setProgress: (progress, progressMessage) => set({ progress, progressMessage }),
}));
