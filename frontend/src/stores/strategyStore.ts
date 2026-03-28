import { create } from "zustand";
import type { StrategyInfo } from "@/lib/api";
import { fetchStrategies, fetchActiveParams } from "@/lib/api";


interface StrategyState {
  strategies: StrategyInfo[];
  strategy: string;
  symbol: string;
  startDate: string;
  endDate: string;
  slippageBps: number;
  commissionBps: number;
  initialCapital: number;
  maxLoss: number;
  params: Record<string, number>;
  loading: boolean;
  locked: boolean;
  setStrategy: (slug: string) => void;
  setSymbol: (s: string) => void;
  setDates: (start: string, end: string) => void;
  setCosts: (slippage: number, commission: number) => void;
  setParam: (key: string, value: number) => void;
  setParams: (p: Record<string, number>) => void;
  setInitialCapital: (v: number) => void;
  setMaxLoss: (v: number) => void;
  resetParams: () => void;
  setLoading: (v: boolean) => void;
  setLocked: (v: boolean) => void;
  loadStrategies: () => Promise<void>;
}

export const useStrategyStore = create<StrategyState>((set, get) => ({
  strategies: [],
  strategy: "",
  symbol: "TX",
  startDate: "2025-08-01",
  endDate: "2026-03-14",
  slippageBps: 0,
  commissionBps: 0,
  initialCapital: 2_000_000,
  maxLoss: 500_000,
  params: {},
  loading: false,
  locked: false,

  setStrategy: (slug) => {
    set({ strategy: slug });
    const strat = get().strategies.find((s) => s.slug === slug);
    if (!strat?.param_grid) return;
    const defaults: Record<string, number> = {};
    for (const [k, v] of Object.entries(strat.param_grid)) {
      defaults[k] = v.value ?? v.default?.[0] ?? 0;
    }
    fetchActiveParams(slug)
      .then((active) => {
        if (active.source === "registry" && active.params) {
          const merged = { ...defaults };
          for (const [k, v] of Object.entries(active.params)) {
            if (k in merged && typeof v === "number") merged[k] = v;
          }
          set({ params: merged });
        } else {
          set({ params: defaults });
        }
      })
      .catch(() => set({ params: defaults }));
  },

  setSymbol: (symbol) => set({ symbol }),
  setDates: (startDate, endDate) => set({ startDate, endDate }),
  setCosts: (slippageBps, commissionBps) => set({ slippageBps, commissionBps }),
  setParam: (key, value) => set((s) => ({ params: { ...s.params, [key]: value } })),
  setParams: (params) => set({ params }),
  setInitialCapital: (initialCapital) => set({ initialCapital }),
  setMaxLoss: (maxLoss) => set({ maxLoss }),
  setLoading: (loading) => set({ loading }),
  setLocked: (locked) => set({ locked }),

  resetParams: () => {
    const strat = get().strategies.find((s) => s.slug === get().strategy);
    if (!strat?.param_grid) return;
    const defaults: Record<string, number> = {};
    for (const [k, v] of Object.entries(strat.param_grid)) {
      defaults[k] = v.value ?? v.default?.[0] ?? 0;
    }
    set({ params: defaults });
  },

  loadStrategies: async () => {
    const strategies = await fetchStrategies();
    set({ strategies });
    if (strategies.length > 0 && !get().strategy) {
      get().setStrategy(strategies[0].slug);
    }
  },
}));
