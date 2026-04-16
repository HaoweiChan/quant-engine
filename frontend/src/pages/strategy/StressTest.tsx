import React, { useMemo, useState } from "react";
import { StatCard, StatRow } from "@/components/StatCard";
import { ChartCard } from "@/components/ChartCard";
import { useStrategyStore } from "@/stores/strategyStore";
import { runMonteCarloSim } from "@/lib/api";
import type { MCSimulationResult } from "@/lib/api";
import { colors, pnlColor } from "@/lib/theme";


type MCMethod = "stationary" | "circular" | "garch";

const SVG_W = 600;
const SVG_H = 260;
const PAD = { top: 10, bottom: 20, left: 60, right: 10 };

const FanChartSVG = React.memo(function FanChartSVG({
  bands,
}: {
  bands: MCSimulationResult["bands"];
}) {
  const len = bands.p50.length;
  const { yMin, yMax, ticks, fmtY } = useMemo(() => {
    let lo = Infinity, hi = -Infinity;
    for (const v of bands.p5) { if (v < lo) lo = v; }
    for (const v of bands.p95) { if (v > hi) hi = v; }
    if (!isFinite(lo)) { lo = 0; hi = 1; }
    const pad = (hi - lo) * 0.05 || 1;
    lo -= pad; hi += pad;
    const range = hi - lo;
    // Pick a nice step aiming for 4-6 ticks
    const rawStep = range / 5;
    const mag = Math.pow(10, Math.floor(Math.log10(rawStep)));
    const niceSteps = [1, 2, 2.5, 5, 10];
    const step = mag * (niceSteps.find((s) => s * mag >= rawStep) ?? 10);
    const arr: number[] = [];
    let t = Math.ceil(lo / step) * step;
    while (t <= hi) { arr.push(t); t += step; }
    // Adaptive precision so ticks always display distinct labels
    const fmtY = (v: number): string => {
      if (Math.abs(v) >= 1e6) {
        const dec = range < 5e5 ? 2 : range < 5e6 ? 1 : 0;
        return `${(v / 1e6).toFixed(dec)}M`;
      }
      if (Math.abs(v) >= 1e3) {
        const dec = range < 5e3 ? 1 : 0;
        return `${(v / 1e3).toFixed(dec)}K`;
      }
      return v.toFixed(0);
    };
    return { yMin: lo, yMax: hi, ticks: arr, fmtY };
  }, [bands]);

  const xScale = (i: number) => PAD.left + (i / (len - 1)) * (SVG_W - PAD.left - PAD.right);
  const yScale = (v: number) => PAD.top + (1 - (v - yMin) / (yMax - yMin)) * (SVG_H - PAD.top - PAD.bottom);

  const bandArea = (upper: number[], lower: number[]) => {
    const fwd = upper.map((_, i) => `${xScale(i)},${yScale(upper[i])}`).join(" ");
    const bwd = [...lower].reverse().map((_, i) => `${xScale(len - 1 - i)},${yScale(lower[len - 1 - i])}`).join(" ");
    return `${fwd} ${bwd}`;
  };

  return (
    <svg viewBox={`0 0 ${SVG_W} ${SVG_H}`} style={{ width: "100%", height: "auto" }}>
      {ticks.map((t) => (
        <g key={t}>
          <line x1={PAD.left} x2={SVG_W - PAD.right} y1={yScale(t)} y2={yScale(t)} stroke="rgba(255,255,255,0.05)" />
          <text x={PAD.left - 4} y={yScale(t) + 3} textAnchor="end" fill={colors.dim} fontSize={8} fontFamily="var(--font-mono)">{fmtY(t)}</text>
        </g>
      ))}
      {/* 5th–95th band (lightest) */}
      <polygon points={bandArea(bands.p95, bands.p5)} fill={colors.blue} opacity={0.08} />
      {/* 25th–75th band */}
      <polygon points={bandArea(bands.p75, bands.p25)} fill={colors.blue} opacity={0.15} />
      {/* Median line */}
      <polyline
        fill="none"
        stroke={colors.cyan}
        strokeWidth={1.5}
        points={bands.p50.map((v, i) => `${xScale(i)},${yScale(v)}`).join(" ")}
      />
      {/* Day labels */}
      {[0, Math.floor(len / 4), Math.floor(len / 2), Math.floor((3 * len) / 4), len - 1].map((d) => (
        <text key={d} x={xScale(d)} y={SVG_H - 4} textAnchor="middle" fill={colors.dim} fontSize={7} fontFamily="var(--font-mono)">
          {d === 0 ? "0" : `${d}d`}
        </text>
      ))}
    </svg>
  );
});

export function StressTest() {
  const strategy = useStrategyStore((s) => s.strategy);
  const symbol = useStrategyStore((s) => s.symbol);
  const startDate = useStrategyStore((s) => s.startDate);
  const endDate = useStrategyStore((s) => s.endDate);
  const params = useStrategyStore((s) => s.params);
  const initialCapital = useStrategyStore((s) => s.initialCapital);
  const slippageBps = useStrategyStore((s) => s.slippageBps);
  const commissionBps = useStrategyStore((s) => s.commissionBps);
  const commissionFixed = useStrategyStore((s) => s.commissionFixed);
  const [method, setMethod] = useState<MCMethod>("stationary");
  const [nPaths, setNPaths] = useState(500);
  const [simDays, setSimDays] = useState(252);
  const [result, setResult] = useState<MCSimulationResult | null>(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleRun = async () => {
    setRunning(true);
    setError(null);
    setResult(null);
    useStrategyStore.getState().setLocked(true);
    try {
      const r = await runMonteCarloSim({
        strategy,
        symbol,
        start: startDate,
        end: endDate,
        params,
        initial_equity: initialCapital,
        slippage_bps: slippageBps,
        commission_bps: commissionBps,
        commission_fixed_per_contract: commissionFixed,
        n_paths: nPaths,
        n_days: simDays,
        method,
      });
      setResult(r);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setRunning(false);
      useStrategyStore.getState().setLocked(false);
    }
  };

  const finalValues = useMemo(() => {
    if (!result?.bands?.p50) return [];
    // Build synthetic distribution from percentile endpoints for histogram
    const keys = ["p5", "p25", "p50", "p75", "p95"] as const;
    return keys.map((k) => result.bands[k][result.bands[k].length - 1]);
  }, [result]);

  const inputStyle: React.CSSProperties = {
    background: "var(--color-qe-input)",
    border: "1px solid var(--color-qe-input-border)",
    color: "var(--color-qe-text)",
    fontFamily: "var(--font-mono)",
    fontSize: 11,
    outline: "none",
  };
  const fmtDollar = (v: number) => `$${v.toLocaleString(undefined, { maximumFractionDigits: 0 })}`;

  return (
    <div className="p-3 overflow-y-auto" style={{ minWidth: 0 }}>
      <div className="flex items-center gap-3 mb-3 flex-wrap">
        <select value={method} onChange={(e) => setMethod(e.target.value as MCMethod)} className="rounded px-1.5 py-1 text-[11px]" style={inputStyle}>
          <option value="stationary">Block Bootstrap (Stationary)</option>
          <option value="circular">Block Bootstrap (Circular)</option>
          <option value="garch">GARCH-Filtered Residuals</option>
        </select>
        <label className="flex items-center gap-1 text-[11px]" style={{ color: colors.dim, fontFamily: "var(--font-mono)" }}>
          Paths
          <input type="number" value={nPaths} min={50} max={5000} step={50} onChange={(e) => setNPaths(Number(e.target.value))} className="w-16 rounded px-1 py-0.5 text-[11px]" style={inputStyle} />
        </label>
        <label className="flex items-center gap-1 text-[11px]" style={{ color: colors.dim, fontFamily: "var(--font-mono)" }}>
          Days
          <input type="number" value={simDays} min={20} max={756} step={1} onChange={(e) => setSimDays(Number(e.target.value))} className="w-16 rounded px-1 py-0.5 text-[11px]" style={inputStyle} />
        </label>
        <button
          onClick={handleRun}
          disabled={running || !strategy}
          className="py-1.5 px-5 rounded text-[11px] font-semibold cursor-pointer border-none text-white"
          style={{ background: "#2A5A9A", fontFamily: "var(--font-mono)", opacity: running ? 0.5 : 1 }}
        >
          {running ? "Simulating…" : "Run Stress Test"}
        </button>
      </div>
      {error && (
        <div className="rounded-[5px] p-3 mb-2.5 text-[11px]" style={{ border: `1px solid ${colors.red}`, color: colors.red, fontFamily: "var(--font-mono)" }}>
          {error}
        </div>
      )}
      {!result && !running && !error && (
        <div className="text-[11px] py-5" style={{ color: colors.muted, fontFamily: "var(--font-mono)" }}>
          Select method and click Run Stress Test. Uses server-side block-bootstrap Monte Carlo.
        </div>
      )}
      {running && (
        <div className="text-[11px] py-5" style={{ color: colors.cyan, fontFamily: "var(--font-mono)" }}>
          Running {method} simulation with {nPaths} paths × {simDays} days…
        </div>
      )}
      {result && (
        <>
          <StatRow>
            <StatCard label="VaR 95%" value={fmtDollar(result.var_95)} color={colors.red} />
            <StatCard label="VaR 99%" value={fmtDollar(result.var_99)} color={colors.red} />
            <StatCard label="CVaR 95%" value={fmtDollar(result.cvar_95)} color={colors.red} />
            <StatCard label="CVaR 99%" value={fmtDollar(result.cvar_99)} color={colors.red} />
            <StatCard label="MEDIAN FINAL" value={fmtDollar(result.median_final)} color={pnlColor(result.median_final - initialCapital)} />
            <StatCard label="P(RUIN)" value={`${(result.prob_ruin * 100).toFixed(1)}%`} color={result.prob_ruin > 0.05 ? colors.red : colors.green} />
          </StatRow>
          <ChartCard title={`EQUITY FAN CHART — ${result.n_paths} paths × ${result.n_days}d (${result.method})`}>
            <FanChartSVG bands={result.bands} />
          </ChartCard>
          {finalValues.length > 0 && (
            <ChartCard title="TERMINAL EQUITY PERCENTILES">
              <div className="flex items-end gap-4 px-6 pt-4 pb-3" style={{ height: 160 }}>
                {(["p5", "p25", "p50", "p75", "p95"] as const).map((k) => {
                  const val = result.bands[k][result.bands[k].length - 1];
                  const max = result.bands.p95[result.bands.p95.length - 1];
                  const min = result.bands.p5[result.bands.p5.length - 1];
                  const pct = max === min ? 65 : 30 + ((val - min) / (max - min)) * 70;
                  const delta = val - initialCapital;
                  const deltaStr = delta >= 0 ? `+${fmtDollar(delta)}` : `-${fmtDollar(Math.abs(delta))}`;
                  return (
                    <div key={k} className="flex flex-col items-center flex-1 gap-1.5">
                      <span className="text-xs font-medium" style={{ color: colors.dim, fontFamily: "var(--font-mono)" }}>{fmtDollar(val)}</span>
                      <span className="text-[11px]" style={{ color: delta >= 0 ? colors.green : colors.red, fontFamily: "var(--font-mono)" }}>{deltaStr}</span>
                      <div className="w-full rounded-sm" style={{ height: `${pct}%`, background: k === "p50" ? colors.cyan : colors.blue, opacity: k === "p50" ? 1 : 0.55 }} />
                      <span className="text-xs font-semibold" style={{ color: colors.muted, fontFamily: "var(--font-mono)" }}>{k.toUpperCase()}</span>
                    </div>
                  );
                })}
              </div>
            </ChartCard>
          )}
        </>
      )}
    </div>
  );
}
