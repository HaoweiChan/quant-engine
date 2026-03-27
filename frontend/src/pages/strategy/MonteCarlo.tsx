import React, { useEffect, useMemo, useState } from "react";
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

// Aggregate a per-bar equity curve into daily end-of-day values
function equityToDailyReturns(equity: number[], startDate: string, endDate: string): number[] {
  if (equity.length < 2) return [];
  const msPerDay = 86_400_000;
  const s = new Date(startDate).getTime();
  const e = new Date(endDate).getTime();
  const calDays = Math.max(1, Math.round((e - s) / msPerDay));
  const tradingDays = Math.max(1, Math.round(calDays * 252 / 365));
  const barsPerDay = Math.max(1, Math.floor(equity.length / tradingDays));
  // sample end-of-day equity values
  const dailyEq: number[] = [];
  for (let i = barsPerDay - 1; i < equity.length; i += barsPerDay) {
    dailyEq.push(equity[i]);
  }
  if (dailyEq.length === 0) dailyEq.push(equity[equity.length - 1]);
  const rets: number[] = [];
  for (let i = 1; i < dailyEq.length; i++) {
    if (dailyEq[i - 1] !== 0) rets.push(dailyEq[i] / dailyEq[i - 1] - 1);
  }
  return rets;
}

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

const SVG_W = 600;
const SVG_H = 260;
const PAD = { top: 10, bottom: 20, left: 60, right: 10 };

const EquityPathsSVG = React.memo(function EquityPathsSVG({ paths, simDays }: { paths: number[][]; simDays: number }) {
  const { yMin, yMax, ticks } = useMemo(() => {
    let lo = Infinity;
    let hi = -Infinity;
    for (const p of paths) {
      for (const v of p) {
        if (v < lo) lo = v;
        if (v > hi) hi = v;
      }
    }
    const margin = (hi - lo) * 0.05 || 1;
    const yMin = lo - margin;
    const yMax = hi + margin;
    const range = yMax - yMin;
    const step = Math.pow(10, Math.floor(Math.log10(range / 4)));
    const niceStep = range / step < 6 ? step : step * 2;
    const ticks: number[] = [];
    let t = Math.ceil(yMin / niceStep) * niceStep;
    while (t <= yMax) { ticks.push(t); t += niceStep; }
    return { yMin, yMax, ticks };
  }, [paths]);

  const xScale = (d: number) => PAD.left + (d / simDays) * (SVG_W - PAD.left - PAD.right);
  const yScale = (v: number) => PAD.top + (1 - (v - yMin) / (yMax - yMin)) * (SVG_H - PAD.top - PAD.bottom);

  const fmtY = (v: number) => {
    if (Math.abs(v) >= 1_000_000) return `${(v / 1_000_000).toFixed(1)}M`;
    if (Math.abs(v) >= 1_000) return `${(v / 1_000).toFixed(0)}k`;
    return v.toFixed(0);
  };

  return (
    <svg viewBox={`0 0 ${SVG_W} ${SVG_H}`} className="w-full" style={{ height: 280, background: colors.card }}>
      {ticks.map((t) => (
        <g key={t}>
          <line x1={PAD.left} x2={SVG_W - PAD.right} y1={yScale(t)} y2={yScale(t)} stroke={colors.grid} strokeWidth={0.5} />
          <text x={PAD.left - 4} y={yScale(t) + 3} textAnchor="end" fill={colors.dim} fontSize={8} fontFamily="var(--font-mono)">{fmtY(t)}</text>
        </g>
      ))}
      {[0, Math.round(simDays * 0.25), Math.round(simDays * 0.5), Math.round(simDays * 0.75), simDays].map((d) => (
        <text key={d} x={xScale(d)} y={SVG_H - 4} textAnchor="middle" fill={colors.dim} fontSize={8} fontFamily="var(--font-mono)">
          {d}d
        </text>
      ))}
      {paths.map((path, i) => {
        const pts = path.map((v, d) => `${xScale(d).toFixed(1)},${yScale(v).toFixed(1)}`).join(" ");
        const gain = path[path.length - 1] >= path[0];
        return (
          <polyline key={i} points={pts} fill="none" stroke={gain ? colors.green : colors.red} strokeWidth={0.6} opacity={0.25} />
        );
      })}
      <line x1={PAD.left} x2={PAD.left} y1={PAD.top} y2={SVG_H - PAD.bottom} stroke={colors.cardBorder} strokeWidth={0.5} />
      <line x1={PAD.left} x2={SVG_W - PAD.right} y1={SVG_H - PAD.bottom} y2={SVG_H - PAD.bottom} stroke={colors.cardBorder} strokeWidth={0.5} />
    </svg>
  );
});

export function MonteCarlo() {
  const [strategies, setStrategies] = useState<StrategyInfo[]>([]);
  const [strategy, setStrategy] = useState("");
  const [symbol, setSymbol] = useState("TX");
  const [start, setStart] = useState("2025-08-01");
  const [end, setEnd] = useState("2026-03-14");
  const [barAgg, setBarAgg] = useState(1);
  const [initialCapital, setInitialCapital] = useState(2_000_000);
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
      const r = await runBacktest({
        strategy, symbol, start, end,
        params: { bar_agg: barAgg },
        initial_capital: initialCapital,
      });
      const returns = equityToDailyReturns(r.equity_curve, start, end);
      if (returns.length < 5) { setRunning(false); return; }
      const initial = r.equity_curve[0] ?? initialCapital;
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
        <ParamInput label="Timeframe">
          <select value={barAgg} onChange={(e) => setBarAgg(Number(e.target.value))} className="w-full rounded px-1.5 py-1 text-[11px]" style={inputStyle}>
            <option value={1}>1 min</option>
            <option value={3}>3 min</option>
            <option value={5}>5 min</option>
            <option value={15}>15 min</option>
            <option value={30}>30 min</option>
            <option value={60}>60 min</option>
          </select>
        </ParamInput>
        <ParamInput label="Init Capital ($)">
          <input type="number" value={initialCapital} step={100000} onChange={(e) => setInitialCapital(Number(e.target.value))} className="w-full rounded px-1.5 py-1 text-[11px]" style={inputStyle} />
        </ParamInput>
        <hr style={{ borderColor: colors.cardBorder, margin: "10px 0" }} />
        <SectionLabel>SIMULATION</SectionLabel>
        <ParamInput label="Paths"><input type="number" value={nPaths} min={100} max={5000} step={100} onChange={(e) => setNPaths(Number(e.target.value))} className="w-full rounded px-1.5 py-1 text-[11px]" style={inputStyle} /></ParamInput>
        <ParamInput label="Sim Days"><input type="number" value={simDays} min={30} max={504} step={10} onChange={(e) => setSimDays(Number(e.target.value))} className="w-full rounded px-1.5 py-1 text-[11px]" style={inputStyle} /></ParamInput>
        <button onClick={handleRun} disabled={running} className="w-full py-1.5 mt-2 rounded text-[10px] font-semibold cursor-pointer border-none text-white" style={{ background: "#5A2A8A", fontFamily: "var(--font-mono)" }}>
          {running ? "Simulating…" : "Run Simulation"}
        </button>
        <div className="text-[8px] mt-2" style={{ color: colors.dim, fontFamily: "var(--font-mono)", lineHeight: 1.4 }}>
          Runs a backtest on the date range to extract return distribution, then bootstraps {nPaths} equity paths over {simDays} trading days.
        </div>
      </Sidebar>
      <div className="flex-1 p-3 overflow-y-auto" style={{ minWidth: 0 }}>
        {!paths.length && !running && (
          <div className="text-[11px] py-5" style={{ color: colors.muted, fontFamily: "var(--font-mono)" }}>
            Select a strategy & data range, then click Run Simulation.
            <br /><span style={{ color: colors.dim }}>Runs a backtest to extract return statistics, then bootstraps simulated equity paths.</span>
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
            <ChartCard title={`SIMULATED EQUITY PATHS (${Math.min(200, paths.length)} of ${nPaths} shown)`}>
              <EquityPathsSVG paths={paths} simDays={simDays} />
            </ChartCard>
            <ChartCard title="FINAL PnL DISTRIBUTION (×$1k)">
              <DistributionChart values={finalPnls.map((v) => v / 1000)} bins={40} />
            </ChartCard>
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
                        {((p.val / initialCapital) * 100).toFixed(1)}%
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
