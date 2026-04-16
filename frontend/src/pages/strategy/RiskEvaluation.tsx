import React, { useMemo, useState } from "react";
import { StatCard, StatRow } from "@/components/StatCard";
import { ChartCard } from "@/components/ChartCard";
import { useStrategyStore } from "@/stores/strategyStore";
import { runMonteCarloSim } from "@/lib/api";
import type { MCSimulationResult } from "@/lib/api";
import { colors, pnlColor } from "@/lib/theme";

type MCMethod = "stationary" | "circular" | "garch";

interface RiskReportData {
  strategy_name: string;
  generated_at: string;
  instrument: string;
  cost_gate: {
    passed: boolean;
    net_sharpe: number;
    cost_drag_pct: number;
  };
  param_stability_gate: {
    passed: boolean;
    likely_overfit: boolean | null;
    robust: boolean | null;
  };
  regime_gate: {
    passed: boolean;
    worst_regime_sharpe: number;
    regime_metrics: Array<{
      label: string;
      sharpe: number;
      mdd_pct: number;
      win_rate: number;
      n_sessions: number;
    }> | null;
  };
  adversarial_gate: {
    passed: boolean;
    worst_case_terminal_equity: number | null;
    median_impact_pct: number | null;
  };
  walk_forward_gate: {
    passed: boolean;
    aggregate_oos_sharpe: number | null;
    overfit_flag: string | null;
  };
  all_gates_passed: boolean;
  failure_reasons: string[];
  recommendation: "promote" | "investigate" | "reject";
}

// ============================================================================
// Stress Test Components (from StressTest.tsx)
// ============================================================================

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
    const rawStep = range / 5;
    const mag = Math.pow(10, Math.floor(Math.log10(rawStep)));
    const niceSteps = [1, 2, 2.5, 5, 10];
    const step = mag * (niceSteps.find((s) => s * mag >= rawStep) ?? 10);
    const arr: number[] = [];
    let t = Math.ceil(lo / step) * step;
    while (t <= hi) { arr.push(t); t += step; }
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
      <polygon points={bandArea(bands.p95, bands.p5)} fill={colors.blue} opacity={0.08} />
      <polygon points={bandArea(bands.p75, bands.p25)} fill={colors.blue} opacity={0.15} />
      <polyline
        fill="none"
        stroke={colors.cyan}
        strokeWidth={1.5}
        points={bands.p50.map((v, i) => `${xScale(i)},${yScale(v)}`).join(" ")}
      />
      {[0, Math.floor(len / 4), Math.floor(len / 2), Math.floor((3 * len) / 4), len - 1].map((d) => (
        <text key={d} x={xScale(d)} y={SVG_H - 4} textAnchor="middle" fill={colors.dim} fontSize={7} fontFamily="var(--font-mono)">
          {d === 0 ? "0" : `${d}d`}
        </text>
      ))}
    </svg>
  );
});

const GateCard = React.memo(function GateCard({
  title,
  passed,
  details,
}: {
  title: string;
  passed: boolean;
  details: React.ReactNode;
}) {
  const statusColor = passed ? colors.green : colors.red;
  const statusText = passed ? "PASS" : "FAIL";

  return (
    <div
      className="rounded-[5px] p-4 mb-3 border"
      style={{
        borderColor: statusColor,
        background: `${statusColor}08`,
      }}
    >
      <div className="flex items-center justify-between mb-2">
        <span className="font-semibold text-[11px]" style={{ color: colors.text, fontFamily: "var(--font-mono)" }}>
          {title}
        </span>
        <span className="text-[11px] font-bold" style={{ color: statusColor, fontFamily: "var(--font-mono)" }}>
          {statusText}
        </span>
      </div>
      <div className="text-[11px]" style={{ color: colors.muted, fontFamily: "var(--font-mono)" }}>
        {details}
      </div>
    </div>
  );
});

// ============================================================================
// Main Component
// ============================================================================

export function RiskEvaluation() {
  const strategy = useStrategyStore((s) => s.strategy);
  const symbol = useStrategyStore((s) => s.symbol);
  const startDate = useStrategyStore((s) => s.startDate);
  const endDate = useStrategyStore((s) => s.endDate);
  const params = useStrategyStore((s) => s.params);
  const initialCapital = useStrategyStore((s) => s.initialCapital);
  const slippageBps = useStrategyStore((s) => s.slippageBps);
  const commissionBps = useStrategyStore((s) => s.commissionBps);
  const commissionFixed = useStrategyStore((s) => s.commissionFixed);

  // Stress Test state
  const [method, setMethod] = useState<MCMethod>("stationary");
  const [nPaths, setNPaths] = useState(500);
  const [simDays, setSimDays] = useState(252);
  const [stressResult, setStressResult] = useState<MCSimulationResult | null>(null);
  const [stressRunning, setStressRunning] = useState(false);
  const [stressError, setStressError] = useState<string | null>(null);

  // Risk Report state
  const [riskResult, setRiskResult] = useState<RiskReportData | null>(null);
  const [riskRunning, setRiskRunning] = useState(false);
  const [riskError, setRiskError] = useState<string | null>(null);

  const handleRunStress = async () => {
    setStressRunning(true);
    setStressError(null);
    setStressResult(null);
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
      setStressResult(r);
    } catch (e) {
      setStressError(e instanceof Error ? e.message : String(e));
    } finally {
      setStressRunning(false);
      useStrategyStore.getState().setLocked(false);
    }
  };

  const handleGenerateReport = async () => {
    if (!strategy) {
      setRiskError("Please select a strategy first");
      return;
    }

    setRiskRunning(true);
    setRiskError(null);
    setRiskResult(null);
    useStrategyStore.getState().setLocked(true);

    try {
      const response = await fetch(`/api/risk-report/${encodeURIComponent(strategy)}?instrument=${symbol}`);
      if (!response.ok) {
        const errData = await response.json().catch(() => ({ detail: response.statusText }));
        throw new Error(errData.detail ?? `HTTP ${response.status}`);
      }
      const data = await response.json();
      setRiskResult(data);
    } catch (e) {
      setRiskError(e instanceof Error ? e.message : String(e));
    } finally {
      setRiskRunning(false);
      useStrategyStore.getState().setLocked(false);
    }
  };

  const finalValues = useMemo(() => {
    if (!stressResult?.bands?.p50) return [];
    const keys = ["p5", "p25", "p50", "p75", "p95"] as const;
    return keys.map((k) => stressResult.bands[k][stressResult.bands[k].length - 1]);
  }, [stressResult]);

  const inputStyle: React.CSSProperties = {
    background: "var(--color-qe-input)",
    border: "1px solid var(--color-qe-input-border)",
    color: "var(--color-qe-text)",
    fontFamily: "var(--font-mono)",
    fontSize: 11,
    outline: "none",
  };

  const fmtDollar = (v: number) => `$${v.toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
  const recommendationColors: Record<string, string> = {
    promote: colors.green,
    investigate: "#FFA500",
    reject: colors.red,
  };

  return (
    <div className="p-3 overflow-y-auto" style={{ minWidth: 0 }}>
      {/* ======== SECTION 1: MONTE CARLO STRESS TEST ======== */}
      <div className="mb-6 pb-6" style={{ borderBottom: `1px solid ${colors.cardBorder}` }}>
        <div className="text-xs font-bold mb-3" style={{ color: colors.muted, fontFamily: "var(--font-mono)" }}>
          SECTION 1: MONTE CARLO STRESS TEST
        </div>
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
            onClick={handleRunStress}
            disabled={stressRunning || !strategy}
            className="py-1.5 px-5 rounded text-[11px] font-semibold cursor-pointer border-none text-white"
            style={{ background: "#2A5A9A", fontFamily: "var(--font-mono)", opacity: stressRunning ? 0.5 : 1 }}
          >
            {stressRunning ? "Simulating…" : "Run Stress Test"}
          </button>
        </div>

        {stressError && (
          <div className="rounded-[5px] p-3 mb-2.5 text-[11px]" style={{ border: `1px solid ${colors.red}`, color: colors.red, fontFamily: "var(--font-mono)" }}>
            {stressError}
          </div>
        )}

        {!stressResult && !stressRunning && !stressError && (
          <div className="text-[11px] py-5" style={{ color: colors.muted, fontFamily: "var(--font-mono)" }}>
            Select method and click Run Stress Test. Uses server-side block-bootstrap Monte Carlo.
          </div>
        )}

        {stressRunning && (
          <div className="text-[11px] py-5" style={{ color: colors.cyan, fontFamily: "var(--font-mono)" }}>
            Running {method} simulation with {nPaths} paths × {simDays} days…
          </div>
        )}

        {stressResult && (
          <>
            <StatRow>
              <StatCard label="VaR 95%" value={fmtDollar(stressResult.var_95)} color={colors.red} />
              <StatCard label="VaR 99%" value={fmtDollar(stressResult.var_99)} color={colors.red} />
              <StatCard label="CVaR 95%" value={fmtDollar(stressResult.cvar_95)} color={colors.red} />
              <StatCard label="CVaR 99%" value={fmtDollar(stressResult.cvar_99)} color={colors.red} />
              <StatCard label="MEDIAN FINAL" value={fmtDollar(stressResult.median_final)} color={pnlColor(stressResult.median_final - initialCapital)} />
              <StatCard label="P(RUIN)" value={`${(stressResult.prob_ruin * 100).toFixed(1)}%`} color={stressResult.prob_ruin > 0.05 ? colors.red : colors.green} />
            </StatRow>
            <ChartCard title={`EQUITY FAN CHART — ${stressResult.n_paths} paths × ${stressResult.n_days}d (${stressResult.method})`}>
              <FanChartSVG bands={stressResult.bands} />
            </ChartCard>
            {finalValues.length > 0 && (
              <ChartCard title="TERMINAL EQUITY PERCENTILES">
                <div className="flex items-end gap-4 px-6 pt-4 pb-3" style={{ height: 160 }}>
                  {(["p5", "p25", "p50", "p75", "p95"] as const).map((k) => {
                    const val = stressResult.bands[k][stressResult.bands[k].length - 1];
                    const max = stressResult.bands.p95[stressResult.bands.p95.length - 1];
                    const min = stressResult.bands.p5[stressResult.bands.p5.length - 1];
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

      {/* ======== SECTION 2: 5-LAYER RISK REPORT ======== */}
      <div>
        <div className="text-xs font-bold mb-3" style={{ color: colors.muted, fontFamily: "var(--font-mono)" }}>
          SECTION 2: 5-LAYER RISK EVALUATION REPORT
        </div>
        <div className="flex items-center gap-3 mb-3 flex-wrap">
          <button
            onClick={handleGenerateReport}
            disabled={riskRunning || !strategy}
            className="py-1.5 px-5 rounded text-[11px] font-semibold cursor-pointer border-none text-white"
            style={{ background: "#2A5A9A", fontFamily: "var(--font-mono)", opacity: riskRunning ? 0.5 : 1 }}
          >
            {riskRunning ? "Generating…" : "Generate Risk Report"}
          </button>
        </div>

        {riskError && (
          <div className="rounded-[5px] p-3 mb-2.5 text-[11px]" style={{ border: `1px solid ${colors.red}`, color: colors.red, fontFamily: "var(--font-mono)" }}>
            {riskError}
          </div>
        )}

        {!riskResult && !riskRunning && !riskError && (
          <div className="text-[11px] py-5" style={{ color: colors.muted, fontFamily: "var(--font-mono)" }}>
            Click "Generate Risk Report" to run comprehensive 5-layer risk evaluation:<br />
            L1: Cost Model | L2: Parameter Sensitivity | L3: Regime MC | L4: Adversarial | L5: Walk-Forward
          </div>
        )}

        {riskRunning && (
          <div className="text-[11px] py-5" style={{ color: colors.cyan, fontFamily: "var(--font-mono)" }}>
            Generating risk report with all 5 evaluation layers…
          </div>
        )}

        {riskResult && (
          <>
            <div
              className="rounded-[5px] p-4 mb-3 text-center border-2"
              style={{
                borderColor: recommendationColors[riskResult.recommendation],
                background: `${recommendationColors[riskResult.recommendation]}15`,
              }}
            >
              <div className="text-[12px] font-bold" style={{ color: recommendationColors[riskResult.recommendation], fontFamily: "var(--font-mono)" }}>
                RECOMMENDATION: {riskResult.recommendation.toUpperCase()}
              </div>
              {riskResult.failure_reasons.length > 0 && (
                <div className="text-[11px] mt-2" style={{ color: colors.dim, fontFamily: "var(--font-mono)" }}>
                  {riskResult.failure_reasons.join(" • ")}
                </div>
              )}
            </div>

            <StatRow>
              <StatCard label="COST DRAG" value={`${riskResult.cost_gate.cost_drag_pct.toFixed(1)}%`} color={riskResult.cost_gate.passed ? colors.green : colors.red} />
              <StatCard label="NET SHARPE" value={riskResult.cost_gate.net_sharpe.toFixed(2)} color={riskResult.cost_gate.passed ? colors.green : colors.red} />
              <StatCard label="OOS SHARPE" value={(riskResult.walk_forward_gate.aggregate_oos_sharpe ?? 0).toFixed(2)} color={riskResult.walk_forward_gate.passed ? colors.green : colors.red} />
              <StatCard label="OVERFIT FLAG" value={riskResult.walk_forward_gate.overfit_flag ?? "N/A"} color={riskResult.walk_forward_gate.passed ? colors.green : colors.red} />
            </StatRow>

            <ChartCard title="EVALUATION GATES">
              <div className="p-4">
                <GateCard
                  title="L1: COST MODEL"
                  passed={riskResult.cost_gate.passed}
                  details={
                    <>
                      Net Sharpe: {riskResult.cost_gate.net_sharpe.toFixed(2)} | Cost drag: {riskResult.cost_gate.cost_drag_pct.toFixed(2)}%
                    </>
                  }
                />

                <GateCard
                  title="L2: PARAMETER SENSITIVITY"
                  passed={riskResult.param_stability_gate.passed}
                  details={
                    <>
                      Robust: {riskResult.param_stability_gate.robust ? "Yes" : "No"} | Overfit risk: {riskResult.param_stability_gate.likely_overfit ? "High" : "Low"}
                    </>
                  }
                />

                <GateCard
                  title="L3: REGIME-CONDITIONED MC"
                  passed={riskResult.regime_gate.passed}
                  details={
                    <>
                      Worst regime Sharpe: {riskResult.regime_gate.worst_regime_sharpe.toFixed(2)} | Regimes analyzed: {riskResult.regime_gate.regime_metrics?.length || 0}
                    </>
                  }
                />

                <GateCard
                  title="L4: ADVERSARIAL INJECTION"
                  passed={riskResult.adversarial_gate.passed}
                  details={
                    <>
                      Worst case equity: ${((riskResult.adversarial_gate.worst_case_terminal_equity ?? 0) / 1e6).toFixed(2)}M | Impact: {((riskResult.adversarial_gate.median_impact_pct ?? 0)).toFixed(2)}%
                    </>
                  }
                />

                <GateCard
                  title="L5: WALK-FORWARD OOS VALIDATION"
                  passed={riskResult.walk_forward_gate.passed}
                  details={
                    <>
                      OOS Sharpe: {(riskResult.walk_forward_gate.aggregate_oos_sharpe ?? 0).toFixed(2)} | Overfit flag: {riskResult.walk_forward_gate.overfit_flag ?? "N/A"}
                    </>
                  }
                />
              </div>
            </ChartCard>

            {riskResult.regime_gate.regime_metrics && riskResult.regime_gate.regime_metrics.length > 0 && (
              <ChartCard title="REGIME METRICS">
                <div className="p-4 overflow-x-auto">
                  <table className="w-full text-[11px]" style={{ fontFamily: "var(--font-mono)" }}>
                    <thead>
                      <tr style={{ borderBottomColor: colors.cardBorder }}>
                        <th className="text-left p-1" style={{ color: colors.dim }}>Regime</th>
                        <th className="text-right p-1" style={{ color: colors.dim }}>Sharpe</th>
                        <th className="text-right p-1" style={{ color: colors.dim }}>MDD</th>
                        <th className="text-right p-1" style={{ color: colors.dim }}>Win Rate</th>
                        <th className="text-right p-1" style={{ color: colors.dim }}>Sessions</th>
                      </tr>
                    </thead>
                    <tbody>
                      {riskResult.regime_gate.regime_metrics.map((m) => (
                        <tr key={m.label} style={{ borderBottomColor: colors.cardBorder, borderBottom: `1px solid ${colors.cardBorder}` }}>
                          <td className="text-left p-1" style={{ color: colors.text }}>{m.label}</td>
                          <td className="text-right p-1" style={{ color: m.sharpe > 0 ? colors.green : colors.red }}>{m.sharpe.toFixed(2)}</td>
                          <td className="text-right p-1" style={{ color: colors.dim }}>{m.mdd_pct.toFixed(1)}%</td>
                          <td className="text-right p-1" style={{ color: colors.dim }}>{(m.win_rate * 100).toFixed(0)}%</td>
                          <td className="text-right p-1" style={{ color: colors.dim }}>{m.n_sessions}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </ChartCard>
            )}

            <div className="text-[11px] p-3 mt-3" style={{ color: colors.muted, fontFamily: "var(--font-mono)" }}>
              Generated: {new Date(riskResult.generated_at).toLocaleString()} | Instrument: {riskResult.instrument}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
