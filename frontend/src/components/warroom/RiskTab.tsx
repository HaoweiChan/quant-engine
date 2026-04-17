import { useMemo } from "react";
import { ChartCard } from "@/components/ChartCard";
import { DrawdownChart } from "@/components/charts/DrawdownChart";
import { AccountStrip } from "@/components/warroom/AccountStrip";
import { useTradingStore } from "@/stores/tradingStore";
import { useRiskAlerts } from "@/hooks/useRiskAlerts";
import { colors } from "@/lib/theme";
import type { WarRoomData } from "@/lib/api";

interface RiskMetrics {
  totalReturn: number;
  annualReturn: number | null;
  annualVol: number | null;
  sharpe: number | null;
  sortino: number | null;
  calmar: number | null;
  maxDrawdown: number;
  mddDurationDays: number;
  currentDrawdown: number;
  equityRatio: number;
  nDays: number;
  winRate: number;
  profitFactor: number;
}

const MIN_DAYS_FOR_ANNUALIZATION = 30;

function computeRiskMetrics(
  equityCurve: { timestamp: string; equity: number }[],
  marginUsed: number,
  marginAvail: number,
): RiskMetrics {
  const empty: RiskMetrics = {
    totalReturn: 0, annualReturn: null, annualVol: null, sharpe: null, sortino: null,
    calmar: null, maxDrawdown: 0, mddDurationDays: 0, currentDrawdown: 0,
    equityRatio: 0, nDays: 0, winRate: 0, profitFactor: 0,
  };
  if (!equityCurve || equityCurve.length < 2) return empty;

  const dailyMap = new Map<string, { first: number; last: number }>();
  for (const pt of equityCurve) {
    const day = pt.timestamp.slice(0, 10);
    const entry = dailyMap.get(day);
    if (!entry) dailyMap.set(day, { first: pt.equity, last: pt.equity });
    else entry.last = pt.equity;
  }
  const days = Array.from(dailyMap.entries()).sort((a, b) => a[0].localeCompare(b[0]));
  const dailyReturns: number[] = [];
  for (let i = 1; i < days.length; i++) {
    const prev = days[i - 1][1].last;
    const curr = days[i][1].last;
    if (prev > 0) dailyReturns.push((curr - prev) / prev);
  }
  const nDays = days.length;
  if (dailyReturns.length === 0) return { ...empty, nDays };

  const startEq = equityCurve[0].equity;
  const endEq = equityCurve[equityCurve.length - 1].equity;
  const totalReturn = startEq > 0 ? endEq / startEq - 1 : 0;

  // Only annualize if we have enough data
  const canAnnualize = nDays >= MIN_DAYS_FOR_ANNUALIZATION;
  let annualReturn: number | null = null;
  let annualVol: number | null = null;
  let sharpe: number | null = null;
  let sortino: number | null = null;
  let calmar: number | null = null;

  const mean = dailyReturns.reduce((s, r) => s + r, 0) / dailyReturns.length;
  const variance = dailyReturns.reduce((s, r) => s + (r - mean) ** 2, 0) / dailyReturns.length;
  const stdDev = Math.sqrt(variance);

  if (canAnnualize) {
    const logReturn = startEq > 0 && endEq > 0 ? Math.log(endEq / startEq) : 0;
    const annLogReturn = logReturn * (252 / nDays);
    annualReturn = Math.exp(annLogReturn) - 1;
    annualVol = stdDev * Math.sqrt(252);

    if (annualVol > 0) sharpe = annualReturn / annualVol;
    const downsideReturns = dailyReturns.filter((r) => r < 0);
    const downsideVar = downsideReturns.length > 0
      ? downsideReturns.reduce((s, r) => s + r * r, 0) / downsideReturns.length
      : 0;
    const downsideDev = Math.sqrt(downsideVar) * Math.sqrt(252);
    if (downsideDev > 0) sortino = annualReturn / downsideDev;
  }

  // Drawdown (always computed regardless of period length)
  let peak = equityCurve[0].equity;
  let maxDD = 0;
  let longestDDDuration = 0;
  let currentDDDuration = 0;
  const equityValues = equityCurve.map((p) => p.equity);
  for (let i = 0; i < equityValues.length; i++) {
    if (equityValues[i] > peak) {
      peak = equityValues[i];
      if (currentDDDuration > longestDDDuration) longestDDDuration = currentDDDuration;
      currentDDDuration = 0;
    } else {
      currentDDDuration++;
    }
    const dd = (peak - equityValues[i]) / peak;
    if (dd > maxDD) maxDD = dd;
  }
  if (currentDDDuration > longestDDDuration) longestDDDuration = currentDDDuration;

  const lastEquity = equityValues[equityValues.length - 1];
  const currentDrawdown = peak > 0 ? (peak - lastEquity) / peak : 0;
  const barsPerDay = equityCurve.length / Math.max(1, nDays);
  const mddDurationDays = Math.round(longestDDDuration / Math.max(1, barsPerDay));
  if (canAnnualize && annualReturn != null && maxDD > 0) calmar = annualReturn / maxDD;

  const equityRatio = (marginUsed + marginAvail) > 0 ? marginUsed / (marginUsed + marginAvail) : 0;
  const wins = dailyReturns.filter((r) => r > 0);
  const losses = dailyReturns.filter((r) => r < 0);
  const winRate = dailyReturns.length > 0 ? wins.length / dailyReturns.length : 0;
  const grossProfit = wins.reduce((s, r) => s + r, 0);
  const grossLoss = Math.abs(losses.reduce((s, r) => s + r, 0));
  const profitFactor = grossLoss > 0 ? grossProfit / grossLoss : grossProfit > 0 ? 99.9 : 0;

  return {
    totalReturn, annualReturn, annualVol, sharpe, sortino, calmar,
    maxDrawdown: maxDD, mddDurationDays, currentDrawdown, equityRatio,
    nDays, winRate, profitFactor,
  };
}

function fmtNum(v: number | null, decimals = 2): string {
  if (v == null || !isFinite(v)) return "—";
  return v.toFixed(decimals);
}

function fmtPct(v: number | null): string {
  if (v == null || !isFinite(v)) return "—";
  const pct = v * 100;
  if (Math.abs(pct) >= 10000) return `${Math.round(pct / 1000)}k%`;
  if (Math.abs(pct) >= 1000) return `${(pct / 1000).toFixed(1)}k%`;
  return `${pct.toFixed(1)}%`;
}

function fmtDollar(v: number): string {
  return `$${Math.round(v).toLocaleString()}`;
}

function MetricCell({ label, value, color }: { label: string; value: string; color: string }) {
  return (
    <div className="flex-1 flex flex-col items-center px-2 py-2.5 rounded" style={{ background: colors.card, border: `1px solid ${colors.cardBorder}`, minWidth: 0 }}>
      <span className="text-[11px] tracking-wider mb-1" style={{ color: colors.dim, fontFamily: "var(--font-mono)" }}>{label}</span>
      <span className="text-[15px] font-bold truncate w-full text-center" style={{ color, fontFamily: "var(--font-mono)" }}>{value}</span>
    </div>
  );
}

export function RiskTab() {
  const riskAlerts = useTradingStore((s) => s.riskAlerts);
  const warRoomData = useTradingStore((s) => s.warRoomData) as WarRoomData | null;
  const activeAccountId = useTradingStore((s) => s.activeAccountId);
  useRiskAlerts();

  const accounts = warRoomData?.accounts ?? {};
  const activeAccount = activeAccountId ? accounts[activeAccountId] : null;
  const allSessions = warRoomData?.all_sessions ?? [];
  const acctSessions = allSessions.filter((s) => s.account_id === activeAccountId);

  const marginUsed = activeAccount?.margin_used ?? 0;
  const marginAvail = activeAccount?.margin_available ?? 0;
  const totalUnrealizedPnl = acctSessions.reduce((sum, s) => sum + (s.snapshot?.unrealized_pnl ?? 0), 0);

  const equityCurve = useMemo(() => activeAccount?.equity_curve ?? [], [activeAccount]);
  const metrics = useMemo(
    () => computeRiskMetrics(equityCurve, marginUsed, marginAvail),
    [equityCurve, marginUsed, marginAvail],
  );
  const equityValues = useMemo(() => equityCurve.map((p) => p.equity), [equityCurve]);

  const shortPeriod = metrics.nDays < MIN_DAYS_FOR_ANNUALIZATION;
  const sharpeColor = (v: number | null) => v == null ? colors.dim : v >= 1.5 ? colors.green : v >= 0.8 ? colors.gold : colors.red;
  const ddColor = (v: number) => v < 0.1 ? colors.green : v < 0.2 ? colors.gold : colors.red;

  return (
    <div className="flex flex-col flex-1" style={{ minWidth: 0 }}>
      <AccountStrip accounts={accounts as Record<string, any>} />
      <div className="flex-1 p-4 overflow-y-auto">
      {shortPeriod && metrics.nDays > 0 && (
        <div className="flex items-center gap-2 mb-3">
          <span className="text-[11px] px-2 py-0.5 rounded" style={{ background: "rgba(255,165,0,0.12)", color: colors.orange, fontFamily: "var(--font-mono)" }}>
            {metrics.nDays}d — annualized ratios require 30+ days
          </span>
        </div>
      )}

      {/* Row 1: Capital metrics */}
      <div className="flex gap-2 mb-2">
        <MetricCell label="TOTAL RETURN" value={fmtPct(metrics.totalReturn)} color={metrics.totalReturn >= 0 ? colors.green : colors.red} />
        <MetricCell label="ANNUAL RETURN" value={fmtPct(metrics.annualReturn)} color={metrics.annualReturn != null && metrics.annualReturn >= 0 ? colors.green : metrics.annualReturn != null ? colors.red : colors.dim} />
        <MetricCell label="ANNUAL VOL" value={fmtPct(metrics.annualVol)} color={metrics.annualVol != null && metrics.annualVol < 0.2 ? colors.green : colors.dim} />
        <MetricCell label="MARGIN USED" value={fmtDollar(marginUsed)} color={colors.muted} />
        <MetricCell label="UNREALIZED PNL" value={fmtDollar(totalUnrealizedPnl)} color={totalUnrealizedPnl >= 0 ? colors.green : colors.red} />
      </div>

      {/* Row 2: Risk ratios */}
      <div className="flex gap-2 mb-2">
        <MetricCell label="SHARPE" value={fmtNum(metrics.sharpe)} color={sharpeColor(metrics.sharpe)} />
        <MetricCell label="SORTINO" value={fmtNum(metrics.sortino)} color={sharpeColor(metrics.sortino)} />
        <MetricCell label="CALMAR" value={fmtNum(metrics.calmar)} color={metrics.calmar != null && metrics.calmar >= 1 ? colors.green : metrics.calmar != null ? colors.gold : colors.dim} />
        <MetricCell label="MAX DD" value={fmtPct(metrics.maxDrawdown)} color={ddColor(metrics.maxDrawdown)} />
        <MetricCell label="MDD DURATION" value={`${metrics.mddDurationDays}d`} color={metrics.mddDurationDays < 30 ? colors.green : metrics.mddDurationDays < 60 ? colors.gold : colors.red} />
      </div>

      {/* Row 3: Secondary */}
      <div className="flex gap-2 mb-4">
        <MetricCell label="CURRENT DD" value={fmtPct(metrics.currentDrawdown)} color={ddColor(metrics.currentDrawdown)} />
        <MetricCell label="EQUITY RATIO" value={fmtPct(metrics.equityRatio)} color={metrics.equityRatio < 0.6 ? colors.green : metrics.equityRatio < 0.8 ? colors.gold : colors.red} />
        <MetricCell label="TRADING DAYS" value={`${metrics.nDays}`} color={colors.text} />
        <MetricCell label="WIN RATE" value={fmtPct(metrics.winRate)} color={metrics.winRate >= 0.5 ? colors.green : metrics.winRate >= 0.35 ? colors.gold : colors.red} />
        <MetricCell label="PROFIT FACTOR" value={fmtNum(metrics.profitFactor)} color={metrics.profitFactor >= 1.5 ? colors.green : metrics.profitFactor >= 1.0 ? colors.gold : colors.red} />
      </div>

      {/* Equity & Drawdown chart */}
      {equityValues.length > 0 && (
        <ChartCard title="EQUITY & DRAWDOWN">
          <DrawdownChart equity={equityValues} height={220} />
        </ChartCard>
      )}

      {/* Per-session breakdown */}
      <ChartCard title="PER-STRATEGY BREAKDOWN">
        <table className="w-full text-[12px]" style={{ fontFamily: "var(--font-mono)" }}>
          <thead>
            <tr style={{ borderBottom: `1px solid ${colors.cardBorder}` }}>
              {["Strategy", "Symbol", "Status", "Unrealized PnL", "Drawdown %"].map((h) => (
                <th key={h} className="text-left py-1.5 px-2" style={{ color: colors.dim }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {acctSessions.length === 0 ? (
              <tr><td colSpan={5} className="py-3 px-2 text-center" style={{ color: colors.dim }}>No sessions for this account.</td></tr>
            ) : (
              acctSessions.map((s) => {
                const slug = s.strategy_slug.split("/").pop() ?? s.strategy_slug;
                const pnl = s.snapshot?.unrealized_pnl ?? 0;
                const dd = s.snapshot?.drawdown_pct ?? 0;
                return (
                  <tr key={s.session_id} style={{ borderBottom: `1px solid ${colors.cardBorder}` }}>
                    <td className="py-1.5 px-2 font-medium" style={{ color: colors.text }}>{slug}</td>
                    <td className="py-1.5 px-2" style={{ color: colors.muted }}>{s.symbol}</td>
                    <td className="py-1.5 px-2 font-semibold" style={{ color: s.status === "active" ? colors.green : s.status === "halted" ? colors.red : colors.gold }}>{s.status}</td>
                    <td className="py-1.5 px-2" style={{ color: pnl >= 0 ? colors.green : colors.red }}>{fmtDollar(pnl)}</td>
                    <td className="py-1.5 px-2" style={{ color: dd > 5 ? colors.red : colors.gold }}>{dd.toFixed(1)}%</td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </ChartCard>

      {/* Alert history */}
      <ChartCard title="ALERT HISTORY">
        <table className="w-full text-[12px]" style={{ fontFamily: "var(--font-mono)" }}>
          <thead>
            <tr style={{ borderBottom: `1px solid ${colors.cardBorder}` }}>
              {["Time", "Severity", "Trigger", "Details"].map((h) => (
                <th key={h} className="text-left py-1.5 px-2" style={{ color: colors.dim }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {riskAlerts.length === 0 ? (
              <tr><td colSpan={4} className="py-3 px-2 text-center" style={{ color: colors.dim }}>No alerts recorded yet.</td></tr>
            ) : (
              riskAlerts.map((a, i) => (
                <tr key={`live-${i}`} style={{ borderBottom: `1px solid ${colors.cardBorder}`, background: "#1a1422" }}>
                  <td className="py-1.5 px-2" style={{ color: colors.muted }}>{a.timestamp}</td>
                  <td className="py-1.5 px-2 font-semibold" style={{ color: a.severity === "critical" ? colors.red : a.severity === "warning" ? colors.gold : colors.green }}>{a.severity.toUpperCase()}</td>
                  <td className="py-1.5 px-2" style={{ color: colors.text }}>{a.trigger}</td>
                  <td className="py-1.5 px-2" style={{ color: colors.muted }}>{a.details}</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </ChartCard>
      </div>
    </div>
  );
}
