import { create } from "zustand";
import type { AccountInfo } from "@/lib/api";

interface Position {
  symbol: string;
  side: string;
  quantity: number;
  avg_entry_price: number;
  unrealized_pnl: number;
}

interface RiskAlert {
  severity: string;
  trigger: string;
  details: string;
  timestamp: string;
}

interface TradingState {
  accounts: AccountInfo[];
  wsConnected: boolean;
  positions: Position[];
  riskAlerts: RiskAlert[];
  warRoomData: Record<string, unknown> | null;
  setAccounts: (a: AccountInfo[]) => void;
  setWsConnected: (v: boolean) => void;
  setPositions: (p: Position[]) => void;
  addRiskAlert: (a: RiskAlert) => void;
  setWarRoomData: (d: Record<string, unknown>) => void;
}

export const useTradingStore = create<TradingState>((set) => ({
  accounts: [],
  wsConnected: false,
  positions: [],
  riskAlerts: [],
  warRoomData: null,
  setAccounts: (accounts) => set({ accounts }),
  setWsConnected: (wsConnected) => set({ wsConnected }),
  setPositions: (positions) => set({ positions }),
  addRiskAlert: (alert) => set((s) => ({ riskAlerts: [alert, ...s.riskAlerts].slice(0, 100) })),
  setWarRoomData: (warRoomData) => set({ warRoomData }),
}));
