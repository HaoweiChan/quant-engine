import { colors } from "@/lib/theme";

interface Fill {
  timestamp: string;
  symbol: string;
  side: string;
  price: number;
  quantity: number;
  fee: number;
}

export function TradesTable({ fills }: { fills: Fill[] }) {
  return (
    <div className="rounded h-full flex flex-col" style={{ background: colors.card, border: `1px solid ${colors.cardBorder}` }}>
      <div className="text-[10px] p-2 border-b shrink-0" style={{ borderColor: colors.cardBorder, color: colors.muted, fontFamily: "var(--font-mono)" }}>
        RECENT TRADES
      </div>
      <div className="p-2 overflow-y-auto flex-1">
        {fills.length === 0 ? (
          <div className="text-[9px] py-2 text-center" style={{ color: colors.dim, fontFamily: "var(--font-mono)" }}>No recent trades.</div>
        ) : (
          <table className="w-full text-[9px]" style={{ fontFamily: "var(--font-mono)", borderCollapse: "collapse" }}>
            <thead>
              <tr style={{ borderBottom: `1px solid ${colors.cardBorder}` }}>
                {["Time", "Sym", "Side", "Price", "Qty", "Fee"].map((h) => (
                  <th key={h} className="text-left py-1 pr-2" style={{ color: colors.dim }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {fills.slice(0, 20).map((f, i) => (
                <tr key={i} style={{ borderBottom: `1px solid ${colors.cardBorder}` }}>
                  <td className="py-1 pr-2" style={{ color: colors.dim }}>{f.timestamp.slice(0, 16).replace("T", " ")}</td>
                  <td className="py-1 pr-2" style={{ color: colors.text }}>{f.symbol}</td>
                  <td className="py-1 pr-2" style={{ color: f.side === "buy" || f.side === "long" ? colors.green : colors.red }}>{f.side.toUpperCase()}</td>
                  <td className="py-1 pr-2" style={{ color: colors.muted }}>${f.price.toLocaleString()}</td>
                  <td className="py-1 pr-2" style={{ color: colors.muted }}>{f.quantity}</td>
                  <td className="py-1 pr-2" style={{ color: colors.dim }}>${f.fee.toFixed(2)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
