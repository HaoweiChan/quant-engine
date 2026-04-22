import { useEffect, useMemo, useRef, useState } from "react";
import { EquityCurveChart, type EquityCurveChartHandle } from "@/components/charts/EquityCurveChart";
import { colors } from "@/lib/theme";
import type { WarRoomSession } from "@/lib/api";

interface EquityMetrics {
  totalReturn: number;
  sharpe: number;
  maxDrawdownPct: number;
  nDays: number;
}

function toDayKey(ts: number): string {
  const d = new Date(ts < 1e12 ? ts * 1000 : ts);
  return `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`;
}

function computeEquityMetrics(curve: number[], timestamps?: number[]): EquityMetrics | null {
  if (curve.length < 2) return null;
  const first = curve[0];
  const last = curve[curve.length - 1];
  if (first <= 0) return null;
  const totalReturn = (last - first) / first;
  let peak = first;
  let maxDd = 0;
  for (const v of curve) {
    if (v > peak) peak = v;
    const dd = (peak - v) / peak;
    if (dd > maxDd) maxDd = dd;
  }
  // Aggregate to daily returns for correct Sharpe annualization
  const dailyReturns: number[] = [];
  if (timestamps && timestamps.length === curve.length) {
    let prevDay = toDayKey(timestamps[0]);
    let dayStart = curve[0];
    for (let i = 1; i < curve.length; i++) {
      const day = toDayKey(timestamps[i]);
      if (day !== prevDay && dayStart > 0) {
        dailyReturns.push((curve[i - 1] - dayStart) / dayStart);
        dayStart = curve[i - 1];
        prevDay = day;
      }
    }
    if (dayStart > 0) dailyReturns.push((last - dayStart) / dayStart);
  } else {
    for (let i = 1; i < curve.length; i++) {
      if (curve[i - 1] > 0) dailyReturns.push((curve[i] - curve[i - 1]) / curve[i - 1]);
    }
  }
  const n = dailyReturns.length;
  if (n === 0) return null;
  const mean = dailyReturns.reduce((a, b) => a + b, 0) / n;
  const variance = dailyReturns.reduce((a, r) => a + (r - mean) ** 2, 0) / n;
  const std = Math.sqrt(variance);
  const sharpe = std > 1e-12 ? (mean / std) * Math.sqrt(252) : 0;
  return { totalReturn, sharpe, maxDrawdownPct: maxDd, nDays: n };
}

interface EquityPanelProps {
  equityCurve: number[];
  equityTimestamps?: number[];
  sessions: WarRoomSession[];
  accountLabel: string;
  visibleRange?: { fromTs: string; toTs: string } | null;
  playbackActive?: boolean;
}

export function EquityPanel({ equityCurve, equityTimestamps, sessions: _sessions, accountLabel: _accountLabel, visibleRange, playbackActive }: EquityPanelProps) {
  void _accountLabel;
  void _sessions;
  const chartRef = useRef<EquityCurveChartHandle>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const [chartHeight, setChartHeight] = useState(120);
  const metrics = useMemo(() => computeEquityMetrics(equityCurve, equityTimestamps), [equityCurve, equityTimestamps]);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const ro = new ResizeObserver(() => {
      const h = el.clientHeight;
      if (h > 0) setChartHeight(h);
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  return (
    <div className="h-full flex flex-col rounded" style={{ background: colors.card, border: `1px solid ${colors.cardBorder}` }}>
      <div className="text-[11px] px-2 py-1.5 border-b shrink-0 flex items-center justify-between" style={{ borderColor: colors.cardBorder, fontFamily: "var(--font-mono)" }}>
        <div className="flex items-center gap-3">
          <span style={{ color: colors.muted }}>EQUITY</span>
          {metrics && (
            <div className="flex items-center gap-2 text-[11px]">
              <span style={{ color: colors.text, fontWeight: 700 }}>
                {metrics.nDays}d
              </span>
              <span style={{ color: colors.dim }}>|</span>
              <span style={{ color: metrics.totalReturn >= 0 ? colors.green : colors.red }}>
                {metrics.totalReturn >= 0 ? "+" : ""}{(metrics.totalReturn * 100).toFixed(1)}%
              </span>
              <span style={{ color: colors.dim }}>|</span>
              <span style={{ color: metrics.sharpe >= 1 ? colors.green : metrics.sharpe >= 0.5 ? colors.orange : colors.red }}>
                SR {metrics.sharpe.toFixed(2)}
              </span>
              <span style={{ color: colors.dim }}>|</span>
              <span style={{ color: metrics.maxDrawdownPct > 0.2 ? colors.red : metrics.maxDrawdownPct > 0.1 ? colors.orange : colors.green }}>
                MDD {(metrics.maxDrawdownPct * 100).toFixed(1)}%
              </span>
            </div>
          )}
        </div>
        <button
          onClick={() => chartRef.current?.fitContent()}
          className="p-1 rounded cursor-pointer border-none flex items-center justify-center"
          style={{ background: "rgba(90,138,242,0.12)", color: colors.text }}
          title="Fit to view"
        >
          <svg viewBox="0 0 16 16" width="12" height="12" fill="none" stroke="currentColor" strokeWidth="1.5">
            <path d="M2 5V2h3M11 2h3v3M14 11v3h-3M5 14H2v-3" />
          </svg>
        </button>
      </div>
      <div className="flex-1 min-h-0">
        <div ref={containerRef} className="h-full">
          {equityCurve.length > 0 ? (
            <EquityCurveChart
              ref={chartRef}
              equity={equityCurve}
              timestamps={equityTimestamps}
              height={chartHeight}
              visibleRange={visibleRange}
              playbackActive={playbackActive}
            />
          ) : (
            <div className="text-[11px] py-4 text-center" style={{ color: colors.dim, fontFamily: "var(--font-mono)" }}>
              No equity data yet.
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
