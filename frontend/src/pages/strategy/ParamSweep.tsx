import { useEffect, useMemo, useState } from "react";
import { ChartCard } from "@/components/ChartCard";
import { StatCard, StatRow } from "@/components/StatCard";
import { SectionLabel, ParamInput } from "@/components/Sidebar";
import { useStrategyStore } from "@/stores/strategyStore";
import { runBacktest, startOptimizer, fetchOptimizerStatus } from "@/lib/api";
import type { BacktestResult, OptimizerStatus } from "@/lib/api";
import { colors } from "@/lib/theme";


type SweepMethod = "grid" | "random" | "walkforward";
type Metric = "mean_ret" | "sharpe" | "sortino" | "win_rate" | "std_dev";
const metricLabels: Record<Metric, string> = {
  mean_ret: "E[Return %]", sharpe: "Sharpe", sortino: "Sortino", win_rate: "Win Rate %", std_dev: "Std Dev",
};

interface CellResult {
  xVal: number;
  yVal: number;
  mean_ret: number;
  sharpe: number;
  sortino: number;
  win_rate: number;
  std_dev: number;
  fullResult?: BacktestResult;
}

function fmtAxis(v: number): string {
  const abs = Math.abs(v);
  if (abs === 0) return "0";
  if (abs >= 100) return v.toFixed(0);
  if (abs >= 1) return v.toFixed(1);
  if (abs >= 0.01) return v.toFixed(3);
  return v.toFixed(4);
}

const inputStyle: React.CSSProperties = {
  background: "var(--color-qe-input)",
  border: "1px solid var(--color-qe-input-border)",
  color: "var(--color-qe-text)",
  fontFamily: "var(--font-mono)",
  fontSize: 11,
  outline: "none",
};

function downsample(arr: number[], maxPts: number): number[] {
  if (arr.length <= maxPts) return arr;
  const step = (arr.length - 1) / (maxPts - 1);
  return Array.from({ length: maxPts }, (_, i) => arr[Math.round(i * step)]);
}

function MiniEquity({ equity, bnh }: { equity: number[]; bnh: number[] }) {
  const w = 360, h = 100, pad = 2;
  const eq = downsample(equity, 200);
  const bh = downsample(bnh, 200);
  let mn = Infinity, mx = -Infinity;
  for (const v of eq) { if (v < mn) mn = v; if (v > mx) mx = v; }
  for (const v of bh) { if (v < mn) mn = v; if (v > mx) mx = v; }
  const rng = mx - mn || 1;
  const toPath = (arr: number[]) =>
    arr.map((v, i) => {
      const x = pad + (i / (arr.length - 1)) * (w - 2 * pad);
      const y = h - pad - ((v - mn) / rng) * (h - 2 * pad);
      return `${i === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`;
    }).join(" ");
  return (
    <svg viewBox={`0 0 ${w} ${h}`} width={w} height={h} style={{ display: "block" }}>
      <path d={toPath(bh)} fill="none" stroke={colors.dim} strokeWidth={1} strokeDasharray="3,3" />
      <path d={toPath(eq)} fill="none" stroke={colors.cyan} strokeWidth={1.5} />
    </svg>
  );
}

function CellDetailPanel({ cell, xParam, yParam, onClose }: { cell: CellResult; xParam: string; yParam: string; onClose: () => void }) {
  const r = cell.fullResult!;
  const m = r.metrics;
  const fmtPct = (v?: number) => v != null ? `${(v * 100).toFixed(2)}%` : "—";
  const fmtNum = (v?: number) => v != null ? v.toFixed(2) : "—";
  const rows: [string, string, string][] = [
    ["Total Return", fmtPct(m.total_return), m.total_return >= 0 ? colors.green : colors.red],
    ["Sharpe", fmtNum(m.sharpe), m.sharpe >= 1 ? colors.green : m.sharpe >= 0 ? colors.text : colors.red],
    ["Sortino", fmtNum(m.sortino), colors.text],
    ["Calmar", fmtNum(m.calmar), colors.text],
    ["Win Rate", fmtPct(m.win_rate), colors.text],
    ["Max DD", fmtPct(m.max_drawdown), colors.red],
    ["Annual Vol", fmtPct(m.annual_volatility), colors.text],
    ["Trades", String(m.total_trades ?? 0), colors.muted],
    ["Profit Factor", fmtNum(m.profit_factor), colors.text],
  ];
  return (
    <ChartCard title={`CELL DETAIL — ${xParam}=${cell.xVal}, ${yParam}=${cell.yVal}`}>
      <div className="px-4 py-3">
        <div className="flex gap-6">
          {/* Mini equity chart */}
          <div className="shrink-0">
            <div className="text-[10px] mb-1" style={{ color: colors.dim, fontFamily: "var(--font-mono)" }}>
              <span style={{ color: colors.cyan }}>━</span> Strategy
              <span className="ml-3" style={{ color: colors.dim }}>┄</span> B&H
            </div>
            <MiniEquity equity={r.equity_curve} bnh={r.bnh_equity} />
          </div>
          {/* Metrics table */}
          <div className="flex-1 min-w-0">
            <table className="w-full text-[11px]" style={{ fontFamily: "var(--font-mono)" }}>
              <tbody>
                {rows.map(([label, val, color]) => (
                  <tr key={label} style={{ borderBottom: `1px solid ${colors.cardBorder}` }}>
                    <td className="py-1.5 pr-4" style={{ color: colors.dim }}>{label}</td>
                    <td className="py-1.5 text-right font-semibold" style={{ color }}>{val}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
        <button onClick={onClose} className="mt-3 text-[10px] cursor-pointer border-none bg-transparent" style={{ color: colors.dim, fontFamily: "var(--font-mono)" }}>
          ✕ Close
        </button>
      </div>
    </ChartCard>
  );
}

export function ParamSweep() {
  const strategy = useStrategyStore((s) => s.strategy);
  const symbol = useStrategyStore((s) => s.symbol);
  const startDate = useStrategyStore((s) => s.startDate);
  const endDate = useStrategyStore((s) => s.endDate);
  const params = useStrategyStore((s) => s.params);
  const strategies = useStrategyStore((s) => s.strategies);
  const slippageBps = useStrategyStore((s) => s.slippageBps);
  const commissionBps = useStrategyStore((s) => s.commissionBps);
  const currentStrat = strategies.find((s) => s.slug === strategy);
  const paramOpts = currentStrat
    ? Object.entries(currentStrat.param_grid).map(([k, v]) => ({ value: k, label: v.label || k }))
    : [];

  const [method, setMethod] = useState<SweepMethod>("grid");
  const [metric, setMetric] = useState<Metric>("sortino");
  const [xParam, setXParam] = useState("");
  const [yParam, setYParam] = useState("");
  const [xMin, setXMin] = useState(1);
  const [xMax, setXMax] = useState(3);
  const [xSteps, setXSteps] = useState(6);
  const [yMin, setYMin] = useState(2);
  const [yMax, setYMax] = useState(8);
  const [ySteps, setYSteps] = useState(6);
  const [gridResults, setGridResults] = useState<CellResult[]>([]);
  const [selectedCellKey, setSelectedCellKey] = useState<string | null>(null);
  const [paramGridStr, setParamGridStr] = useState<Record<string, string>>({});
  const [isFraction, setIsFraction] = useState(0.8);
  const [objective, setObjective] = useState("sortino");
  const [nJobs, setNJobs] = useState(2);
  const [optStatus, setOptStatus] = useState<OptimizerStatus | null>(null);
  const [running, setRunning] = useState(false);
  const [progress, setProgress] = useState("");

  useEffect(() => {
    if (!currentStrat?.param_grid) return;
    const keys = Object.keys(currentStrat.param_grid);
    if (keys[0] && !xParam) setXParam(keys[0]);
    if (keys[1] && !yParam) setYParam(keys[1]);
    else if (keys[0] && !yParam) setYParam(keys[0]);
    const defaults: Record<string, string> = {};
    for (const [k, v] of Object.entries(currentStrat.param_grid)) {
      defaults[k] = (v.default ?? []).join(",");
    }
    setParamGridStr(defaults);
  }, [strategy, strategies]);

  const linspace = (min: number, max: number, steps: number) => {
    if (steps <= 1) return [min];
    return Array.from({ length: steps }, (_, i) => min + (max - min) * i / (steps - 1));
  };

  const handleRunGrid = async () => {
    if (!strategy || !xParam || !yParam) return;
    setRunning(true);
    setGridResults([]);
    setSelectedCellKey(null);
    useStrategyStore.getState().setLocked(true);
    const xVals = linspace(xMin, xMax, xSteps);
    const yVals = linspace(yMin, yMax, ySteps);
    const total = xVals.length * yVals.length;
    const cells: CellResult[] = [];
    let done = 0;
    for (const xv of xVals) {
      for (const yv of yVals) {
        const merged = { ...params, [xParam]: xv, [yParam]: yv };
        try {
          const r = await runBacktest({
            strategy, symbol, start: startDate, end: endDate, params: merged,
            slippage_bps: slippageBps, commission_bps: commissionBps,
          });
          const m = r.metrics;
          cells.push({
                    xVal: xv, yVal: yv,
                    mean_ret: (m.total_return ?? 0) * 100,
                    sharpe: m.sharpe ?? 0,
                    sortino: m.sortino ?? 0,
                    win_rate: (m.win_rate ?? 0) * 100,
                    std_dev: (m.annual_volatility ?? 0) * 100,
                    fullResult: r,
                  });
                } catch (err) {
                  console.warn(`Grid cell [${xParam}=${xv}, ${yParam}=${yv}] failed:`, err);
                  cells.push({ xVal: xv, yVal: yv, mean_ret: 0, sharpe: 0, sortino: 0, win_rate: 0, std_dev: 0 });
        }
        done++;
        setProgress(`${done}/${total}`);
      }
    }
    setGridResults(cells);
    setRunning(false);
    useStrategyStore.getState().setLocked(false);
  };

  const handleRunOptimizer = async () => {
    const parsed: Record<string, number[]> = {};
    for (const [k, v] of Object.entries(paramGridStr)) {
      parsed[k] = v.split(",").map(Number).filter((n) => !isNaN(n));
    }
    try {
      useStrategyStore.getState().setLocked(true);
      await startOptimizer({
        strategy, symbol, start: startDate, end: endDate,
        param_grid: parsed, is_fraction: isFraction, objective, n_jobs: nJobs,
        slippage_bps: slippageBps, commission_bps: commissionBps,
      });
      setRunning(true);
      const poll = setInterval(async () => {
        const s = await fetchOptimizerStatus();
        setOptStatus(s);
        if (s.finished || s.error) {
          clearInterval(poll);
          setRunning(false);
          useStrategyStore.getState().setLocked(false);
        }
      }, 2000);
    } catch {
      useStrategyStore.getState().setLocked(false);
    }
  };

  const handleRun = () => {
    if (method === "grid") handleRunGrid();
    else handleRunOptimizer();
  };

  // Grid results rendering
  const xVals = [...new Set(gridResults.map((r) => r.xVal))].sort((a, b) => a - b);
  const yVals = [...new Set(gridResults.map((r) => r.yVal))].sort((a, b) => a - b);
  const cellMap = new Map(gridResults.map((r) => [`${r.xVal},${r.yVal}`, r]));
  const metricVals = gridResults.map((r) => r[metric]);
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

  // Optimizer results
  const optResult = optStatus?.result_data as Record<string, unknown> | null;
  const topTrials = useMemo(
    () => (optResult?.top_trials ?? []) as { rank: number; params: Record<string, number>; sharpe: number; score: number }[],
    [optResult],
  );

  const selectedCell = selectedCellKey ? cellMap.get(selectedCellKey) ?? null : null;

  const bestCell = useMemo(() => {
    if (!gridResults.length) return null;
    return gridResults.reduce((best, c) =>
      metric === "std_dev" ? (c[metric] < best[metric] ? c : best) : (c[metric] > best[metric] ? c : best),
    );
  }, [gridResults, metric]);

  return (
    <div className="p-3 overflow-y-auto" style={{ minWidth: 0 }}>
      {/* Controls */}
      <div className="flex flex-col gap-2 mb-4" style={{ fontFamily: "var(--font-mono)" }}>
        {method === "grid" ? (
          <>
            {/* Row 1: Method + X axis */}
            <div className="flex items-end gap-4">
              <div>
                <div className="text-[11px] mb-1" style={{ color: colors.dim }}>Method</div>
                <select value={method} onChange={(e) => setMethod(e.target.value as SweepMethod)} className="rounded px-2 py-1.5 text-[11px]" style={inputStyle}>
                  <option value="grid">Grid Search</option>
                  <option value="random">Random Search</option>
                  <option value="walkforward">Walk-Forward</option>
                </select>
              </div>
              <div>
                <div className="text-[11px] mb-1" style={{ color: colors.dim }}>X Param</div>
                <select value={xParam} onChange={(e) => setXParam(e.target.value)} className="rounded px-2 py-1.5 text-[11px]" style={inputStyle}>
                  {paramOpts.map((p) => <option key={p.value} value={p.value}>{p.label}</option>)}
                </select>
              </div>
              <div className="flex gap-1.5 items-end">
                <ParamInput label="min"><input type="number" value={xMin} step={0.1} onChange={(e) => setXMin(Number(e.target.value))} className="w-16 rounded px-1.5 py-1 text-[11px]" style={inputStyle} /></ParamInput>
                <ParamInput label="max"><input type="number" value={xMax} step={0.1} onChange={(e) => setXMax(Number(e.target.value))} className="w-16 rounded px-1.5 py-1 text-[11px]" style={inputStyle} /></ParamInput>
                <ParamInput label="#"><input type="number" value={xSteps} min={2} max={12} onChange={(e) => setXSteps(Number(e.target.value))} className="w-14 rounded px-1.5 py-1 text-[11px]" style={inputStyle} /></ParamInput>
              </div>
            </div>
            {/* Row 2: Y axis + Run button */}
            <div className="flex items-end gap-4">
              <div style={{ visibility: "hidden" }}>
                <div className="text-[11px] mb-1">Method</div>
                <select className="rounded px-2 py-1.5 text-[11px]" style={inputStyle}><option>—</option></select>
              </div>
              <div>
                <div className="text-[11px] mb-1" style={{ color: colors.dim }}>Y Param</div>
                <select value={yParam} onChange={(e) => setYParam(e.target.value)} className="rounded px-2 py-1.5 text-[11px]" style={inputStyle}>
                  {paramOpts.map((p) => <option key={p.value} value={p.value}>{p.label}</option>)}
                </select>
              </div>
              <div className="flex gap-1.5 items-end">
                <ParamInput label="min"><input type="number" value={yMin} step={0.5} onChange={(e) => setYMin(Number(e.target.value))} className="w-16 rounded px-1.5 py-1 text-[11px]" style={inputStyle} /></ParamInput>
                <ParamInput label="max"><input type="number" value={yMax} step={0.5} onChange={(e) => setYMax(Number(e.target.value))} className="w-16 rounded px-1.5 py-1 text-[11px]" style={inputStyle} /></ParamInput>
                <ParamInput label="#"><input type="number" value={ySteps} min={2} max={12} onChange={(e) => setYSteps(Number(e.target.value))} className="w-14 rounded px-1.5 py-1 text-[11px]" style={inputStyle} /></ParamInput>
              </div>
              <button
                onClick={handleRun}
                disabled={running}
                className="py-1.5 px-6 rounded text-[11px] font-semibold cursor-pointer border-none text-white"
                style={{ background: "#2A6A4A", fontFamily: "var(--font-mono)", opacity: running ? 0.5 : 1, whiteSpace: "nowrap" }}
              >
                {running ? `Running… ${progress}` : "Run Grid Search"}
              </button>
            </div>
          </>
        ) : (
          <div className="flex items-end gap-4 flex-wrap">
            <div>
              <div className="text-[11px] mb-1" style={{ color: colors.dim }}>Method</div>
              <select value={method} onChange={(e) => setMethod(e.target.value as SweepMethod)} className="rounded px-2 py-1.5 text-[11px]" style={inputStyle}>
                <option value="grid">Grid Search</option>
                <option value="random">Random Search</option>
                <option value="walkforward">Walk-Forward</option>
              </select>
            </div>
            <div>
              <div className="text-[11px] mb-1" style={{ color: colors.dim }}>Objective</div>
              <select value={objective} onChange={(e) => setObjective(e.target.value)} className="rounded px-2 py-1.5 text-[11px]" style={inputStyle}>
                <option value="sortino">Sortino</option>
                <option value="sharpe">Sharpe</option>
                <option value="calmar">Calmar</option>
                <option value="total_return">Total Return</option>
              </select>
            </div>
            <div>
              <div className="text-[11px] mb-1" style={{ color: colors.dim }}>IS Frac</div>
              <input type="number" value={isFraction} min={0.5} max={0.95} step={0.05} onChange={(e) => setIsFraction(Number(e.target.value))} className="w-16 rounded px-1.5 py-1 text-[11px]" style={inputStyle} />
            </div>
            <div>
              <div className="text-[11px] mb-1" style={{ color: colors.dim }}>Jobs</div>
              <input type="number" value={nJobs} min={1} max={8} step={1} onChange={(e) => setNJobs(Number(e.target.value))} className="w-14 rounded px-1.5 py-1 text-[11px]" style={inputStyle} />
            </div>
            <button
              onClick={handleRun}
              disabled={running}
              className="py-1.5 px-6 rounded text-[11px] font-semibold cursor-pointer border-none text-white"
              style={{ background: "#2A6A4A", fontFamily: "var(--font-mono)", opacity: running ? 0.5 : 1, whiteSpace: "nowrap" }}
            >
              {running ? `Running… ${optStatus?.progress ?? ""}` : `Run ${method === "random" ? "Random Search" : "Walk-Forward"}`}
            </button>
          </div>
        )}
      </div>
      {/* Param grid inputs for optimizer mode */}
      {method !== "grid" && currentStrat?.param_grid && (
        <div className="mb-3 p-3 rounded" style={{ border: "1px solid var(--color-qe-card-border)", background: "var(--color-qe-card)" }}>
          <SectionLabel>PARAM GRID (comma-separated)</SectionLabel>
          <div className="flex flex-wrap gap-3">
            {Object.entries(currentStrat.param_grid).map(([key, cfg]) => (
              <div key={key} className="flex items-center gap-1.5">
                <span className="text-[11px]" style={{ color: colors.dim, fontFamily: "var(--font-mono)" }}>{cfg.label || key}:</span>
                <input
                  type="text"
                  value={paramGridStr[key] ?? ""}
                  onChange={(e) => setParamGridStr({ ...paramGridStr, [key]: e.target.value })}
                  className="w-32 rounded px-1.5 py-1 text-[11px]"
                  placeholder="e.g. 15,20,25"
                  style={inputStyle}
                />
              </div>
            ))}
          </div>
        </div>
      )}
      {/* Grid results */}
      {method === "grid" && (
        <>
          <div className="flex items-center gap-4 mb-4">
            <span className="text-[11px]" style={{ color: colors.muted, fontFamily: "var(--font-mono)" }}>Metric:</span>
            {(Object.keys(metricLabels) as Metric[]).map((m) => (
              <label key={m} className="flex items-center gap-1.5 text-[11px] cursor-pointer" style={{ color: metric === m ? colors.text : colors.dim, fontFamily: "var(--font-mono)" }}>
                <input type="radio" name="metric" checked={metric === m} onChange={() => setMetric(m)} />
                {metricLabels[m]}
              </label>
            ))}
          </div>
          {gridResults.length === 0 && !running && (
            <div className="text-[11px] py-5" style={{ color: colors.muted, fontFamily: "var(--font-mono)" }}>Configure sweep axes and click Run Grid Search.</div>
          )}
          {gridResults.length > 0 && (
            <>
              {bestCell && (
                <StatRow>
                  <StatCard label={`BEST ${metricLabels[metric].toUpperCase()}`} value={bestCell[metric].toFixed(2)} color={colors.green} />
                  <StatCard label="AT X" value={`${xParam} = ${bestCell.xVal}`} color={colors.cyan} />
                  <StatCard label="AT Y" value={`${yParam} = ${bestCell.yVal}`} color={colors.cyan} />
                  <StatCard label="CELLS" value={`${xVals.length}×${yVals.length}`} color={colors.muted} />
                </StatRow>
              )}
              <ChartCard title={`HEATMAP — ${metricLabels[metric]}   (click a cell for details)`}>
                <div className="overflow-x-auto px-2 pb-2">
                  <table style={{ fontFamily: "var(--font-mono)", borderCollapse: "separate", borderSpacing: 3 }}>
                    <thead>
                      <tr>
                        <th className="px-3 py-2 text-left text-xs" style={{ color: colors.dim }}>
                          <span style={{ color: colors.muted }}>{yParam}</span>
                          <span style={{ color: colors.dim, margin: "0 4px", opacity: 0.5 }}>⧸</span>
                          <span style={{ color: colors.muted }}>{xParam}</span>
                        </th>
                        {xVals.map((x) => (
                          <th key={x} className="px-3 py-2 text-center text-xs font-semibold" style={{ color: colors.muted }}>{fmtAxis(x)}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {yVals.map((y) => (
                        <tr key={y}>
                          <td className="px-3 py-2 text-xs font-semibold" style={{ color: colors.muted }}>{fmtAxis(y)}</td>
                          {xVals.map((x) => {
                            const cell = cellMap.get(`${x},${y}`);
                            const val = cell ? cell[metric] : 0;
                            const isBest = bestCell && cell === bestCell;
                            const isSelected = selectedCellKey === `${x},${y}`;
                            const bg = heatColor(val);
                            return (
                              <td key={x} style={{ padding: 2 }}>
                                <button
                                  type="button"
                                  className="text-xs font-bold border-none w-full"
                                  onClick={() => {
                                    if (cell?.fullResult) setSelectedCellKey(`${x},${y}`);
                                  }}
                                  style={{
                                    background: bg,
                                    color: "#fff",
                                    borderRadius: 4,
                                    minWidth: 52,
                                    padding: "8px 12px",
                                    cursor: cell?.fullResult ? "pointer" : "default",
                                    fontFamily: "var(--font-mono)",
                                    outline: isSelected
                                      ? `2px solid ${colors.gold}`
                                      : isBest ? `2px solid ${colors.cyan}` : "none",
                                    outlineOffset: (isSelected || isBest) ? -1 : undefined,
                                  }}
                                >
                                  {val.toFixed(2)}
                                </button>
                              </td>
                            );
                          })}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </ChartCard>
              {/* Detail panel for selected cell */}
              {selectedCell?.fullResult && (
                <CellDetailPanel cell={selectedCell} xParam={xParam} yParam={yParam} onClose={() => setSelectedCellKey(null)} />
              )}
            </>
          )}
        </>
      )}
      {/* Optimizer results */}
      {method !== "grid" && (
        <>
          {!optStatus && !running && (
            <div className="text-[11px] py-5" style={{ color: colors.muted, fontFamily: "var(--font-mono)" }}>
              Configure param grid and click Run.
            </div>
          )}
          {running && (
            <div className="text-[11px] py-3" style={{ color: colors.cyan, fontFamily: "var(--font-mono)" }}>
              Optimizing… {optStatus?.progress ?? ""}
            </div>
          )}
          {optStatus?.finished && optResult && (
            <>
              <StatRow>
                <StatCard label="BEST SHARPE" value={String((optResult.best_sharpe as number)?.toFixed(2) ?? "—")} color={colors.green} />
                <StatCard label="TRIALS" value={String(optResult.n_trials ?? "—")} color={colors.cyan} />
                <StatCard label="OBJECTIVE" value={objective.toUpperCase()} color={colors.muted} />
              </StatRow>
              {topTrials.length > 0 && (
                <ChartCard title="TOP RESULTS">
                  <div className="max-h-[300px] overflow-y-auto">
                    <table className="w-full text-[11px]" style={{ fontFamily: "var(--font-mono)" }}>
                      <thead>
                        <tr style={{ borderBottom: `1px solid ${colors.cardBorder}` }}>
                          <th className="text-left py-2 px-3" style={{ color: colors.dim }}>#</th>
                          <th className="text-left py-2 px-3" style={{ color: colors.dim }}>Score</th>
                          <th className="text-left py-2 px-3" style={{ color: colors.dim }}>Sharpe</th>
                          <th className="text-left py-2 px-3" style={{ color: colors.dim }}>Params</th>
                        </tr>
                      </thead>
                      <tbody>
                        {topTrials.map((t, i) => (
                          <tr key={i} style={{ borderBottom: `1px solid ${colors.cardBorder}` }}>
                            <td className="py-2 px-3" style={{ color: colors.muted }}>{t.rank}</td>
                            <td className="py-2 px-3" style={{ color: colors.green }}>{t.score?.toFixed(3)}</td>
                            <td className="py-2 px-3" style={{ color: colors.cyan }}>{t.sharpe?.toFixed(2)}</td>
                            <td className="py-2 px-3" style={{ color: colors.text }}>{JSON.stringify(t.params)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </ChartCard>
              )}
            </>
          )}
        </>
      )}
    </div>
  );
}
