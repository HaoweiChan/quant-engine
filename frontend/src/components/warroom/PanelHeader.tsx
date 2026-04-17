import type { ReactNode } from "react";
import { colors } from "@/lib/theme";
import type { OHLCVBar } from "@/lib/api";

interface PanelHeaderProps {
  chip: string;
  chipColor: string;
  symbol: string;
  bars: OHLCVBar[];
  liveValue?: number;
  rightBadge?: ReactNode;
  collapsed?: boolean;
  onToggleCollapse?: () => void;
}

// TAIFEX session boundaries (Taipei time):
//   NIGHT: 15:00 → 05:00 next day
//   DAY:   08:45 → 13:45
// Returns a session id like "NIGHT-2026-04-17" so bars in the same trading
// session share an id. Used to anchor price change to the session open.
function sessionIdOf(timestamp: string): string {
  const normalized = timestamp.includes("T") ? timestamp : timestamp.replace(" ", "T");
  const withZ = /(?:Z|[+-]\d{2}:\d{2})$/i.test(normalized) ? normalized : `${normalized}Z`;
  const d = new Date(withZ);
  const hour = d.getUTCHours();
  const minute = d.getUTCMinutes();
  const totalMin = hour * 60 + minute;
  const dateStr = d.toISOString().slice(0, 10);
  if (totalMin >= 15 * 60) return `NIGHT-${dateStr}`;
  if (totalMin <= 5 * 60) {
    // Night session that started yesterday at 15:00
    const yesterday = new Date(d.getTime() - 24 * 3600 * 1000);
    return `NIGHT-${yesterday.toISOString().slice(0, 10)}`;
  }
  if (totalMin >= 8 * 60 + 45 && totalMin <= 13 * 60 + 45) return `DAY-${dateStr}`;
  return `OTHER-${dateStr}`;
}

export function PanelHeader({
  chip,
  chipColor,
  symbol,
  bars,
  liveValue,
  rightBadge,
  collapsed,
  onToggleCollapse,
}: PanelHeaderProps) {
  const lastBar = bars[bars.length - 1];
  const lastPrice = liveValue ?? lastBar?.close ?? null;

  // Anchor change to the OPEN of the current trading session (day or night),
  // not the previous bar. This matches how traders read TAIFEX session moves.
  let sessionOpenPrice: number | null = null;
  if (lastBar) {
    const lastSession = sessionIdOf(lastBar.timestamp);
    for (let i = bars.length - 1; i >= 0; i--) {
      if (sessionIdOf(bars[i].timestamp) === lastSession) {
        sessionOpenPrice = bars[i].open;
      } else {
        break;
      }
    }
  }
  const change = lastPrice !== null && sessionOpenPrice !== null ? lastPrice - sessionOpenPrice : null;
  const pctChange = change !== null && sessionOpenPrice ? (change / Math.abs(sessionOpenPrice)) * 100 : null;
  const changeColor = change === null ? colors.muted : change >= 0 ? colors.green : colors.red;

  return (
    <div
      className="flex items-center justify-between gap-3 px-3 py-1.5 flex-none"
      style={{
        background: colors.sidebar,
        borderBottom: `1px solid ${colors.cardBorder}`,
        fontFamily: "var(--font-mono)",
      }}
    >
      <div className="flex items-center gap-2">
        {onToggleCollapse && (
          <button
            onClick={onToggleCollapse}
            className="text-[11px] cursor-pointer border-none bg-transparent p-0 leading-none"
            style={{ color: colors.muted, width: 12 }}
            title={collapsed ? "Expand" : "Collapse"}
          >
            {collapsed ? "▸" : "▾"}
          </button>
        )}
        <span
          className="px-1.5 py-0.5 rounded text-[10px] font-bold tracking-wider"
          style={{ background: `${chipColor}33`, color: chipColor }}
        >
          {chip}
        </span>
        <span className="text-[11px]" style={{ color: colors.muted }}>{symbol}</span>
        {lastPrice !== null && (
          <span className="text-[13px] font-semibold" style={{ color: colors.text }}>
            {lastPrice.toFixed(2)}
          </span>
        )}
        {change !== null && (
          <span className="text-[11px]" style={{ color: changeColor }}>
            {change >= 0 ? "+" : ""}{change.toFixed(2)}
            {pctChange !== null && ` (${pctChange >= 0 ? "+" : ""}${pctChange.toFixed(2)}%)`}
          </span>
        )}
      </div>
      {rightBadge}
    </div>
  );
}
