import { useEffect, useState } from "react";
import { Sidebar, SectionLabel, ParamInput } from "@/components/Sidebar";
import { StatCard, StatRow } from "@/components/StatCard";
import { ChartCard } from "@/components/ChartCard";
import { DistributionChart } from "@/components/charts/DistributionChart";
import { fetchStrategies, runBacktest } from "@/lib/api";
import type { StrategyInfo } from "@/lib/api";
import { colors, pnlColor } from "@/lib/theme";

const inputStyle: React.CSSProperties = {
  background: "var(--color-qe-input)", border: "1px solid var(--color-qe-input-border)",
  color: "var(--color-qe-text)", fontFamily: "var(--font-mono)", fontSize: 11, outline: "none",
};

function simulatePaths(dailyReturns: number[], nPaths: number, nDays: number, initial: number): number[][] {
  const rng = () => dailyReturns[Math.floor(Math.random() * dailyReturns.length)];
  const paths: number[][] = [];
  for (let p = 0; p < nPaths; p++) {
    const path = [initial];
    for (let d = 1; d <= nDays; d++) {
      path.push(path[d - 1] * (1 + rng()));
    }
    paths.push(path);
  }
  return paths;
}

function percentile(sorted: number[], p: number): number {
  const idx = Math.ceil(p / 100 * sorted.length) - 1;
  return sorted[Math.max(0, idx)];
}

export function MonteCarlo() {
  const [strategies, setStrategies] = useState<StrategyInfo[]>([]);
  const [strategy, setStrategy] = useState("");
  const [symbol, setSymbol] = useState("TX");
  const [start, setStart] = useState("2025-08-01");
  const [end, setEnd] = useState("2026-03-14");
  const [nPaths, setNPaths] = useState(1000);
  const [simDays, setSimDays] = useState(252);
  const [running, setRunning] = useState(false);
  const [paths, setPaths] = useState<number[][]>([]);
  const [finalPnls, setFinalPnls] = useState<number[]>([]);
  const [percentiles, setPercentiles] = useState<{ p: number; val: number }[]>([]);

  useEffect(() => {
    fetchStrategies().then((s) => {
      setStrategies(s);
      if (s.length > 0 && !strategy) setStrategy(s[0].slug);
    });
  }, []);

  const handleRun = async () => {
    setRunning(true);
    try {
      const r = await runBacktest({ strategy, symbol, start, end });
      const returns = r.daily_returns;
      if (returns.length < 5) { setRunning(false); return; }
      const initial = r.equity_curve[0] ?? 2_000_000;
      const simulated = simulatePaths(returns, nPaths, simDays, initial);
      const finals = simulated.map((p) => p[p.length - 1] - initial);
      const sorted = [...finals].sort((a, b) => a - b);
      setPaths(simulated.slice(0, Math.min(200, simulated.length)));
      setFinalPnls(finals);
      setPercentiles([
        { p: 5, val: percentile(sorted, 5) },
        { p: 25, val: percentile(sorted, 25) },
        { p: 50, val: percentile(sorted, 50) },
        { p: 75, val: percentile(sorted, 75) },
        { p: 95, val: percentile(sorted, 95) },
      ]);
    } catch {
      // ignore
    }
    setRunning(false);
  };

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
        <SectionLabel>DATA (backtest period)</SectionLabel>
        <ParamInput label="Contract">
          <select value={symbol} onChange={(e) => setSymbol(e.target.value)} className="w-full rounded px-1.5 py-1 text-[11px]" style={inputStyle}>
            <option value="TX">TX (TAIEX)</option><option value="MTX">MTX</option>
          </select>
        </ParamInput>
        <ParamInput label="From"><input type="text" value={start} onChange={(e) => setStart(e.target.value)} className="w-full rounded px-1.5 py-1 text-[11px]" style={inputStyle} /></ParamInput>
        <ParamInput label="To"><input type="text" value={end} onChange={(e) => setEnd(e.target.value)} className="w-full rounded px-1.5 py-1 text-[11px]" style={inputStyle} /></ParamInput>
        <hr style={{ borderColor: colors.cardBorder, margin: "10px 0" }} />
        <SectionLabel>SIMULATION</SectionLabel>
        <ParamInput label="Number of Paths"><input type="number" value={nPaths} min={100} max={5000} step={100} onChange={(e) => setNPaths(Number(e.target.value))} className="w-full rounded px-1.5 py-1 text-[11px]" style={inputStyle} /></ParamInput>
        <ParamInput label="Simulation Days"><input type="number" value={simDays} min={30} max={504} step={10} onChange={(e) => setSimDays(Number(e.target.value))} className="w-full rounded px-1.5 py-1 text-[11px]" style={inputStyle} /></ParamInput>
        <button onClick={handleRun} disabled={running} className="w-full py-1.5 mt-2 rounded text-[10px] font-semibold cursor-pointer border-none text-white" style={{ background: "#5A2A8A", fontFamily: "var(--font-mono)" }}>
          {running ? "Simulating…" : "Run Simulation"}
        </button>
      </Sidebar>
      <div className="flex-1 p-3 overflow-y-auto" style={{ minWidth: 0 }}>
        {!paths.length && !running && (
          <div className="text-[11px] py-5" style={{ color: colors.muted, fontFamily: "var(--font-mono)" }}>
            Select a strategy & data range, then click Run Simulation.
            <br />Runs a backtest to extract return statistics, then simulates equity paths.
          </div>
        )}
        {running && (
          <div className="text-[11px] py-5" style={{ color: colors.purple, fontFamily: "var(--font-mono)" }}>
            Simulating {nPaths} paths over {simDays} days…
          </div>
        )}
        {paths.length > 0 && (
          <>
            <StatRow>
              {percentiles.map((p) => (
                <StatCard
                  key={p.p}
                  label={`P${p.p}`}
                  value={`$${p.val >= 0 ? "+" : ""}${Math.round(p.val).toLocaleString()}`}
                  color={pnlColor(p.val)}
                />
              ))}
            </StatRow>
            {/* Paths visualization via SVG */}
            <ChartCard title={`SIMULATED EQUITY PATHS (${Math.min(200, paths.length)} shown)`}>
              <svg viewBox={`0 0 ${simDays + 1} 100`} className="w-full" style={{ height: 260, background: colors.card }}>
                {paths.map((path, i) => {
                  const min = Math.min(...path);
                  const max = Math.max(...path);
                  const range = max - min || 1;
                  return (
                    <polyline
                      key={i}
                      points={path.map((v, d) => `${d},${100 - ((v - min) / range) * 90 - 5}`).join(" ")}
                      fill="none"
                      stroke={path[path.length - 1] >= path[0] ? colors.green : colors.red}
                      strokeWidth="0.15"
                      opacity={0.3}
                    />
                  );
                })}
              </svg>
            </ChartCard>
            <ChartCard title="FINAL PnL DISTRIBUTION">
              <DistributionChart values={finalPnls.map((v) => v / 1000)} bins={40} />
            </ChartCard>
            {/* Percentile table */}
            <ChartCard title="PERCENTILE TABLE">
              <table className="w-full text-[10px]" style={{ fontFamily: "var(--font-mono)" }}>
                <thead>
                  <tr style={{ borderBottom: `1px solid ${colors.cardBorder}` }}>
                    <th className="text-left py-1 px-3" style={{ color: colors.dim }}>Percentile</th>
                    <th className="text-right py-1 px-3" style={{ color: colors.dim }}>PnL ($)</th>
                    <th className="text-right py-1 px-3" style={{ color: colors.dim }}>Return %</th>
                  </tr>
                </thead>
                <tbody>
                  {percentiles.map((p) => (
                    <tr key={p.p} style={{ borderBottom: `1px solid ${colors.cardBorder}` }}>
                      <td className="py-1 px-3" style={{ color: colors.muted }}>P{p.p}</td>
                      <td className="text-right py-1 px-3" style={{ color: pnlColor(p.val) }}>
                        ${p.val >= 0 ? "+" : ""}{Math.round(p.val).toLocaleString()}
                      </td>
                      <td className="text-right py-1 px-3" style={{ color: pnlColor(p.val) }}>
                        {((p.val / 2_000_000) * 100).toFixed(1)}%
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </ChartCard>
          </>
        )}
      </div>
    </div>
  );
}
