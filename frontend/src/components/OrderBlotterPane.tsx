import { useBlotter } from "@/hooks/useBlotter";
import type { BlotterEvent } from "@/hooks/useBlotter";
import { colors, pnlColor } from "@/lib/theme";


const typeColor: Record<string, string> = {
  fill: colors.green,
  submission: colors.cyan,
  rejection: colors.red,
};

function fmtTime(ts: number): string {
  return new Date(ts * 1000).toLocaleTimeString(undefined, { hour12: false });
}

export function OrderBlotterPane() {
  const { events, connected } = useBlotter();

  return (
    <div className="overflow-y-auto" style={{ maxHeight: 320 }}>
      <div className="flex items-center justify-between mb-1.5 px-1">
        <span className="text-[9px] font-semibold" style={{ color: colors.muted, fontFamily: "var(--font-mono)" }}>
          ORDER BLOTTER
        </span>
        <span className="flex items-center gap-1 text-[8px]" style={{ fontFamily: "var(--font-mono)" }}>
          <span
            className="inline-block w-1.5 h-1.5 rounded-full"
            style={{ background: connected ? colors.green : colors.red }}
          />
          <span style={{ color: connected ? colors.dim : colors.red }}>
            {connected ? "LIVE" : "DISCONNECTED"}
          </span>
        </span>
      </div>
      {events.length === 0 ? (
        <div className="text-[10px] py-3 text-center" style={{ color: colors.dim, fontFamily: "var(--font-mono)" }}>
          No events yet.
        </div>
      ) : (
        <table className="w-full text-[9px]" style={{ fontFamily: "var(--font-mono)" }}>
          <thead>
            <tr style={{ borderBottom: `1px solid ${colors.cardBorder}` }}>
              <th className="text-left py-0.5 px-1" style={{ color: colors.dim }}>Time</th>
              <th className="text-left py-0.5 px-1" style={{ color: colors.dim }}>Type</th>
              <th className="text-left py-0.5 px-1" style={{ color: colors.dim }}>Symbol</th>
              <th className="text-right py-0.5 px-1" style={{ color: colors.dim }}>Side</th>
              <th className="text-right py-0.5 px-1" style={{ color: colors.dim }}>Qty</th>
              <th className="text-right py-0.5 px-1" style={{ color: colors.dim }}>Price</th>
              <th className="text-right py-0.5 px-1" style={{ color: colors.dim }}>Slip(bps)</th>
            </tr>
          </thead>
          <tbody>
            {events.map((ev, i) => (
              <BlotterRow key={`${ev.timestamp}-${i}`} ev={ev} />
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

function BlotterRow({ ev }: { ev: BlotterEvent }) {
  const slip = ev.slippage_bps;
  return (
    <tr style={{ borderBottom: `1px solid ${colors.cardBorder}` }}>
      <td className="py-0.5 px-1" style={{ color: colors.dim }}>{fmtTime(ev.timestamp)}</td>
      <td className="py-0.5 px-1" style={{ color: typeColor[ev.type] ?? colors.muted }}>{ev.type.toUpperCase()}</td>
      <td className="py-0.5 px-1" style={{ color: colors.text }}>{ev.symbol ?? "—"}</td>
      <td className="text-right py-0.5 px-1" style={{ color: ev.side === "buy" ? colors.green : colors.red }}>{ev.side ?? "—"}</td>
      <td className="text-right py-0.5 px-1" style={{ color: colors.muted }}>{ev.qty ?? "—"}</td>
      <td className="text-right py-0.5 px-1" style={{ color: colors.text }}>{ev.price?.toLocaleString() ?? "—"}</td>
      <td className="text-right py-0.5 px-1" style={{ color: slip != null ? pnlColor(-slip) : colors.dim }}>
        {slip != null ? slip.toFixed(1) : "—"}
      </td>
    </tr>
  );
}
