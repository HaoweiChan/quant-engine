import { colors } from "@/lib/theme";
import type { SettlementInfo } from "@/lib/api";

interface SettlementCountdownProps {
  settlement?: SettlementInfo;
}

export function SettlementCountdown({ settlement }: SettlementCountdownProps) {
  if (!settlement) return null;
  const days = settlement.days_to_settlement;
  const urgent = days <= 2;
  const warning = days <= 5;
  const dateLabel = settlement.settlement_date.slice(5).replace("-", "/");
  return (
    <div className="flex items-center gap-1.5">
      <span className="text-[8px]" style={{ color: colors.dim, fontFamily: "var(--font-mono)" }}>
        Settle
      </span>
      <span
        className="text-[10px] font-semibold"
        style={{
          color: urgent ? colors.red : warning ? colors.orange : colors.muted,
          fontFamily: "var(--font-mono)",
        }}
      >
        {days}d
      </span>
      <span className="text-[8px]" style={{ color: colors.dim, fontFamily: "var(--font-mono)" }}>
        ({dateLabel})
      </span>
      <span className="text-[8px]" style={{ color: colors.blue, fontFamily: "var(--font-mono)" }}>
        {settlement.current_month}
      </span>
    </div>
  );
}
