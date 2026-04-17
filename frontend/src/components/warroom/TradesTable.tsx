import { colors } from "@/lib/theme";

interface Fill {
  timestamp: string;
  symbol: string;
  side: string;
  price: number;
  quantity: number;
  fee: number;
  strategy_slug?: string;
}

// Deterministic color map keyed by slug segment (shared logic with PositionsTable)
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
  let h = 0;
  for (let i = 0; i < seg.length; i++) h = (h * 31 + seg.charCodeAt(i)) & 0xffffff;
  return `#${((h & 0xffffff) | 0x404040).toString(16).padStart(6, "0")}`;
}

function strategyLabel(slug: string | undefined): string {
  if (!slug) return "—";
  return slug.split("/").pop() ?? slug;
}

export function TradesTable({ fills }: { fills: Fill[] }) {
  return (
    <div className="h-full flex flex-col">
      <div className="p-2 overflow-y-auto flex-1">
        {fills.length === 0 ? (
          <div className="text-[11px] py-2 text-center" style={{ color: colors.dim, fontFamily: "var(--font-mono)" }}>No recent trades.</div>
        ) : (
          <table className="w-full text-[11px]" style={{ fontFamily: "var(--font-mono)", borderCollapse: "collapse" }} data-testid="trades-table">
            <thead>
              <tr style={{ borderBottom: `1px solid ${colors.cardBorder}` }}>
                {["Time", "Sym", "Strategy", "Side", "Price", "Qty", "Fee"].map((h) => (
                  <th key={h} className="text-left py-1 pr-2" style={{ color: colors.dim }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {fills.slice(0, 50).map((f, i) => {
                const col = strategyColor(f.strategy_slug);
                return (
                  <tr key={i} style={{ borderBottom: `1px solid ${colors.cardBorder}` }} data-testid="trade-row">
                    <td className="py-1 pr-2" style={{ color: colors.dim }}>{f.timestamp.slice(0, 16).replace("T", " ")}</td>
                    <td className="py-1 pr-2" style={{ color: colors.text }}>{f.symbol}</td>
                    <td className="py-1 pr-2" style={{ maxWidth: 72 }} data-testid="strategy-badge">
                      {f.strategy_slug ? (
                        <span className="flex items-center gap-1">
                          <span style={{ display: "inline-block", width: 5, height: 5, borderRadius: "50%", background: col, flexShrink: 0 }} />
                          <span style={{ color: col, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                            {strategyLabel(f.strategy_slug)}
                          </span>
                        </span>
                      ) : (
                        <span style={{ color: colors.dim }}>—</span>
                      )}
                    </td>
                    <td className="py-1 pr-2" style={{ color: f.side === "buy" || f.side === "long" ? colors.green : colors.red }}>{f.side.toUpperCase()}</td>
                    <td className="py-1 pr-2" style={{ color: colors.muted }}>${f.price.toLocaleString()}</td>
                    <td className="py-1 pr-2" style={{ color: colors.muted }}>{f.quantity}</td>
                    <td className="py-1 pr-2" style={{ color: colors.dim }}>${f.fee.toFixed(2)}</td>
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
