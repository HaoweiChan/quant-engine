import { create } from "zustand";

type BottomTab = "blotter" | "trades" | "activity";

interface WarRoomUiState {
  bottomTab: BottomTab;
  setBottomTab: (tab: BottomTab) => void;
  bindingsExpanded: boolean;
  toggleBindings: () => void;
  selectedSessionId: string | null;
  setSelectedSessionId: (id: string | null) => void;
  paramDrawerOpen: boolean;
  paramDrawerStrategy: string | null;
  openParamDrawer: (strategy: string) => void;
  closeParamDrawer: () => void;
}

export const useWarRoomStore = create<WarRoomUiState>((set) => ({
  bottomTab: "blotter",
  setBottomTab: (bottomTab) => set({ bottomTab }),
  bindingsExpanded: true,
  toggleBindings: () => set((s) => ({ bindingsExpanded: !s.bindingsExpanded })),
  selectedSessionId: null,
  setSelectedSessionId: (selectedSessionId) => set({ selectedSessionId }),
  paramDrawerOpen: false,
  paramDrawerStrategy: null,
  openParamDrawer: (strategy) => set({ paramDrawerOpen: true, paramDrawerStrategy: strategy }),
  closeParamDrawer: () => set({ paramDrawerOpen: false, paramDrawerStrategy: null }),
}));
