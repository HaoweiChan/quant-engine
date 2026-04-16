import { useState } from "react";
import { colors } from "@/lib/theme";
import { flattenSession } from "@/lib/api";
import type { SettlementInfo, WarRoomSession } from "@/lib/api";

interface Position {
  symbol: string;
  side: string;
  quantity: number;
  avg_entry_price: number;
  current_price: number;
  unrealized_pnl: number;
  strategy?: string;
  strategy_slug?: string;
}

interface RollInfo {
  holding_period: string;
  urgency: "none" | "watch" | "imminent" | "overdue";
  days_to_settlement: number;
}

const URGENCY_STYLES: Record<string, { color: string; label: string }> = {
  none: { color: colors.dim, label: "" },
  watch: { color: colors.gold, label: "ROLL" },
  imminent: { color: colors.orange, label: "ROLL!" },
  overdue: { color: colors.red, label: "ROLL!!" },
};

// Deterministic color map keyed by slug segment
const STRATEGY_COLORS: Record<string, string> = {
  donchian: colors.green,
  night_session_long: "#5a8af2",
  vol_managed_bnh: "#f5a623",
  vol_managed: "#f5a623",
  breakout: "#7ed6df",
  mean_reversion: "#e056fd",
  trend_following: "#22d3ee",
};

function strategyColor(slug: string | undefined): string {
  if (!slug) return colors.dim;
  const seg = slug.split("/").pop() ?? slug;
  if (STRATEGY_COLORS[seg]) return STRATEGY_COLORS[seg];
  // Hash remaining slugs to a stable color
  let h = 0;
  for (let i = 0; i < seg.length; i++) h = (h * 31 + seg.charCodeAt(i)) & 0xffffff;
  return `#${((h & 0xffffff) | 0x404040).toString(16).padStart(6, "0")}`;
}

function strategyLabel(slug: string | undefined): string {
  if (!slug) return "—";
  return slug.split("/").pop() ?? slug;
}

export function PositionsTable({ positions, settlement, sessions, onAction }: { positions: Position[]; settlement?: SettlementInfo; sessions?: WarRoomSession[]; onAction?: () => void }) {
  const [flatteningSlug, setFlatteningSlug] = useState<string | null>(null);

  const sessionBySlug = new Map<string, string>();
  if (sessions) {
    for (const s of sessions) sessionBySlug.set(s.strategy_slug, s.session_id);
  }

  const handleFlatten = async (slug: string | undefined) => {
    if (!slug) return;
    const sessionId = sessionBySlug.get(slug);
    if (!sessionId) return;
    setFlatteningSlug(slug);
    try {
      await flattenSession(sessionId);
      onAction?.();
    } catch { /* ignore */ }
    setFlatteningSlug(null);
  };

  const rollByStrategy = new Map<string, RollInfo>();
  if (settlement?.per_session && sessions) {
    for (const sess of sessions) {
      const rollInfo = settlement.per_session[sess.session_id];
      if (rollInfo && rollInfo.urgency !== "none") {
        rollByStrategy.set(sess.strategy_slug, rollInfo);
      }
    }
  }
  return (
    <div className="rounded h-full flex flex-col" style={{ background: colors.card, border: `1px solid ${colors.cardBorder}` }}>
      <div className="flex items-center justify-between text-[11px] p-2 border-b shrink-0" style={{ borderColor: colors.cardBorder, fontFamily: "var(--font-mono)" }}>
        <span style={{ color: colors.muted }}>OPEN POSITIONS</span>
        {settlement && (
          <span style={{ color: colors.blue, fontSize: 11 }}>
            R1: {settlement.current_month} &rarr; R2: {settlement.next_month}
          </span>
        )}
      </div>
      <div className="p-2 overflow-y-auto flex-1">
        {positions.length === 0 ? (
          <div className="text-[11px] py-2 text-center" style={{ color: colors.dim, fontFamily: "var(--font-mono)" }}>No open positions.</div>
        ) : (
          <table className="w-full text-[11px]" style={{ fontFamily: "var(--font-mono)", borderCollapse: "collapse" }} data-testid="positions-table">
            <thead>
              <tr style={{ borderBottom: `1px solid ${colors.cardBorder}` }}>
                {["Sym", "Strategy", "Side", "Qty", "Entry", "Current", "UnPnL", "Roll", ""].map((h) => (
                  <th key={h || "action"} className="text-left py-1 pr-2" style={{ color: colors.dim }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {positions.map((p, i) => {
                const slug = p.strategy_slug ?? p.strategy;
                const col = strategyColor(slug);
                const rollInfo = slug ? rollByStrategy.get(slug) : undefined;
                const rollStyle = rollInfo ? URGENCY_STYLES[rollInfo.urgency] : URGENCY_STYLES.none;
                const isFlattening = flatteningSlug === slug;
                return (
                  <tr key={i} style={{ borderBottom: `1px solid ${colors.cardBorder}` }}>
                    <td className="py-1 pr-2" style={{ color: colors.text }}>{p.symbol}</td>
                    <td className="py-1 pr-2" style={{ maxWidth: 80 }}>
                      {slug ? (
                        <span className="flex items-center gap-1">
                          <span style={{ display: "inline-block", width: 5, height: 5, borderRadius: "50%", background: col, flexShrink: 0 }} />
                          <span style={{ color: col, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                            {strategyLabel(slug)}
                          </span>
                        </span>
                      ) : (
                        <span style={{ color: colors.dim }}>—</span>
                      )}
                    </td>
                    <td className="py-1 pr-2" style={{ color: p.side === "long" ? colors.green : colors.red }}>{p.side.toUpperCase()}</td>
                    <td className="py-1 pr-2" style={{ color: colors.muted }}>{p.quantity}</td>
                    <td className="py-1 pr-2" style={{ color: colors.muted }}>${p.avg_entry_price.toLocaleString()}</td>
                    <td className="py-1 pr-2" style={{ color: colors.text }}>${p.current_price.toLocaleString()}</td>
                    <td className="py-1 pr-2" style={{ color: p.unrealized_pnl >= 0 ? colors.green : colors.red }}>
                      {p.unrealized_pnl >= 0 ? "+" : ""}${Math.round(p.unrealized_pnl).toLocaleString()}
                    </td>
                    <td className="py-1 pr-2">
                      {rollInfo ? (
                        <span
                          className="px-2 py-0.5 rounded text-[11px] font-bold"
                          style={{ background: rollInfo.urgency === "overdue" ? "#8B6914" : "#1E4D8C", color: "#fff" }}
                          title={`${rollInfo.days_to_settlement}d to settlement`}
                        >
                          {rollStyle.label} {rollInfo.days_to_settlement}d
                        </span>
                      ) : (
                        <span style={{ color: colors.dim }}>—</span>
                      )}
                    </td>
                    <td className="py-1">
                      <button
                        onClick={() => handleFlatten(slug)}
                        disabled={isFlattening}
                        className="px-2 py-0.5 rounded text-[11px] font-bold cursor-pointer border-none"
                        style={{ background: "#991B1B", color: "#fff", opacity: isFlattening ? 0.5 : 1 }}
                      >
                        {isFlattening ? "..." : "FLATTEN"}
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
