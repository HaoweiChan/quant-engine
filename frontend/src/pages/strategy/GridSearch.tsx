import { useEffect, useState } from "react";
import { Sidebar, SectionLabel, ParamInput } from "@/components/Sidebar";
import { ChartCard } from "@/components/ChartCard";
import { fetchStrategies, runBacktest } from "@/lib/api";
import type { StrategyInfo } from "@/lib/api";
import { colors } from "@/lib/theme";

const inputStyle: React.CSSProperties = {
  background: "var(--color-qe-input)", border: "1px solid var(--color-qe-input-border)",
  color: "var(--color-qe-text)", fontFamily: "var(--font-mono)", fontSize: 11, outline: "none",
};

type Metric = "mean_ret" | "sharpe" | "win_rate" | "std_dev";
const metricLabels: Record<Metric, string> = {
  mean_ret: "E[Return %]", sharpe: "Sharpe", win_rate: "Win Rate %", std_dev: "Std Dev",
};

interface CellResult {
  xVal: number;
  yVal: number;
  mean_ret: number;
  sharpe: number;
  win_rate: number;
  std_dev: number;
}

export function GridSearch() {
  const [strategies, setStrategies] = useState<StrategyInfo[]>([]);
  const [strategy, setStrategy] = useState("");
  const [xParam, setXParam] = useState("");
  const [yParam, setYParam] = useState("");
  const [xMin, setXMin] = useState(1);
  const [xMax, setXMax] = useState(3);
  const [xSteps, setXSteps] = useState(6);
  const [yMin, setYMin] = useState(2);
  const [yMax, setYMax] = useState(8);
  const [ySteps, setYSteps] = useState(6);
  const [nSims, setNSims] = useState(200);
  const [metric, setMetric] = useState<Metric>("mean_ret");
  const [results, setResults] = useState<CellResult[]>([]);
  const [running, setRunning] = useState(false);
  const [progress, setProgress] = useState("");

  useEffect(() => {
    fetchStrategies().then((s) => {
      setStrategies(s);
      if (s.length > 0) {
        setStrategy(s[0].slug);
        const keys = Object.keys(s[0].param_grid);
        if (keys[0]) setXParam(keys[0]);
        if (keys[1]) setYParam(keys[1]);
        else if (keys[0]) setYParam(keys[0]);
      }
    });
  }, []);

  const currentStrat = strategies.find((s) => s.slug === strategy);
  const paramOpts = currentStrat ? Object.entries(currentStrat.param_grid).map(([k, v]) => ({ value: k, label: v.label || k })) : [];

  const linspace = (min: number, max: number, steps: number) => {
    if (steps <= 1) return [min];
    return Array.from({ length: steps }, (_, i) => min + (max - min) * i / (steps - 1));
  };

  const handleRun = async () => {
    if (!strategy || !xParam || !yParam) return;
    setRunning(true);
    setResults([]);
    const xVals = linspace(xMin, xMax, xSteps);
    const yVals = linspace(yMin, yMax, ySteps);
    const total = xVals.length * yVals.length;
    const cells: CellResult[] = [];
    let done = 0;
    for (const xv of xVals) {
      for (const yv of yVals) {
        try {
          const r = await runBacktest({
            strategy, symbol: "TX", start: "2025-08-01", end: "2026-03-14",
            params: { [xParam]: xv, [yParam]: yv },
          });
          const m = r.metrics;
          cells.push({
            xVal: xv, yVal: yv,
            mean_ret: (m.total_return ?? 0) * 100,
            sharpe: m.sharpe ?? 0,
            win_rate: (m.win_rate ?? 0) * 100,
            std_dev: (m.annual_volatility ?? 0) * 100,
          });
        } catch {
          cells.push({ xVal: xv, yVal: yv, mean_ret: 0, sharpe: 0, win_rate: 0, std_dev: 0 });
        }
        done++;
        setProgress(`${done}/${total}`);
      }
    }
    setResults(cells);
    setRunning(false);
  };

  const xVals = [...new Set(results.map((r) => r.xVal))].sort((a, b) => a - b);
  const yVals = [...new Set(results.map((r) => r.yVal))].sort((a, b) => a - b);
  const cellMap = new Map(results.map((r) => [`${r.xVal},${r.yVal}`, r]));
  const metricVals = results.map((r) => r[metric]);
  const minVal = Math.min(...metricVals);
  const maxVal = Math.max(...metricVals);
  const range = maxVal - minVal || 1;

  const heatColor = (v: number) => {
    const t = (v - minVal) / range;
    if (metric === "std_dev") {
      const r = Math.round(60 + 180 * t);
      return `rgb(${r}, ${Math.round(40 + 60 * (1 - t))}, ${Math.round(40 + 60 * (1 - t))})`;
    }
    const g = Math.round(60 + 180 * t);
    return `rgb(${Math.round(40 + 60 * (1 - t))}, ${g}, ${Math.round(40 + 60 * (1 - t))})`;
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
        <SectionLabel>AXES</SectionLabel>
        <ParamInput label="X-axis Parameter">
          <select value={xParam} onChange={(e) => setXParam(e.target.value)} className="w-full rounded px-1.5 py-1 text-[11px]" style={inputStyle}>
            {paramOpts.map((p) => <option key={p.value} value={p.value}>{p.label}</option>)}
          </select>
        </ParamInput>
        <ParamInput label="Y-axis Parameter">
          <select value={yParam} onChange={(e) => setYParam(e.target.value)} className="w-full rounded px-1.5 py-1 text-[11px]" style={inputStyle}>
            {paramOpts.map((p) => <option key={p.value} value={p.value}>{p.label}</option>)}
          </select>
        </ParamInput>
        <SectionLabel>X RANGE</SectionLabel>
        <div className="flex gap-1">
          <ParamInput label="min"><input type="number" value={xMin} step={0.1} onChange={(e) => setXMin(Number(e.target.value))} className="w-full rounded px-1 py-0.5 text-[10px]" style={inputStyle} /></ParamInput>
          <ParamInput label="max"><input type="number" value={xMax} step={0.1} onChange={(e) => setXMax(Number(e.target.value))} className="w-full rounded px-1 py-0.5 text-[10px]" style={inputStyle} /></ParamInput>
          <ParamInput label="#"><input type="number" value={xSteps} min={2} max={12} onChange={(e) => setXSteps(Number(e.target.value))} className="w-14 rounded px-1 py-0.5 text-[10px]" style={inputStyle} /></ParamInput>
        </div>
        <SectionLabel>Y RANGE</SectionLabel>
        <div className="flex gap-1">
          <ParamInput label="min"><input type="number" value={yMin} step={0.5} onChange={(e) => setYMin(Number(e.target.value))} className="w-full rounded px-1 py-0.5 text-[10px]" style={inputStyle} /></ParamInput>
          <ParamInput label="max"><input type="number" value={yMax} step={0.5} onChange={(e) => setYMax(Number(e.target.value))} className="w-full rounded px-1 py-0.5 text-[10px]" style={inputStyle} /></ParamInput>
          <ParamInput label="#"><input type="number" value={ySteps} min={2} max={12} onChange={(e) => setYSteps(Number(e.target.value))} className="w-14 rounded px-1 py-0.5 text-[10px]" style={inputStyle} /></ParamInput>
        </div>
        <ParamInput label="MC sims/cell"><input type="number" value={nSims} min={50} max={2000} step={50} onChange={(e) => setNSims(Number(e.target.value))} className="w-full rounded px-1.5 py-1 text-[11px]" style={inputStyle} /></ParamInput>
        <button onClick={handleRun} disabled={running} className="w-full py-1.5 mt-2 rounded text-[10px] font-semibold cursor-pointer border-none text-white" style={{ background: "#2A6A4A", fontFamily: "var(--font-mono)" }}>
          {running ? `Running… ${progress}` : "Run Grid Search"}
        </button>
      </Sidebar>
      <div className="flex-1 p-3 overflow-y-auto" style={{ minWidth: 0 }}>
        {/* Metric selector */}
        <div className="flex items-center gap-3 mb-3">
          <span className="text-[9px]" style={{ color: colors.muted, fontFamily: "var(--font-mono)" }}>Metric:</span>
          {(Object.keys(metricLabels) as Metric[]).map((m) => (
            <label key={m} className="flex items-center gap-1 text-[9px] cursor-pointer" style={{ color: metric === m ? colors.text : colors.dim, fontFamily: "var(--font-mono)" }}>
              <input type="radio" name="metric" checked={metric === m} onChange={() => setMetric(m)} />
              {metricLabels[m]}
            </label>
          ))}
        </div>
        {results.length === 0 && !running && (
          <div className="text-[11px] py-5" style={{ color: colors.muted, fontFamily: "var(--font-mono)" }}>
            Set parameters and click Run Grid Search.
          </div>
        )}
        {results.length > 0 && (
          <ChartCard title={`HEATMAP — ${metricLabels[metric]}`}>
            <div className="overflow-x-auto">
              <table className="text-[9px]" style={{ fontFamily: "var(--font-mono)", borderCollapse: "collapse" }}>
                <thead>
                  <tr>
                    <th className="px-1 py-0.5" style={{ color: colors.dim }}>{yParam}\{xParam}</th>
                    {xVals.map((x) => <th key={x} className="px-2 py-0.5 text-center" style={{ color: colors.muted }}>{x.toFixed(1)}</th>)}
                  </tr>
                </thead>
                <tbody>
                  {yVals.map((y) => (
                    <tr key={y}>
                      <td className="px-1 py-0.5" style={{ color: colors.muted }}>{y.toFixed(1)}</td>
                      {xVals.map((x) => {
                        const cell = cellMap.get(`${x},${y}`);
                        const val = cell ? cell[metric] : 0;
                        return (
                          <td key={x} className="px-2 py-1 text-center" style={{ background: heatColor(val), color: "#fff", fontWeight: 600, borderRadius: 2 }}>
                            {val.toFixed(1)}
                          </td>
                        );
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </ChartCard>
        )}
      </div>
    </div>
  );
}
