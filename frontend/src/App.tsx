import React, { useEffect, useRef } from "react";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useUiStore } from "@/stores/uiStore";
import { DataHub } from "@/pages/DataHub";
import { Options } from "@/pages/Options";
import { Strategy } from "@/pages/Strategy";
import { Trading } from "@/pages/Trading";


const primaryTabs = [
  { value: "trading", label: "Trading" },
  { value: "strategy", label: "Strategy" },
  { value: "datahub", label: "Data Hub" },
  { value: "options", label: "Options" },
] as const;

const tabComponents: Record<string, React.FC> = {
  datahub: DataHub,
  options: Options,
  strategy: Strategy,
  trading: Trading,
};

function TabContent() {
  const tab = useUiStore((s) => s.primaryTab);
  const visited = useRef(new Set<string>([tab]));
  visited.current.add(tab);
  return (
    <>
      {primaryTabs.map((t) => {
        if (!visited.current.has(t.value)) return null;
        const Comp = tabComponents[t.value];
        return (
          <div key={t.value} style={{ display: tab === t.value ? "block" : "none" }}>
            <Comp />
          </div>
        );
      })}
    </>
  );
}

export default function App() {
  const primaryTab = useUiStore((s) => s.primaryTab);
  const setPrimaryTab = useUiStore((s) => s.setPrimaryTab);
  const setStrategySubTab = useUiStore((s) => s.setStrategySubTab);

  // Redirect: if URL has /backtest, navigate to Strategy > Tear Sheet
  useEffect(() => {
    if (window.location.pathname === "/backtest" || window.location.hash.includes("backtest")) {
      setPrimaryTab("strategy");
      setStrategySubTab("tearsheet");
    }
  }, []);

  return (
    <div className="min-h-screen" style={{ background: "var(--color-qe-bg)" }}>
      <div
        className="px-5 py-3"
        style={{
          borderBottom: "1px solid var(--color-qe-card-border)",
          background: `linear-gradient(180deg, var(--color-qe-sidebar), var(--color-qe-bg))`,
        }}
      >
        <h1
          className="m-0 text-[19px] font-semibold"
          style={{ fontFamily: "var(--font-serif)", color: "var(--color-qe-text)" }}
        >
          Quant Engine Dashboard{" "}
          <span
            className="text-[11px] font-normal"
            style={{ fontFamily: "var(--font-mono)", color: "var(--color-qe-muted)" }}
          >
            v3 — FastAPI + React
          </span>
        </h1>
      </div>
      <Tabs value={primaryTab} onValueChange={(v) => setPrimaryTab(v as typeof primaryTab)}>
        <TabsList
          className="h-auto w-full justify-start rounded-none border-b p-0"
          style={{
            background: "var(--color-qe-bg)",
            borderColor: "var(--color-qe-card-border)",
          }}
        >
          {primaryTabs.map((t) => (
            <TabsTrigger
              key={t.value}
              value={t.value}
              className="rounded-none border-b-2 border-transparent px-4 py-2.5 text-[12px] font-normal data-[state=active]:border-qe-blue data-[state=active]:font-semibold data-[state=active]:shadow-none"
              style={{
                fontFamily: "var(--font-mono)",
                color: primaryTab === t.value ? "var(--color-qe-text)" : "var(--color-qe-muted)",
                background: "transparent",
                borderBottomColor: primaryTab === t.value ? "var(--color-qe-blue)" : "transparent",
              }}
            >
              {t.label}
            </TabsTrigger>
          ))}
        </TabsList>
      </Tabs>
      <div style={{ minHeight: "calc(100vh - 90px)" }}>
        <TabContent />
      </div>
    </div>
  );
}
