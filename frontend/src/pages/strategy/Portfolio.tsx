import React, { useCallback, useEffect, useMemo, useState } from "react";
import { ChartCard } from "@/components/ChartCard";
import { useStrategyStore } from "@/stores/strategyStore";
import { fetchSavedPortfolios, runPortfolioBacktest, runPortfolioStress } from "@/lib/api";
import type { MCSimulationResult, PortfolioBacktestResult, PortfolioStrategyEntry, SavedPortfolio } from "@/lib/api";
import { colors, pnlColor } from "@/lib/theme";


interface StrategySlot {
  slug: string;
  weight: number;
}

const METRIC_ROWS: { key: string; label: string; fmt: (v: number) => string }[] = [
  { key: "total_return", label: "Total Return", fmt: (v) => `${(v * 100).toFixed(2)}%` },
  { key: "sharpe", label: "Sharpe", fmt: (v) => v.toFixed(3) },
  { key: "sortino", label: "Sortino", fmt: (v) => v.toFixed(3) },
  { key: "max_drawdown_pct", label: "Max Drawdown", fmt: (v) => `${(v * 100).toFixed(2)}%` },
  { key: "calmar", label: "Calmar", fmt: (v) => v.toFixed(3) },
  { key: "annual_vol", label: "Annual Vol", fmt: (v) => `${(v * 100).toFixed(2)}%` },
  { key: "annual_return", label: "Annual Return", fmt: (v) => `${(v * 100).toFixed(2)}%` },
  { key: "n_days", label: "Trading Days", fmt: (v) => String(Math.round(v)) },
];

const STRATEGY_COLORS = [colors.blue, colors.orange, colors.purple];

const SVG_W = 700;
const SVG_H = 300;
const PAD = { top: 12, bottom: 22, left: 65, right: 12 };

function downsample(arr: number[], maxPts: number): number[] {
  if (arr.length <= maxPts) return arr;
  const step = arr.length / maxPts;
  const out: number[] = [];
  for (let i = 0; i < maxPts; i++) {
    out.push(arr[Math.round(i * step)]);
  }
  if (out[out.length - 1] !== arr[arr.length - 1]) out.push(arr[arr.length - 1]);
  return out;
}

function safeMinMax(arr: number[]): [number, number] {
  let lo = Infinity;
  let hi = -Infinity;
  for (const v of arr) {
    if (v < lo) lo = v;
    if (v > hi) hi = v;
  }
  return [isFinite(lo) ? lo : 0, isFinite(hi) ? hi : 1];
}

const EquityChart = React.memo(function EquityChart({
  result,
}: {
  result: PortfolioBacktestResult;
}) {
  const maxPts = 400;
  const merged = useMemo(() => downsample(result.merged_equity_curve, maxPts), [result.merged_equity_curve]);
  const individuals = useMemo(
    () => result.individual.map((s) => ({ slug: s.slug, data: downsample(s.equity_curve, maxPts) })),
    [result.individual],
  );

  const { yMin, yMax, ticks, fmtY } = useMemo(() => {
    const all = [...merged];
    for (const s of individuals) all.push(...s.data);
    let [lo, hi] = safeMinMax(all);
    const pad = (hi - lo) * 0.05 || 1;
    lo -= pad;
    hi += pad;
    const range = hi - lo;
    const rawStep = range / 5;
    const mag = Math.pow(10, Math.floor(Math.log10(rawStep)));
    const niceSteps = [1, 2, 2.5, 5, 10];
    const step = mag * (niceSteps.find((s) => s * mag >= rawStep) ?? 10);
    const arr: number[] = [];
    let t = Math.ceil(lo / step) * step;
    while (t <= hi) { arr.push(t); t += step; }
    const fmtY = (v: number): string => {
      if (Math.abs(v) >= 1e6) return `${(v / 1e6).toFixed(range < 5e5 ? 2 : range < 5e6 ? 1 : 0)}M`;
      if (Math.abs(v) >= 1e3) return `${(v / 1e3).toFixed(range < 5e3 ? 1 : 0)}K`;
      return v.toFixed(0);
    };
    return { yMin: lo, yMax: hi, ticks: arr, fmtY };
  }, [merged, individuals]);

  const xScale = (i: number, len: number) => PAD.left + (i / Math.max(len - 1, 1)) * (SVG_W - PAD.left - PAD.right);
  const yScale = (v: number) => PAD.top + (1 - (v - yMin) / (yMax - yMin || 1)) * (SVG_H - PAD.top - PAD.bottom);

  const toPath = (data: number[]) =>
    data.map((v, i) => `${i === 0 ? "M" : "L"}${xScale(i, data.length).toFixed(1)},${yScale(v).toFixed(1)}`).join(" ");

  return (
    <div>
      <div className="flex items-center gap-3 px-2 pb-2" style={{ fontFamily: "var(--font-mono)" }}>
        {individuals.map((s, idx) => (
          <div key={s.slug} className="flex items-center gap-1 text-[11px]">
            <span style={{ display: "inline-block", width: 8, height: 8, borderRadius: 2, background: STRATEGY_COLORS[idx] || colors.dim, opacity: 0.7 }} />
            <span style={{ color: colors.muted }}>{s.slug.split("/").pop()}</span>
          </div>
        ))}
        <div className="flex items-center gap-1 text-[11px]">
          <span style={{ display: "inline-block", width: 8, height: 8, borderRadius: 2, background: colors.cyan }} />
          <span style={{ color: colors.text, fontWeight: 600 }}>Portfolio</span>
        </div>
      </div>
      <svg viewBox={`0 0 ${SVG_W} ${SVG_H}`} style={{ width: "100%", height: "auto" }}>
        {ticks.map((t) => (
          <g key={t}>
            <line x1={PAD.left} x2={SVG_W - PAD.right} y1={yScale(t)} y2={yScale(t)} stroke="rgba(255,255,255,0.05)" />
            <text x={PAD.left - 4} y={yScale(t) + 3} textAnchor="end" fill={colors.dim} fontSize={8} fontFamily="var(--font-mono)">{fmtY(t)}</text>
          </g>
        ))}
        {individuals.map((s, idx) => (
          <path key={s.slug} d={toPath(s.data)} fill="none" stroke={STRATEGY_COLORS[idx] || colors.dim} strokeWidth={1} opacity={0.35} />
        ))}
        <path d={toPath(merged)} fill="none" stroke={colors.cyan} strokeWidth={2} />
      </svg>
    </div>
  );
});

function MetricsTable({ result }: { result: PortfolioBacktestResult }) {
  const strategyNames = result.individual.map((s) => s.slug);
  const isBetter = (key: string, pVal: number, iVals: number[]) => {
    const higherIsBetter = ["total_return", "sharpe", "sortino", "calmar", "annual_return"];
    if (higherIsBetter.includes(key)) return iVals.every((v) => pVal > v);
    const lowerIsBetter = ["max_drawdown_pct", "annual_vol"];
    if (lowerIsBetter.includes(key)) return iVals.every((v) => pVal < v);
    return false;
  };
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-[11px]" style={{ fontFamily: "var(--font-mono)" }}>
        <thead>
          <tr style={{ color: colors.muted, borderBottom: `1px solid ${colors.cardBorder}` }}>
            <th className="text-left py-1.5 px-2 font-normal">Metric</th>
            {strategyNames.map((n) => (
              <th key={n} className="text-right py-1.5 px-2 font-normal">{n}</th>
            ))}
            <th className="text-right py-1.5 px-2 font-bold" style={{ color: colors.cyan }}>Portfolio</th>
          </tr>
        </thead>
        <tbody>
          {METRIC_ROWS.map((row) => {
            const pVal = result.merged_metrics[row.key] ?? 0;
            const iVals = result.individual.map((s) => s.metrics[row.key] ?? 0);
            const highlight = isBetter(row.key, pVal, iVals);
            return (
              <tr key={row.key} style={{ borderBottom: `1px solid ${colors.cardBorder}22` }}>
                <td className="py-1 px-2" style={{ color: colors.muted }}>{row.label}</td>
                {iVals.map((v, idx) => (
                  <td key={idx} className="text-right py-1 px-2" style={{ color: colors.text }}>{row.fmt(v)}</td>
                ))}
                <td
                  className="text-right py-1 px-2 font-bold"
                  style={{ color: highlight ? colors.green : colors.text, background: highlight ? `${colors.green}10` : undefined }}
                >
                  {row.fmt(pVal)}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function CorrelationMatrix({ matrix, slugs }: { matrix: number[][]; slugs: string[] }) {
  const cellColor = (v: number) => {
    if (v >= 0.7) return colors.red;
    if (v >= 0.3) return colors.orange;
    if (v >= -0.3) return colors.green;
    return colors.blue;
  };
  return (
    <div className="flex flex-col items-start">
      <table className="text-[11px]" style={{ fontFamily: "var(--font-mono)" }}>
        <thead>
          <tr>
            <th />
            {slugs.map((s) => (
              <th key={s} className="px-3 py-1 font-normal text-center" style={{ color: colors.muted }}>{s}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {matrix.map((row, ri) => (
            <tr key={ri}>
              <td className="px-2 py-1 text-right" style={{ color: colors.muted }}>{slugs[ri]}</td>
              {row.map((v, ci) => (
                <td
                  key={ci}
                  className="px-3 py-1 text-center font-bold"
                  style={{ color: cellColor(v), background: `${cellColor(v)}10` }}
                >
                  {v.toFixed(3)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      <div className="flex gap-3 mt-2 text-[11px]" style={{ color: colors.dim }}>
        <span><span style={{ color: colors.red }}>■</span> High (≥0.7)</span>
        <span><span style={{ color: colors.orange }}>■</span> Moderate</span>
        <span><span style={{ color: colors.green }}>■</span> Low (±0.3)</span>
        <span><span style={{ color: colors.blue }}>■</span> Negative</span>
      </div>
    </div>
  );
}

// Reuse the fan chart from StressTest
const FanChartMini = React.memo(function FanChartMini({ bands }: { bands: MCSimulationResult["bands"] }) {
  const len = bands.p50.length;
  const { yMin, yMax, ticks, fmtY } = useMemo(() => {
    const [lo5, _] = safeMinMax(bands.p5);
    const [__, hi95] = safeMinMax(bands.p95);
    let lo = lo5;
    let hi = hi95;
    const pad = (hi - lo) * 0.05 || 1;
    lo -= pad;
    hi += pad;
    const range = hi - lo;
    const rawStep = range / 5;
    const mag = Math.pow(10, Math.floor(Math.log10(rawStep)));
    const niceSteps = [1, 2, 2.5, 5, 10];
    const step = mag * (niceSteps.find((s) => s * mag >= rawStep) ?? 10);
    const arr: number[] = [];
    let t = Math.ceil(lo / step) * step;
    while (t <= hi) { arr.push(t); t += step; }
    const fmtY = (v: number): string => {
      if (Math.abs(v) >= 1e6) return `${(v / 1e6).toFixed(range < 5e5 ? 2 : range < 5e6 ? 1 : 0)}M`;
      if (Math.abs(v) >= 1e3) return `${(v / 1e3).toFixed(range < 5e3 ? 1 : 0)}K`;
      return v.toFixed(0);
    };
    return { yMin: lo, yMax: hi, ticks: arr, fmtY };
  }, [bands]);

  const xScale = (i: number) => PAD.left + (i / Math.max(len - 1, 1)) * (SVG_W - PAD.left - PAD.right);
  const yScale = (v: number) => PAD.top + (1 - (v - yMin) / (yMax - yMin || 1)) * (SVG_H - PAD.top - PAD.bottom);

  const bandArea = (upper: number[], lower: number[]) => {
    const fwd = upper.map((_, i) => `${xScale(i).toFixed(1)},${yScale(upper[i]).toFixed(1)}`).join(" ");
    const bwd = [...lower].reverse().map((_, i) => `${xScale(len - 1 - i).toFixed(1)},${yScale(lower[len - 1 - i]).toFixed(1)}`).join(" ");
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
        points={bands.p50.map((v, i) => `${xScale(i).toFixed(1)},${yScale(v).toFixed(1)}`).join(" ")}
      />
    </svg>
  );
});

export function Portfolio() {
  const strategies = useStrategyStore((s) => s.strategies);
  const storeSymbol = useStrategyStore((s) => s.symbol);
  const storeStart = useStrategyStore((s) => s.startDate);
  const storeEnd = useStrategyStore((s) => s.endDate);
  const storeCapital = useStrategyStore((s) => s.initialCapital);
  const storeSlippage = useStrategyStore((s) => s.slippageBps);
  const storeCommission = useStrategyStore((s) => s.commissionBps);
  const storeCommissionFixed = useStrategyStore((s) => s.commissionFixed);
  const setSymbol = useStrategyStore((s) => s.setSymbol);
  const setDates = useStrategyStore((s) => s.setDates);

  const [slots, setSlots] = useState<StrategySlot[]>([
    { slug: "", weight: 50 },
    { slug: "", weight: 50 },
  ]);
  const [btResult, setBtResult] = useState<PortfolioBacktestResult | null>(null);
  const [stressResult, setStressResult] = useState<MCSimulationResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [stressLoading, setStressLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [savedPortfolios, setSavedPortfolios] = useState<SavedPortfolio[]>([]);

  useEffect(() => {
    fetchSavedPortfolios().then((res) => {
      if (res.portfolios?.length) setSavedPortfolios(res.portfolios);
    });
  }, []);

  const runBacktestWith = useCallback(async (
    slotsToRun: StrategySlot[],
    symbol: string,
    start: string,
    end: string,
  ) => {
    setLoading(true);
    setError(null);
    setBtResult(null);
    setStressResult(null);
    const entries: PortfolioStrategyEntry[] = slotsToRun
      .filter((s) => s.slug)
      .map((s) => ({ slug: s.slug, weight: s.weight / 100 }));
    try {
      const res = await runPortfolioBacktest({
        strategies: entries,
        symbol,
        start,
        end,
        initial_capital: storeCapital,
        slippage_bps: storeSlippage,
        commission_bps: storeCommission,
        commission_fixed_per_contract: storeCommissionFixed,
      });
      setBtResult(res);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [storeCapital, storeSlippage, storeCommission, storeCommissionFixed]);

  const handleLoadSaved = useCallback((portfolio: SavedPortfolio) => {
    const entries = Object.entries(portfolio.weights);
    const newSlots = entries.map(([slug, w]) => ({ slug, weight: Math.round(w * 100) }));
    setSlots(newSlots);
    setSymbol(portfolio.symbol);
    setDates(portfolio.start_date, portfolio.end_date);
    runBacktestWith(newSlots, portfolio.symbol, portfolio.start_date, portfolio.end_date);
  }, [setSymbol, setDates, runBacktestWith]);

  const hasDuplicates = useMemo(() => {
    const slugs = slots.filter((s) => s.slug).map((s) => s.slug);
    return new Set(slugs).size !== slugs.length;
  }, [slots]);

  const canMerge = slots.filter((s) => s.slug).length >= 2 && !hasDuplicates && !loading;

  const updateSlot = (idx: number, patch: Partial<StrategySlot>) => {
    setSlots((prev) => prev.map((s, i) => (i === idx ? { ...s, ...patch } : s)));
  };

  const addSlot = () => {
    if (slots.length >= 3) return;
    const newWeight = Math.round(100 / (slots.length + 1));
    setSlots((prev) => [...prev.map((s) => ({ ...s, weight: newWeight })), { slug: "", weight: newWeight }]);
  };

  const removeSlot = (idx: number) => {
    if (slots.length <= 2) return;
    const next = slots.filter((_, i) => i !== idx);
    const w = Math.round(100 / next.length);
    setSlots(next.map((s) => ({ ...s, weight: w })));
  };

  const handleMerge = () => {
    runBacktestWith(slots, storeSymbol, storeStart, storeEnd);
  };

  const handleStress = async () => {
    if (!btResult) return;
    setStressLoading(true);
    const entries: PortfolioStrategyEntry[] = slots
      .filter((s) => s.slug)
      .map((s) => ({ slug: s.slug, weight: s.weight / 100 }));
    try {
      const res = await runPortfolioStress({
        strategies: entries,
        symbol: storeSymbol,
        start: storeStart,
        end: storeEnd,
        initial_capital: storeCapital,
        slippage_bps: storeSlippage,
        commission_bps: storeCommission,
        commission_fixed_per_contract: storeCommissionFixed,
      });
      setStressResult(res);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setStressLoading(false);
    }
  };

  const fmtMoney = (v: number) => {
    if (Math.abs(v) >= 1e6) return `${(v / 1e6).toFixed(2)}M`;
    if (Math.abs(v) >= 1e3) return `${(v / 1e3).toFixed(1)}K`;
    return v.toFixed(0);
  };

  return (
    <div className="p-4 space-y-4" style={{ fontFamily: "var(--font-mono)" }}>
      {/* Load Saved Portfolio */}
      {savedPortfolios.length > 0 && (
        <ChartCard title="SAVED PORTFOLIOS">
          <div className="flex flex-wrap gap-2">
            {savedPortfolios.map((p) => {
              const shortSlugs = Object.entries(p.weights)
                .map(([s, w]) => `${s.split("/").pop()} ${Math.round(w * 100)}%`)
                .join(" · ");
              return (
                <button
                  key={p.id}
                  onClick={() => handleLoadSaved(p)}
                  disabled={loading}
                  className="flex flex-col items-start rounded px-3 py-2 text-left transition-colors"
                  style={{
                    background: colors.card,
                    border: `1px solid ${colors.cardBorder}`,
                    cursor: loading ? "not-allowed" : "pointer",
                    minWidth: 180,
                  }}
                >
                  <div className="flex items-center gap-2">
                    <span className="text-[11px] font-bold" style={{ color: colors.text }}>
                      {p.objective.replace("_", " ")}
                    </span>
                    <span className="text-[11px] px-1.5 py-0.5 rounded" style={{ background: `${colors.blue}20`, color: colors.blue }}>
                      {p.symbol}
                    </span>
                    {p.is_selected && (
                      <span className="text-[11px] px-1.5 py-0.5 rounded" style={{ background: `${colors.green}20`, color: colors.green }}>
                        active
                      </span>
                    )}
                  </div>
                  <span className="text-[11px] mt-1" style={{ color: colors.muted }}>{shortSlugs}</span>
                  <div className="flex gap-3 mt-1 text-[11px]" style={{ color: colors.dim }}>
                    {p.sharpe != null && <span>Sharpe {p.sharpe.toFixed(2)}</span>}
                    {p.max_drawdown_pct != null && <span>MDD {(p.max_drawdown_pct * 100).toFixed(1)}%</span>}
                    {p.total_return != null && <span>Ret {(p.total_return * 100).toFixed(1)}%</span>}
                  </div>
                  <span className="text-[11px] mt-0.5" style={{ color: colors.dim }}>
                    {p.start_date} → {p.end_date}
                  </span>
                </button>
              );
            })}
          </div>
        </ChartCard>
      )}

      {/* Strategy Selection */}
      <ChartCard title="PORTFOLIO STRATEGY SELECTION">
        <div className="space-y-2">
          {slots.map((slot, idx) => (
            <div key={idx} className="flex items-center gap-3">
              <span className="text-[11px] w-20" style={{ color: colors.muted }}>
                Strategy {String.fromCharCode(65 + idx)}
              </span>
              <select
                value={slot.slug}
                onChange={(e) => updateSlot(idx, { slug: e.target.value })}
                className="flex-1 rounded px-2 py-1.5 text-[11px]"
                style={{
                  background: colors.input,
                  color: colors.text,
                  border: `1px solid ${colors.inputBorder}`,
                  fontFamily: "var(--font-mono)",
                }}
              >
                <option value="">-- select --</option>
                {strategies.map((s) => (
                  <option key={s.slug} value={s.slug}>{s.name}</option>
                ))}
              </select>
              <div className="flex items-center gap-1">
                <span className="text-[11px]" style={{ color: colors.dim }}>Weight</span>
                <input
                  type="number"
                  min={1}
                  max={99}
                  value={slot.weight}
                  onChange={(e) => updateSlot(idx, { weight: Number(e.target.value) })}
                  className="w-14 rounded px-1.5 py-1 text-[11px] text-center"
                  style={{
                    background: colors.input,
                    color: colors.text,
                    border: `1px solid ${colors.inputBorder}`,
                    fontFamily: "var(--font-mono)",
                  }}
                />
                <span className="text-[11px]" style={{ color: colors.dim }}>%</span>
              </div>
              {slots.length > 2 && (
                <button
                  onClick={() => removeSlot(idx)}
                  className="text-[11px] px-1.5 py-0.5 rounded"
                  style={{ color: colors.red, border: `1px solid ${colors.red}44` }}
                >
                  ✕
                </button>
              )}
            </div>
          ))}
          <div className="flex items-center gap-3 pt-1">
            {slots.length < 3 && (
              <button
                onClick={addSlot}
                className="text-[11px] px-3 py-1 rounded"
                style={{ color: colors.cyan, border: `1px solid ${colors.cyan}44` }}
              >
                + Add Strategy {String.fromCharCode(65 + slots.length)}
              </button>
            )}
            <button
              onClick={handleMerge}
              disabled={!canMerge}
              className="text-[11px] px-4 py-1.5 rounded font-bold ml-auto"
              style={{
                background: canMerge ? colors.blue : colors.cardBorder,
                color: canMerge ? "#fff" : colors.dim,
                opacity: canMerge ? 1 : 0.5,
                cursor: canMerge ? "pointer" : "not-allowed",
              }}
            >
              {loading ? "Merging…" : "Merge & Analyze"}
            </button>
          </div>
          {hasDuplicates && (
            <div className="text-[11px] mt-1" style={{ color: colors.red }}>
              Duplicate strategy selected — please choose different strategies
            </div>
          )}
        </div>
      </ChartCard>

      {error && (
        <div className="rounded px-3 py-2 text-[11px]" style={{ background: `${colors.red}15`, color: colors.red, border: `1px solid ${colors.red}33` }}>
          {error}
        </div>
      )}

      {/* Results */}
      {btResult && (
        <>
          {/* Equity Curve */}
          <ChartCard title="COMBINED EQUITY CURVE">
            <EquityChart result={btResult} />
          </ChartCard>

          {/* Metrics Table */}
          <ChartCard title="SIDE-BY-SIDE METRICS">
            <MetricsTable result={btResult} />
          </ChartCard>

          {/* Correlation Matrix */}
          <ChartCard title="RETURN CORRELATION MATRIX">
            <CorrelationMatrix matrix={btResult.correlation_matrix} slugs={btResult.strategy_slugs} />
          </ChartCard>

          {/* Stress Test */}
          <ChartCard title="PORTFOLIO STRESS TEST">
            <div className="flex items-center gap-3 mb-3">
              <button
                onClick={handleStress}
                disabled={stressLoading}
                className="text-[11px] px-4 py-1.5 rounded font-bold"
                style={{
                  background: stressLoading ? colors.cardBorder : colors.purple,
                  color: "#fff",
                  cursor: stressLoading ? "not-allowed" : "pointer",
                }}
              >
                {stressLoading ? "Running…" : "Run Portfolio Stress Test"}
              </button>
              <span className="text-[11px]" style={{ color: colors.dim }}>Monte Carlo on merged portfolio returns</span>
            </div>

            {stressResult && (
              <>
                <FanChartMini bands={stressResult.bands} />
                <div className="flex flex-wrap gap-2 mt-3">
                  {([
                    ["VaR 95%", stressResult.var_95],
                    ["CVaR 95%", stressResult.cvar_95],
                    ["VaR 99%", stressResult.var_99],
                    ["CVaR 99%", stressResult.cvar_99],
                    ["Median Final", stressResult.median_final],
                    ["P(Ruin)", stressResult.prob_ruin],
                  ] as const).map(([label, val]) => (
                    <div
                      key={label}
                      className="flex-1 min-w-[100px] rounded px-3 py-2"
                      style={{ background: colors.card, border: `1px solid ${colors.cardBorder}` }}
                    >
                      <div className="text-[11px] uppercase tracking-wide mb-0.5" style={{ color: colors.muted }}>{label}</div>
                      <div
                        className="text-[14px] font-bold"
                        style={{
                          color: label === "P(Ruin)"
                            ? val > 0.1 ? colors.red : colors.green
                            : pnlColor(val),
                          fontFamily: "var(--font-mono)",
                        }}
                      >
                        {label === "P(Ruin)" ? `${(val * 100).toFixed(2)}%` : fmtMoney(val)}
                      </div>
                    </div>
                  ))}
                </div>
              </>
            )}
          </ChartCard>
        </>
      )}
    </div>
  );
}
