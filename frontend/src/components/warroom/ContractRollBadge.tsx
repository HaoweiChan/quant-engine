import { colors } from "@/lib/theme";

type Urgency = "none" | "watch" | "imminent" | "overdue";

interface ContractRollBadgeProps {
  urgency: Urgency;
  daysToSettlement: number;
  holdingPeriod: string;
  compact?: boolean;
}

const URGENCY_CONFIG: Record<Urgency, { label: string; color: string; bg: string }> = {
  none: { label: "", color: colors.dim, bg: "transparent" },
  watch: { label: "ROLL", color: colors.gold, bg: "rgba(255,213,79,0.12)" },
  imminent: { label: "ROLL!", color: colors.orange, bg: "rgba(255,138,101,0.15)" },
  overdue: { label: "ROLL!!", color: colors.red, bg: "rgba(255,82,82,0.18)" },
};

export function ContractRollBadge({ urgency, daysToSettlement, holdingPeriod, compact }: ContractRollBadgeProps) {
  if (urgency === "none") return null;
  const cfg = URGENCY_CONFIG[urgency];
  const hp = holdingPeriod === "medium_term" ? "MT" : holdingPeriod === "swing" ? "SW" : "ST";
  if (compact) {
    return (
      <span
        className="text-[11px] px-1 py-0.5 rounded"
        style={{ background: cfg.bg, color: cfg.color, fontFamily: "var(--font-mono)" }}
        title={`${daysToSettlement}d to settlement (${holdingPeriod})`}
      >
        {cfg.label}
      </span>
    );
  }
  return (
    <div
      className="flex items-center gap-1 px-1.5 py-0.5 rounded text-[11px]"
      style={{ background: cfg.bg, fontFamily: "var(--font-mono)" }}
    >
      <span style={{ color: cfg.color, fontWeight: 600 }}>{cfg.label}</span>
      <span style={{ color: cfg.color }}>{daysToSettlement}d</span>
      <span style={{ color: colors.dim }}>{hp}</span>
    </div>
  );
}
