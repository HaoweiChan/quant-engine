import { useEffect, useState, useMemo } from "react";
import { Sidebar, SectionLabel } from "@/components/Sidebar";
import { StatCard, StatRow } from "@/components/StatCard";
import { ChartCard } from "@/components/ChartCard";
import { DrawdownChart } from "@/components/charts/DrawdownChart";
import { useTradingStore } from "@/stores/tradingStore";
import { useRiskAlerts } from "@/hooks/useRiskAlerts";
import { colors } from "@/lib/theme";
import type { WarRoomData } from "@/lib/api";

export function RiskTab() {
  const riskAlerts = useTradingStore((s) => s.riskAlerts);
  const warRoomData = useTradingStore((s) => s.warRoomData) as WarRoomData | null;
  useRiskAlerts();
  const [enabledAccounts, setEnabledAccounts] = useState<Record<string, boolean>>({});
  const accounts = warRoomData?.accounts ?? {};
  useEffect(() => {
    const ids = Object.keys(accounts);
    if (ids.length === 0) return;
    setEnabledAccounts((prev) => {
      const next = { ...prev };
      for (const id of ids) {
        if (!(id in next)) next[id] = id !== "mock-dev";
      }
      return next;
    });
  }, [Object.keys(accounts).join(",")]);
  const toggleAccount = (id: string) => setEnabledAccounts((prev) => ({ ...prev, [id]: !prev[id] }));
  const included = Object.entries(accounts).filter(([id, a]) => a.connected && enabledAccounts[id]);
  const totalEquity = included.reduce((sum, [, a]) => sum + a.equity, 0);
  const totalMarginUsed = included.reduce((sum, [, a]) => sum + a.margin_used, 0);
  const totalMarginAvail = included.reduce((sum, [, a]) => sum + a.margin_available, 0);
  const marginRatio = (totalMarginUsed + totalMarginAvail) > 0 ? totalMarginUsed / (totalMarginUsed + totalMarginAvail) : 0;
  const allSessions = warRoomData?.all_sessions ?? [];
  const includedIds = new Set(included.map(([id]) => id));
  const filteredSessions = allSessions.filter((s) => includedIds.has(s.account_id));
  const worstDD = filteredSessions.reduce((mx, s) => Math.max(mx, s.snapshot?.drawdown_pct ?? 0), 0);
  const totalUnrealizedPnl = filteredSessions.reduce((sum, s) => sum + (s.snapshot?.unrealized_pnl ?? 0), 0);
  const equityCurveData = useMemo(() => {
    const acct = included.find(([, a]) => a.equity_curve && a.equity_curve.length > 0);
    return acct?.[1]?.equity_curve?.map((p) => p.equity) ?? [];
  }, [included]);
  const thresholds = useMemo(() => {
    const rows: { parameter: string; value: string; status: string }[] = [];
    for (const [, info] of included) {
      const ratio = info.margin_used / Math.max(1, info.margin_used + info.margin_available) * 100;
      rows.push({ parameter: `${info.display_name} Margin`, value: `${ratio.toFixed(1)}%`, status: ratio < 80 ? "OK" : "WARN" });
    }
    if (rows.length === 0) rows.push({ parameter: "No accounts selected", value: "—", status: "—" });
    return rows;
  }, [included]);
  return (
    <div className="flex">
      <Sidebar>
        <SectionLabel>ACCOUNTS</SectionLabel>
        <div className="text-[7px] mb-2" style={{ color: colors.dim, fontFamily: "var(--font-mono)" }}>Toggle accounts for risk calculation</div>
        {Object.entries(accounts).map(([id, info]) => {
          const on = enabledAccounts[id] ?? false;
          const marginPct = (info.margin_used + info.margin_available) > 0 ? info.margin_used / (info.margin_used + info.margin_available) * 100 : 0;
          return (
            <div key={id} onClick={() => toggleAccount(id)} className="rounded p-2 mb-1.5 cursor-pointer transition-opacity" style={{ background: colors.card, border: `1px solid ${on ? "rgba(105,240,174,0.3)" : colors.cardBorder}`, opacity: on ? 1 : 0.4 }}>
              <div className="flex items-center justify-between mb-0.5">
                <span className="text-[9px]" style={{ fontFamily: "var(--font-mono)", color: colors.text }}>{info.display_name || id}</span>
                <span className="text-[7px] font-semibold px-1 py-0.5 rounded text-white" style={{ background: info.connected ? colors.green : "#6B4040" }}>
                  {info.connected ? "LIVE" : "OFF"}
                </span>
              </div>
              {info.connected && (
                <>
                  <div className="text-[12px] font-bold" style={{ fontFamily: "var(--font-mono)", color: colors.green }}>${info.equity.toLocaleString()}</div>
                  <div className="text-[7px]" style={{ color: colors.muted, fontFamily: "var(--font-mono)" }}>
                    Margin {marginPct.toFixed(1)}%
                  </div>
                </>
              )}
            </div>
          );
        })}
      </Sidebar>
      <div className="flex-1 p-3 overflow-y-auto" style={{ minWidth: 0 }}>
        <StatRow>
          <StatCard label="TOTAL EQUITY" value={totalEquity > 0 ? `$${totalEquity.toLocaleString()}` : "—"} color={totalEquity > 0 ? colors.green : colors.dim} />
          <StatCard label="MARGIN RATIO" value={`${(marginRatio * 100).toFixed(1)}%`} color={marginRatio < 0.30 ? colors.gold : colors.red} />
          <StatCard label="WORST DRAWDOWN" value={`${worstDD.toFixed(1)}%`} color={worstDD > 5 ? colors.red : colors.gold} />
          <StatCard label="UNREALIZED PNL" value={`$${Math.round(totalUnrealizedPnl).toLocaleString()}`} color={totalUnrealizedPnl >= 0 ? colors.green : colors.red} />
        </StatRow>
        {equityCurveData.length > 0 && (
          <ChartCard title="EQUITY OVER TIME">
            <DrawdownChart equity={equityCurveData} height={220} />
          </ChartCard>
        )}
        <ChartCard title="PER-ACCOUNT MARGIN">
          <table className="w-full text-[9px]" style={{ fontFamily: "var(--font-mono)" }}>
            <thead>
              <tr style={{ borderBottom: `1px solid ${colors.cardBorder}` }}>
                {["Account", "Margin Used", "Status"].map((h) => (
                  <th key={h} className="text-left py-1 px-2" style={{ color: colors.dim }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {thresholds.map((t, i) => (
                <tr key={i} style={{ borderBottom: `1px solid ${colors.cardBorder}` }}>
                  <td className="py-1 px-2" style={{ color: colors.text }}>{t.parameter}</td>
                  <td className="py-1 px-2" style={{ color: colors.muted }}>{t.value}</td>
                  <td className="py-1 px-2" style={{ color: t.status === "OK" ? colors.green : t.status === "WARN" ? colors.gold : colors.dim }}>{t.status}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </ChartCard>
        <ChartCard title="ALERT HISTORY">
          <table className="w-full text-[9px]" style={{ fontFamily: "var(--font-mono)" }}>
            <thead>
              <tr style={{ borderBottom: `1px solid ${colors.cardBorder}` }}>
                {["Time", "Severity", "Trigger", "Details"].map((h) => (
                  <th key={h} className="text-left py-1 px-2" style={{ color: colors.dim }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {riskAlerts.length === 0 ? (
                <tr><td colSpan={4} className="py-3 px-2 text-center" style={{ color: colors.dim }}>No alerts recorded yet.</td></tr>
              ) : (
                riskAlerts.map((a, i) => (
                  <tr key={`live-${i}`} style={{ borderBottom: `1px solid ${colors.cardBorder}`, background: "#1a1422" }}>
                    <td className="py-1 px-2" style={{ color: colors.muted }}>{a.timestamp}</td>
                    <td className="py-1 px-2 font-semibold" style={{ color: a.severity === "critical" ? colors.red : a.severity === "warning" ? colors.gold : colors.green }}>{a.severity.toUpperCase()}</td>
                    <td className="py-1 px-2" style={{ color: colors.text }}>{a.trigger}</td>
                    <td className="py-1 px-2" style={{ color: colors.muted }}>{a.details}</td>
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
