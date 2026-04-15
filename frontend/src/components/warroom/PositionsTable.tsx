import { colors } from "@/lib/theme";
import type { SettlementInfo } from "@/lib/api";

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

export function PositionsTable({ positions, settlement }: { positions: Position[]; settlement?: SettlementInfo }) {
  return (
    <div className="rounded h-full flex flex-col" style={{ background: colors.card, border: `1px solid ${colors.cardBorder}` }}>
      <div className="flex items-center justify-between text-[11px] p-2 border-b shrink-0" style={{ borderColor: colors.cardBorder, fontFamily: "var(--font-mono)" }}>
        <span style={{ color: colors.muted }}>OPEN POSITIONS</span>
        {settlement && (
          <span style={{ color: colors.blue, fontSize: 9 }}>
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
                {["Sym", "Strategy", "Side", "Qty", "Entry", "Current", "UnPnL"].map((h) => (
                  <th key={h} className="text-left py-1 pr-2" style={{ color: colors.dim }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {positions.map((p, i) => {
                const slug = p.strategy_slug ?? p.strategy;
                const col = strategyColor(slug);
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
