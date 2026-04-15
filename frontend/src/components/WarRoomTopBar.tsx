import { HeartbeatIndicator } from "@/components/HeartbeatIndicator";
import { KillSwitchBar } from "@/components/KillSwitchBar";
import { colors } from "@/lib/theme";


interface WarRoomTopBarProps {
  totalEquity?: number;
  marginRatio?: number;
}

export function WarRoomTopBar({ totalEquity, marginRatio }: WarRoomTopBarProps) {
  const fmtDollar = (v: number) => `$${v.toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
  const marginColor = (marginRatio ?? 0) > 0.8 ? colors.red : (marginRatio ?? 0) > 0.6 ? "#D4A017" : colors.green;

  return (
    <div
      className="sticky top-0 z-10 flex items-center justify-between gap-4 px-4 py-2"
      style={{
        background: "var(--color-qe-sidebar)",
        borderBottom: `1px solid ${colors.cardBorder}`,
      }}
    >
      <div className="flex items-center gap-4">
        {totalEquity !== undefined && (
          <div className="flex items-center gap-1.5">
            <span className="text-[10px]" style={{ color: colors.dim, fontFamily: "var(--font-mono)" }}>EQUITY</span>
            <span className="text-[14px] font-semibold" style={{ color: colors.text, fontFamily: "var(--font-mono)" }}>
              {fmtDollar(totalEquity)}
            </span>
          </div>
        )}
        {marginRatio !== undefined && (
          <div className="flex items-center gap-1.5">
            <span className="text-[10px]" style={{ color: colors.dim, fontFamily: "var(--font-mono)" }}>MARGIN</span>
            <span className="text-[13px] font-semibold" style={{ color: marginColor, fontFamily: "var(--font-mono)" }}>
              {(marginRatio * 100).toFixed(1)}%
            </span>
          </div>
        )}
        <HeartbeatIndicator />
      </div>
      <KillSwitchBar />
    </div>
  );
}
