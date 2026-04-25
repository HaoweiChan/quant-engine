import { useMemo } from "react";
import { useBlotter } from "@/hooks/useBlotter";
import type { BlotterEvent } from "@/hooks/useBlotter";
import type { AccountFill } from "@/lib/api";
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

function fmtTime(ts: number | string): string {
  try {
    const date = typeof ts === 'string' ? new Date(ts) : new Date(ts * 1000);
    const year = date.getFullYear();
    const month = String(date.getMonth() + 1).padStart(2, '0');
    const day = String(date.getDate()).padStart(2, '0');
    const hours = String(date.getHours()).padStart(2, '0');
    const minutes = String(date.getMinutes()).padStart(2, '0');
    return `${year}-${month}-${day} ${hours}:${minutes}`;
  } catch {
    return "—";
  }
}

interface OrderBlotterPaneProps {
  playbackFills?: AccountFill[];
}

export function OrderBlotterPane({ playbackFills }: OrderBlotterPaneProps = {}) {
  const { events: liveEvents, connected } = useBlotter();

  const playbackEvents: BlotterEvent[] = useMemo(() => {
    if (!playbackFills || playbackFills.length === 0) return [];
    return playbackFills.map((f) => ({
      type: "fill" as const,
      symbol: f.symbol,
      side: (f.side === "Buy" || f.side === "buy" ? "buy" : "sell") as "buy" | "sell",
      qty: f.quantity,
      price: f.price,
      timestamp: Math.floor(new Date(f.timestamp).getTime() / 1000),
      strategy_slug: f.strategy_slug,
      signal_reason: "",
      triggered: true,
    }));
  }, [playbackFills]);

  const events = playbackFills && playbackFills.length > 0 ? playbackEvents : liveEvents;
  const isPlayback = playbackFills !== undefined && playbackFills.length > 0;

  return (
    <div className="h-full flex flex-col">
      <div className="p-2 overflow-y-auto flex-1">
      {events.length === 0 ? (
        <div className="text-[11px] py-3 text-center" style={{ color: colors.dim, fontFamily: "var(--font-mono)" }}>
          No events yet.
        </div>
      ) : (
        <table className="w-full text-[11px]" style={{ fontFamily: "var(--font-mono)" }}>
          <thead>
            <tr style={{ borderBottom: `1px solid ${colors.cardBorder}` }}>
              <th className="text-left py-0.5 px-1" style={{ color: colors.dim }}>Time</th>
              <th className="text-left py-0.5 px-1" style={{ color: colors.dim }}>Type</th>
              <th className="text-left py-0.5 px-1" style={{ color: colors.dim }}>Symbol</th>
              <th className="text-left py-0.5 px-1" style={{ color: colors.dim }}>Strategy</th>
              <th className="text-left py-0.5 px-1" style={{ color: colors.dim }}>Signal</th>
              <th className="text-left py-0.5 px-1" style={{ color: colors.dim }}>Status</th>
              <th className="text-right py-0.5 px-1" style={{ color: colors.dim }}>Side</th>
              <th className="text-right py-0.5 px-1" style={{ color: colors.dim }}>Qty</th>
              <th className="text-right py-0.5 px-1" style={{ color: colors.dim }}>Price</th>
              <th className="text-right py-0.5 px-1" style={{ color: colors.dim }}>Slip(bps)</th>
              <th className="text-right py-0.5 px-1">
                <span className="flex items-center justify-end gap-1" style={{ fontFamily: "var(--font-mono)" }}>
                  <span
                    className="inline-block w-1.5 h-1.5 rounded-full"
                    style={{ background: isPlayback ? colors.cyan : connected ? colors.green : colors.red }}
                  />
                  <span style={{ color: isPlayback ? colors.cyan : connected ? colors.dim : colors.red }}>
                    {isPlayback ? "PLAYBACK" : connected ? "LIVE" : "DISCONNECTED"}
                  </span>
                </span>
              </th>
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
    </div>
  );
}

function BlotterRow({ ev }: { ev: BlotterEvent }) {
  const slip = ev.slippage_bps;
  const isFilled = ev.triggered !== false; // default true when field absent
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
      <td className="py-0.5 px-1" style={{ color: colors.muted }}>
        {ev.signal_reason ? ev.signal_reason : "—"}
      </td>
      <td className="py-0.5 px-1">
        <span style={{ color: isFilled ? colors.green : "#f5a623", fontWeight: 600 }}>
          {isFilled ? "FILLED" : "PENDING"}
        </span>
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
