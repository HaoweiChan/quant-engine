import { useEffect, useState } from "react";
import { Sidebar, SectionLabel, ParamInput } from "@/components/Sidebar";
import { StatCard, StatRow } from "@/components/StatCard";
import { ChartCard } from "@/components/ChartCard";
import { fetchStrategies, startOptimizer, fetchOptimizerStatus } from "@/lib/api";
import type { StrategyInfo, OptimizerStatus } from "@/lib/api";
import { colors } from "@/lib/theme";

const inputStyle: React.CSSProperties = {
  background: "var(--color-qe-input)", border: "1px solid var(--color-qe-input-border)",
  color: "var(--color-qe-text)", fontFamily: "var(--font-mono)", fontSize: 10, outline: "none",
};

export function Optimizer() {
  const [strategies, setStrategies] = useState<StrategyInfo[]>([]);
  const [strategy, setStrategy] = useState("");
  const [symbol, setSymbol] = useState("TX");
  const [start, setStart] = useState("2025-08-01");
  const [end, setEnd] = useState("2026-03-14");
  const [isFraction, setIsFraction] = useState(0.8);
  const [objective, setObjective] = useState("sharpe");
  const [nJobs, setNJobs] = useState(2);
  const [paramGridStr, setParamGridStr] = useState<Record<string, string>>({});
  const [status, setStatus] = useState<OptimizerStatus | null>(null);
  const [running, setRunning] = useState(false);

  useEffect(() => {
    fetchStrategies().then((s) => {
      setStrategies(s);
      if (s.length > 0 && !strategy) setStrategy(s[0].slug);
    });
  }, []);

  const currentStrat = strategies.find((s) => s.slug === strategy);

  useEffect(() => {
    if (!currentStrat?.param_grid) return;
    const defaults: Record<string, string> = {};
    for (const [k, v] of Object.entries(currentStrat.param_grid)) {
      defaults[k] = (v.default ?? []).join(",");
    }
    setParamGridStr(defaults);
  }, [strategy, strategies]);

  const handleRun = async () => {
    const parsed: Record<string, number[]> = {};
    for (const [k, v] of Object.entries(paramGridStr)) {
      parsed[k] = v.split(",").map(Number).filter((n) => !isNaN(n));
    }
    try {
      await startOptimizer({ strategy, symbol, start, end, param_grid: parsed, is_fraction: isFraction, objective, n_jobs: nJobs });
      setRunning(true);
      const poll = setInterval(async () => {
        const s = await fetchOptimizerStatus();
        setStatus(s);
        if (s.finished || s.error) { clearInterval(poll); setRunning(false); }
      }, 2000);
    } catch {
      // ignore
    }
  };

  const result = status?.result_data as Record<string, unknown> | null;
  const topTrials = (result?.top_trials ?? []) as { rank: number; params: Record<string, number>; sharpe: number; score: number }[];

  return (
    <div className="flex">
      <Sidebar>
        <SectionLabel>STRATEGY</SectionLabel>
        <ParamInput label="Strategy">
          <select value={strategy} onChange={(e) => setStrategy(e.target.value)} className="w-full rounded px-1.5 py-1 text-[11px]" style={inputStyle}>
            {strategies.length === 0 && <option value="">Loading…</option>}
            {strategies.map((s) => <option key={s.slug} value={s.slug}>{s.name}</option>)}
          </select>
        </ParamInput>
        <hr style={{ borderColor: colors.cardBorder, margin: "10px 0" }} />
        <SectionLabel>DATA</SectionLabel>
        <ParamInput label="Contract">
          <select value={symbol} onChange={(e) => setSymbol(e.target.value)} className="w-full rounded px-1.5 py-1 text-[11px]" style={inputStyle}>
            <option value="TX">TX (TAIEX)</option><option value="MTX">MTX</option>
          </select>
        </ParamInput>
        <ParamInput label="From"><input type="text" value={start} onChange={(e) => setStart(e.target.value)} className="w-full rounded px-1.5 py-1 text-[11px]" style={inputStyle} /></ParamInput>
        <ParamInput label="To"><input type="text" value={end} onChange={(e) => setEnd(e.target.value)} className="w-full rounded px-1.5 py-1 text-[11px]" style={inputStyle} /></ParamInput>
        <ParamInput label="IS Fraction"><input type="number" value={isFraction} min={0.5} max={0.95} step={0.05} onChange={(e) => setIsFraction(Number(e.target.value))} className="w-full rounded px-1.5 py-1 text-[11px]" style={inputStyle} /></ParamInput>
        <ParamInput label="Objective">
          <select value={objective} onChange={(e) => setObjective(e.target.value)} className="w-full rounded px-1.5 py-1 text-[11px]" style={inputStyle}>
            <option value="sharpe">Sharpe Ratio</option><option value="sortino">Sortino</option><option value="calmar">Calmar</option><option value="total_return">Total Return</option>
          </select>
        </ParamInput>
        <hr style={{ borderColor: colors.cardBorder, margin: "10px 0" }} />
        <SectionLabel>PARAM GRID (comma-separated)</SectionLabel>
        {currentStrat?.param_grid && Object.entries(currentStrat.param_grid).map(([key, cfg]) => (
          <ParamInput key={key} label={cfg.label || key}>
            <input type="text" value={paramGridStr[key] ?? ""} onChange={(e) => setParamGridStr({ ...paramGridStr, [key]: e.target.value })} className="w-full rounded px-1.5 py-1 text-[10px]" placeholder="e.g. 15,20,25" style={inputStyle} />
          </ParamInput>
        ))}
        <hr style={{ borderColor: colors.cardBorder, margin: "10px 0" }} />
        <ParamInput label="Parallel Jobs"><input type="number" value={nJobs} min={1} max={8} step={1} onChange={(e) => setNJobs(Number(e.target.value))} className="w-full rounded px-1.5 py-1 text-[11px]" style={inputStyle} /></ParamInput>
        <button onClick={handleRun} disabled={running} className="w-full py-1.5 mt-2 rounded text-[10px] font-semibold cursor-pointer border-none text-white" style={{ background: "#2A6A4A", fontFamily: "var(--font-mono)" }}>
          {running ? "Running…" : "Run Optimizer"}
        </button>
      </Sidebar>
      <div className="flex-1 p-3 overflow-y-auto" style={{ minWidth: 0 }}>
        {/* Status bar */}
        <div className="text-[9px] mb-2.5 min-h-[16px]" style={{ fontFamily: "var(--font-mono)", color: colors.muted }}>
          {running ? `Optimizing… ${status?.progress ?? ""}` : status?.error ?? ""}
        </div>
        {!status && !running && (
          <div className="text-[11px] py-5" style={{ color: colors.muted, fontFamily: "var(--font-mono)" }}>
            Configure param grid and click Run Optimizer.
          </div>
        )}
        {status?.finished && result && (
          <>
            <StatRow>
              <StatCard label="BEST SHARPE" value={String((result.best_sharpe as number)?.toFixed(2) ?? "—")} color={colors.green} />
              <StatCard label="TRIALS" value={String(result.n_trials ?? "—")} color={colors.cyan} />
              <StatCard label="OBJECTIVE" value={objective.toUpperCase()} color={colors.muted} />
            </StatRow>
            {topTrials.length > 0 && (
              <ChartCard title="TOP RESULTS">
                <div className="max-h-[300px] overflow-y-auto">
                  <table className="w-full text-[9px]" style={{ fontFamily: "var(--font-mono)" }}>
                    <thead>
                      <tr style={{ borderBottom: `1px solid ${colors.cardBorder}` }}>
                        <th className="text-left py-1 px-2" style={{ color: colors.dim }}>#</th>
                        <th className="text-left py-1 px-2" style={{ color: colors.dim }}>Score</th>
                        <th className="text-left py-1 px-2" style={{ color: colors.dim }}>Sharpe</th>
                        <th className="text-left py-1 px-2" style={{ color: colors.dim }}>Params</th>
                      </tr>
                    </thead>
                    <tbody>
                      {topTrials.map((t, i) => (
                        <tr key={i} style={{ borderBottom: `1px solid ${colors.cardBorder}` }}>
                          <td className="py-1 px-2" style={{ color: colors.muted }}>{t.rank}</td>
                          <td className="py-1 px-2" style={{ color: colors.green }}>{t.score?.toFixed(3)}</td>
                          <td className="py-1 px-2" style={{ color: colors.cyan }}>{t.sharpe?.toFixed(2)}</td>
                          <td className="py-1 px-2" style={{ color: colors.text }}>{JSON.stringify(t.params)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </ChartCard>
            )}
          </>
        )}
      </div>
    </div>
  );
}
