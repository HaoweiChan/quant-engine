import { create } from "zustand";
import type { StrategyInfo } from "@/lib/api";
import { fetchStrategies, fetchActiveParams, reloadStrategies } from "@/lib/api";


interface StrategyState {
  strategies: StrategyInfo[];
  strategy: string;
  symbol: string;
  startDate: string;
  endDate: string;
  slippageBps: number;
  commissionBps: number;
  commissionFixed: number;
  initialCapital: number;
  maxLoss: number;
  params: Record<string, number>;
  intraday: boolean;
  loading: boolean;
  locked: boolean;
  setIntraday: (v: boolean) => void;
  setStrategy: (slug: string) => void;
  setSymbol: (s: string) => void;
  setDates: (start: string, end: string) => void;
  setCosts: (slippage: number, commission: number) => void;
  setCommissionFixed: (v: number) => void;
  setParam: (key: string, value: number) => void;
  setParams: (p: Record<string, number>) => void;
  setInitialCapital: (v: number) => void;
  setMaxLoss: (v: number) => void;
  resetParams: () => void;
  setLoading: (v: boolean) => void;
  setLocked: (v: boolean) => void;
  loadStrategies: () => Promise<void>;
  reloadStrategies: () => Promise<void>;
}

export const useStrategyStore = create<StrategyState>((set, get) => ({
  strategies: [],
  strategy: "",
  symbol: "TX",
  startDate: "2025-08-01",
  endDate: "2026-03-14",
  slippageBps: 1,        // matches backend cost_config.slippage_bps (0.1% * 10)
  commissionBps: 0,
  commissionFixed: 100,  // NT$100 per contract for TX (default)
  initialCapital: 2_000_000,
  maxLoss: 500_000,
  params: {},
  intraday: false,
  loading: false,
  locked: false,

  setIntraday: (intraday) => set({ intraday }),

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
          // Merge all active params over defaults (no schema filtering)
          const merged = { ...defaults };
          for (const [k, v] of Object.entries(active.params)) {
            if (typeof v === "number") merged[k] = v;
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
  setCommissionFixed: (commissionFixed) => set({ commissionFixed }),
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

  reloadStrategies: async () => {
    const strategies = await reloadStrategies();
    set({ strategies });
    if (strategies.length > 0 && !get().strategy) {
      get().setStrategy(strategies[0].slug);
    }
  },
}));
