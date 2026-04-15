import { useRef } from "react";
import { EquityCurveChart, type EquityCurveChartHandle } from "@/components/charts/EquityCurveChart";
import { colors } from "@/lib/theme";
import type { WarRoomSession } from "@/lib/api";

interface EquityPanelProps {
  equityCurve: number[];
  equityTimestamps?: number[];
  sessions: WarRoomSession[];
  accountLabel: string;
  visibleRange?: { fromTs: string; toTs: string } | null;
  playbackActive?: boolean;
}

export function EquityPanel({ equityCurve, equityTimestamps, sessions, accountLabel, visibleRange, playbackActive }: EquityPanelProps) {
  const activeSessions = sessions.filter((s) => s.status === "active" || s.status === "paused");
  const chartRef = useRef<EquityCurveChartHandle>(null);

  return (
    <div className="h-full flex flex-col rounded" style={{ background: colors.card, border: `1px solid ${colors.cardBorder}` }}>
      <div className="text-[11px] px-2 py-1.5 border-b shrink-0 flex items-center justify-between" style={{ borderColor: colors.cardBorder, fontFamily: "var(--font-mono)" }}>
        <span style={{ color: colors.muted }}>EQUITY</span>
        <button
          onClick={() => chartRef.current?.fitContent()}
          className="p-1 rounded cursor-pointer border-none flex items-center justify-center"
          style={{ background: "rgba(90,138,242,0.12)", color: colors.text }}
          title="Fit to view"
        >
          <svg viewBox="0 0 16 16" width="12" height="12" fill="none" stroke="currentColor" strokeWidth="1.5">
            <path d="M2 5V2h3M11 2h3v3M14 11v3h-3M5 14H2v-3" />
          </svg>
        </button>
      </div>
      <div className="p-2 flex-1 min-h-0">
        {equityCurve.length > 0 ? (
          <EquityCurveChart
            ref={chartRef}
            equity={equityCurve}
            timestamps={equityTimestamps}
            height={120}
            visibleRange={visibleRange}
            playbackActive={playbackActive}
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
              {(() => {
                const total = (s.snapshot?.realized_pnl ?? 0) + (s.snapshot?.unrealized_pnl ?? 0);
                return (
                  <span style={{ color: total >= 0 ? colors.green : colors.red }}>
                    {total >= 0 ? "+" : ""}${Math.round(total).toLocaleString()}
                  </span>
                );
              })()}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
