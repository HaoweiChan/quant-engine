import { useBlotter } from "@/hooks/useBlotter";
import type { BlotterEvent } from "@/hooks/useBlotter";
import { colors, pnlColor } from "@/lib/theme";


const typeColor: Record<string, string> = {
  fill: colors.green,
  submission: colors.cyan,
  rejection: colors.red,
};

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
              <th className="text-left py-0.5 px-1" style={{ color: colors.dim }}>Strategy</th>
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
      <td className="py-0.5 px-1" style={{ maxWidth: 72 }} data-testid="blotter-strategy-badge">
        {ev.strategy_slug ? (
          <span className="flex items-center gap-1">
            <span style={{ display: "inline-block", width: 5, height: 5, borderRadius: "50%", background: strategyColor(ev.strategy_slug), flexShrink: 0 }} />
            <span style={{ color: strategyColor(ev.strategy_slug), overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
              {strategyLabel(ev.strategy_slug)}
            </span>
          </span>
        ) : (
          <span style={{ color: colors.dim }}>—</span>
        )}
      </td>
      <td className="text-right py-0.5 px-1" style={{ color: ev.side === "buy" ? colors.green : colors.red }}>{ev.side ?? "—"}</td>
      <td className="text-right py-0.5 px-1" style={{ color: colors.muted }}>{ev.qty ?? "—"}</td>
      <td className="text-right py-0.5 px-1" style={{ color: colors.text }}>{ev.price?.toLocaleString() ?? "—"}</td>
      <td className="text-right py-0.5 px-1" style={{ color: slip != null ? pnlColor(-slip) : colors.dim }}>
        {slip != null ? slip.toFixed(1) : "—"}
      </td>
    </tr>
  );
}
