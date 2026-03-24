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
  activeAccountId: string | null;
  setAccounts: (a: AccountInfo[]) => void;
  setWsConnected: (v: boolean) => void;
  setPositions: (p: Position[]) => void;
  addRiskAlert: (a: RiskAlert) => void;
  setWarRoomData: (d: Record<string, unknown>) => void;
  setActiveAccountId: (id: string | null) => void;
}

export const useTradingStore = create<TradingState>((set) => ({
  accounts: [],
  wsConnected: false,
  positions: [],
  riskAlerts: [],
  warRoomData: null,
  activeAccountId: null,
  setAccounts: (accounts) => set({ accounts }),
  setWsConnected: (wsConnected) => set({ wsConnected }),
  setPositions: (positions) => set({ positions }),
  addRiskAlert: (alert) => set((s) => ({ riskAlerts: [alert, ...s.riskAlerts].slice(0, 100) })),
  setWarRoomData: (warRoomData) => {
    set((state) => {
      let nextActiveId = state.activeAccountId;
      // Auto-select logic if activeAccountId is null
      if (!nextActiveId && warRoomData && warRoomData.accounts) {
        const accts = Object.entries(warRoomData.accounts as Record<string, any>);
        if (accts.length > 0) {
          // Find account with highest margin utilization
          let highestMargin = -1;
          let highestMarginId: string | null = null;
          let firstConnectedId: string | null = null;

          for (const [id, info] of accts) {
            if (info.connected && !firstConnectedId) {
              firstConnectedId = id;
            }
            if (info.margin_used !== undefined && info.margin_available !== undefined) {
              const total = info.margin_used + info.margin_available;
              if (total > 0) {
                const util = info.margin_used / total;
                if (util > highestMargin) {
                  highestMargin = util;
                  highestMarginId = id;
                }
              }
            }
          }
          nextActiveId = highestMarginId ?? firstConnectedId ?? accts[0][0];
        }
      }
      return { warRoomData, activeAccountId: nextActiveId };
    });
  },
  setActiveAccountId: (activeAccountId) => set({ activeAccountId }),
}));

// Selectors
export const selectActiveSessions = (state: TradingState) => {
  if (!state.activeAccountId || !state.warRoomData?.all_sessions) return [];
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  return (state.warRoomData.all_sessions as any[]).filter(
    (s) => s.account_id === state.activeAccountId
  );
};

export const selectActivePositions = (state: TradingState) => {
  if (!state.activeAccountId || !state.warRoomData?.all_sessions) return [];
  // Derive positions from active sessions' snapshots filtered to the selected account
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  return (state.warRoomData.all_sessions as any[])
    .filter((s) => s.account_id === state.activeAccountId && s.snapshot)
    .map((s) => ({
      session_id: s.session_id as string,
      symbol: s.symbol as string,
      strategy_slug: s.strategy_slug as string,
      unrealized_pnl: s.snapshot.unrealized_pnl as number,
      drawdown_pct: s.snapshot.drawdown_pct as number,
      trade_count: s.snapshot.trade_count as number,
      equity: s.snapshot.equity as number,
    }));
};
