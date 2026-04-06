import React, { useRef } from "react";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { StrategyParamSidebar } from "@/components/StrategyParamSidebar";
import { useUiStore } from "@/stores/uiStore";
import { CodeEditor } from "@/pages/strategy/CodeEditor";
import { TearSheet } from "@/pages/strategy/TearSheet";
import { ParamSweep } from "@/pages/strategy/ParamSweep";
import { Portfolio } from "@/pages/strategy/Portfolio";
import { RiskEvaluation } from "@/pages/strategy/RiskEvaluation";
import { colors } from "@/lib/theme";


const subTabs = [
  { value: "editor", label: "Code Editor" },
  { value: "tearsheet", label: "Tear Sheet" },
  { value: "paramsweep", label: "Param Sweep" },
  { value: "risk", label: "Risk Evaluation" },
  { value: "portfolio", label: "Portfolio" },
] as const;

const subTabComponents: Record<string, React.FC> = {
  editor: CodeEditor,
  tearsheet: TearSheet,
  paramsweep: ParamSweep,
  risk: RiskEvaluation,
  portfolio: Portfolio,
};

export function Strategy() {
  const subTab = useUiStore((s) => s.strategySubTab);
  const setSubTab = useUiStore((s) => s.setStrategySubTab);
  const visited = useRef(new Set<string>([subTab]));
  visited.current.add(subTab);

  return (
    <div className="flex">
      <StrategyParamSidebar />
      <div className="flex-1" style={{ minWidth: 0 }}>
        <Tabs value={subTab} onValueChange={(v) => setSubTab(v as typeof subTab)}>
          <TabsList
            className="h-auto w-full justify-start rounded-none border-b p-0"
            style={{ background: colors.bg, borderColor: colors.cardBorder }}
          >
            {subTabs.map((t) => (
              <TabsTrigger
                key={t.value}
                value={t.value}
                className="rounded-none border-b px-4 py-2 text-xs font-normal data-[state=active]:shadow-none"
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
        <div>
          {subTabs.map((t) => {
            if (!visited.current.has(t.value)) return null;
            const Comp = subTabComponents[t.value];
            return (
              <div key={t.value} style={{ display: subTab === t.value ? "block" : "none" }}>
                <Comp />
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
