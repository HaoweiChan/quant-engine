import { colors } from "@/lib/theme";

interface Position {
  symbol: string;
  side: string;
  quantity: number;
  avg_entry_price: number;
  current_price: number;
  unrealized_pnl: number;
  strategy?: string;
}

export function PositionsTable({ positions }: { positions: Position[] }) {
  return (
    <div className="rounded h-full flex flex-col" style={{ background: colors.card, border: `1px solid ${colors.cardBorder}` }}>
      <div className="text-[10px] p-2 border-b shrink-0" style={{ borderColor: colors.cardBorder, color: colors.muted, fontFamily: "var(--font-mono)" }}>
        OPEN POSITIONS
      </div>
      <div className="p-2 overflow-y-auto flex-1">
        {positions.length === 0 ? (
          <div className="text-[9px] py-2 text-center" style={{ color: colors.dim, fontFamily: "var(--font-mono)" }}>No open positions.</div>
        ) : (
          <table className="w-full text-[9px]" style={{ fontFamily: "var(--font-mono)", borderCollapse: "collapse" }}>
            <thead>
              <tr style={{ borderBottom: `1px solid ${colors.cardBorder}` }}>
                {["Sym", "Side", "Qty", "Entry", "Current", "UnPnL"].map((h) => (
                  <th key={h} className="text-left py-1 pr-2" style={{ color: colors.dim }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {positions.map((p, i) => (
                <tr key={i} style={{ borderBottom: `1px solid ${colors.cardBorder}` }}>
                  <td className="py-1 pr-2" style={{ color: colors.text }}>{p.symbol}</td>
                  <td className="py-1 pr-2" style={{ color: p.side === "long" ? colors.green : colors.red }}>{p.side.toUpperCase()}</td>
                  <td className="py-1 pr-2" style={{ color: colors.muted }}>{p.quantity}</td>
                  <td className="py-1 pr-2" style={{ color: colors.muted }}>${p.avg_entry_price.toLocaleString()}</td>
                  <td className="py-1 pr-2" style={{ color: colors.text }}>${p.current_price.toLocaleString()}</td>
                  <td className="py-1 pr-2" style={{ color: p.unrealized_pnl >= 0 ? colors.green : colors.red }}>
                    {p.unrealized_pnl >= 0 ? "+" : ""}${Math.round(p.unrealized_pnl).toLocaleString()}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
