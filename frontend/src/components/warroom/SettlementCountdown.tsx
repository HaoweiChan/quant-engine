import { colors } from "@/lib/theme";
import type { SettlementInfo } from "@/lib/api";

const MONTH_ABBR = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

function formatMonth(yyyymm: string): string {
  const m = parseInt(yyyymm.slice(4), 10);
  return m >= 1 && m <= 12 ? MONTH_ABBR[m - 1] : yyyymm;
}

interface SettlementCountdownProps {
  settlement?: SettlementInfo;
}

export function SettlementCountdown({ settlement }: SettlementCountdownProps) {
  if (!settlement) return null;
  const days = settlement.days_to_settlement;
  const urgent = days <= 2;
  const warning = days <= 5;
  const accentColor = urgent ? colors.red : warning ? colors.orange : colors.dim;
  const dateParts = settlement.settlement_date.split("-");
  const dateLabel = `${dateParts[1]}/${dateParts[2]}`;

  return (
    <div
      className="flex items-center gap-1 px-2 py-0.5 rounded"
      style={{
        fontFamily: "var(--font-mono)",
        background: `${accentColor}10`,
        border: `1px solid ${accentColor}25`,
      }}
    >
      <span
        className="text-[11px] font-semibold"
        style={{ color: accentColor }}
      >
        {days}d
      </span>
      <span className="text-[11px]" style={{ color: colors.dim }}>
        settle {dateLabel}
      </span>
      <span className="text-[11px]" style={{ color: colors.muted }}>
        {formatMonth(settlement.current_month)}→{formatMonth(settlement.next_month)}
      </span>
    </div>
  );
}
