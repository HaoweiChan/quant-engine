import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useUiStore } from "@/stores/uiStore";
import { useLiveFeed } from "@/hooks/useLiveFeed";
import { colors } from "@/lib/theme";
import { AccountsTab } from "@/components/warroom/AccountsTab";
import { BlotterTab } from "@/components/warroom/BlotterTab";
import { RiskTab } from "@/components/warroom/RiskTab";
import { WarRoomLayout } from "@/components/warroom/WarRoomLayout";

const tradingSubTabs = [
  { value: "accounts", label: "Accounts" },
  { value: "warroom", label: "War Room" },
  { value: "blotter", label: "Blotter" },
  { value: "risk", label: "Risk" },
] as const;

export function Trading() {
  const subTab = useUiStore((s) => s.tradingSubTab);
  const setSubTab = useUiStore((s) => s.setTradingSubTab);
  useLiveFeed();

  return (
    <div className="flex flex-col" style={{ height: "100%" }}>
      <Tabs value={subTab} onValueChange={(v) => setSubTab(v as typeof subTab)}>
        <TabsList
          className="h-auto w-full justify-start rounded-none border-b p-0"
          style={{ background: colors.bg, borderColor: colors.cardBorder }}
        >
          {tradingSubTabs.map((t) => (
            <TabsTrigger
              key={t.value}
              value={t.value}
              className="rounded-none border-b px-3 py-1.5 text-[11px] font-normal data-[state=active]:shadow-none"
              style={{
                fontFamily: "var(--font-mono)",
                color: subTab === t.value ? colors.muted : colors.dim,
                background: "transparent",
                borderBottomColor: subTab === t.value ? colors.blue : "transparent",
              }}
            >
              {t.label}
            </TabsTrigger>
          ))}
        </TabsList>
      </Tabs>
      <div className="flex-1 min-h-0">
        {subTab === "accounts" && <AccountsTab />}
        {subTab === "warroom" && <WarRoomLayout />}
        {subTab === "blotter" && <BlotterTab />}
        {subTab === "risk" && <RiskTab />}
      </div>
    </div>
  );
}
