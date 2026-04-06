import { colors } from "@/lib/theme";
import { useTradingStore } from "@/stores/tradingStore";

interface AccountData {
  display_name: string;
  broker: string;
  equity: number;
  connected: boolean;
  sandbox_mode: boolean;
  margin_used: number;
  margin_available: number;
}

interface AccountStripProps {
  accounts: Record<string, AccountData>;
}

export function AccountStrip({ accounts }: AccountStripProps) {
  const activeAccountId = useTradingStore((s) => s.activeAccountId);
  const setActiveAccountId = useTradingStore((s) => s.setActiveAccountId);

  const entries = Object.entries(accounts);
  if (entries.length === 0) {
    return (
      <div className="flex items-center px-4 py-1.5" style={{ borderBottom: `1px solid ${colors.cardBorder}`, background: colors.bg }}>
        <span className="text-[9px]" style={{ color: colors.dim, fontFamily: "var(--font-mono)" }}>No accounts configured</span>
      </div>
    );
  }

  return (
    <div className="flex items-center gap-2 px-4 py-1.5 overflow-x-auto" style={{ borderBottom: `1px solid ${colors.cardBorder}`, background: colors.bg }}>
      {entries.map(([id, info]) => {
        const isSelected = activeAccountId === id;
        return (
          <button
            key={id}
            onClick={() => setActiveAccountId(id)}
            className="flex items-center gap-2 px-3 py-1 rounded-full cursor-pointer border-none shrink-0 transition-all"
            style={{
              background: isSelected ? `${colors.green}15` : colors.card,
              border: `1px solid ${isSelected ? colors.green : colors.cardBorder}`,
              fontFamily: "var(--font-mono)",
            }}
          >
            <span style={{ color: info.connected ? colors.green : colors.red, fontSize: 6 }}>{"●"}</span>
            <span className="text-[9px]" style={{ color: isSelected ? colors.text : colors.muted }}>
              {info.display_name || id}
            </span>
            {info.connected && (
              <span className="text-[9px] font-semibold" style={{ color: colors.green }}>
                ${info.equity.toLocaleString()}
              </span>
            )}
            {info.sandbox_mode && (
              <span className="text-[6px] font-semibold px-1 py-0.5 rounded" style={{ background: colors.orange, color: "white" }}>
                PAPER
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
}
