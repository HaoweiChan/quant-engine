import { create } from "zustand";

type PrimaryTab = "datahub" | "strategy" | "trading";
type StrategySubTab = "editor" | "tearsheet" | "paramsweep" | "stresstest" | "portfolio";
type TradingSubTab = "accounts" | "warroom" | "blotter" | "risk";

interface UiState {
  primaryTab: PrimaryTab;
  strategySubTab: StrategySubTab;
  tradingSubTab: TradingSubTab;
  setPrimaryTab: (tab: PrimaryTab) => void;
  setStrategySubTab: (tab: StrategySubTab) => void;
  setTradingSubTab: (tab: TradingSubTab) => void;
}

export const useUiStore = create<UiState>((set) => ({
  primaryTab: "datahub",
  strategySubTab: "editor",
  tradingSubTab: "accounts",
  setPrimaryTab: (tab) => set({ primaryTab: tab }),
  setStrategySubTab: (tab) => set({ strategySubTab: tab }),
  setTradingSubTab: (tab) => set({ tradingSubTab: tab }),
}));
