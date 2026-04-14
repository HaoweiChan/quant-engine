import { EquityCurveChart } from "@/components/charts/EquityCurveChart";
import { colors } from "@/lib/theme";
import type { WarRoomSession } from "@/lib/api";

interface EquityPanelProps {
  equityCurve: number[];
  equityTimestamps?: number[];
  sessions: WarRoomSession[];
  accountLabel: string;
  visibleRange?: { fromTs: string; toTs: string } | null;
}

export function EquityPanel({ equityCurve, equityTimestamps, sessions, accountLabel, visibleRange }: EquityPanelProps) {
  const activeSessions = sessions.filter((s) => s.status === "active" || s.status === "paused");

  return (
    <div className="h-full flex flex-col rounded" style={{ background: colors.card, border: `1px solid ${colors.cardBorder}` }}>
      <div className="text-[9px] px-2 py-1.5 border-b shrink-0 flex items-center justify-between" style={{ borderColor: colors.cardBorder, fontFamily: "var(--font-mono)" }}>
        <span style={{ color: colors.muted }}>EQUITY &mdash; {accountLabel}</span>
      </div>
      <div className="p-2 flex-1 min-h-0">
        {equityCurve.length > 0 ? (
          <EquityCurveChart
            equity={equityCurve}
            timestamps={equityTimestamps}
            height={120}
            visibleRange={visibleRange}
          />
        ) : (
          <div className="text-[8px] py-4 text-center" style={{ color: colors.dim, fontFamily: "var(--font-mono)" }}>
            No equity data yet.
          </div>
        )}
      </div>
      {activeSessions.length > 0 && (
        <div className="px-2 pb-2 border-t" style={{ borderColor: colors.cardBorder }}>
          <div className="text-[8px] py-1" style={{ color: colors.muted, fontFamily: "var(--font-mono)" }}>SESSION PNL</div>
          {activeSessions.map((s) => (
            <div key={s.session_id} className="flex items-center justify-between py-0.5 text-[8px]" style={{ fontFamily: "var(--font-mono)" }}>
              <span style={{ color: colors.text }}>
                {s.strategy_slug.split("/").pop()} &middot; {s.symbol}
              </span>
              <span style={{ color: (s.snapshot?.unrealized_pnl ?? 0) >= 0 ? colors.green : colors.red }}>
                {(s.snapshot?.unrealized_pnl ?? 0) >= 0 ? "+" : ""}${Math.round(s.snapshot?.unrealized_pnl ?? 0).toLocaleString()}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
