import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useUiStore } from "@/stores/uiStore";
import { CodeEditor } from "@/pages/strategy/CodeEditor";
import { GridSearch } from "@/pages/strategy/GridSearch";
import { MonteCarlo } from "@/pages/strategy/MonteCarlo";
import { Optimizer } from "@/pages/strategy/Optimizer";
import { colors } from "@/lib/theme";

const subTabs = [
  { value: "editor", label: "Code Editor" },
  { value: "optimizer", label: "Optimizer" },
  { value: "gridsearch", label: "Grid Search" },
  { value: "montecarlo", label: "Monte Carlo" },
] as const;

export function Strategy() {
  const subTab = useUiStore((s) => s.strategySubTab);
  const setSubTab = useUiStore((s) => s.setStrategySubTab);

  return (
    <div>
      <Tabs value={subTab} onValueChange={(v) => setSubTab(v as typeof subTab)}>
        <TabsList
          className="h-auto w-full justify-start rounded-none border-b p-0"
          style={{ background: colors.bg, borderColor: colors.cardBorder }}
        >
          {subTabs.map((t) => (
            <TabsTrigger
              key={t.value}
              value={t.value}
              className="rounded-none border-b px-3 py-1.5 text-[9px] font-normal data-[state=active]:shadow-none"
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
        {subTab === "editor" && <CodeEditor />}
        {subTab === "optimizer" && <Optimizer />}
        {subTab === "gridsearch" && <GridSearch />}
        {subTab === "montecarlo" && <MonteCarlo />}
      </div>
    </div>
  );
}
