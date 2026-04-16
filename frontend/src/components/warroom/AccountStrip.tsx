import { useEffect, useState } from "react";
import { colors } from "@/lib/theme";
import { useTradingStore } from "@/stores/tradingStore";
import { fetchHeartbeat } from "@/lib/api";
import type { HeartbeatResponse } from "@/lib/api";

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

function latencyColor(ms: number | null): string {
  if (ms === null) return colors.red;
  if (ms < 100) return colors.green;
  if (ms < 500) return "#D4A017";
  return colors.red;
}

export function AccountStrip({ accounts }: AccountStripProps) {
  const activeAccountId = useTradingStore((s) => s.activeAccountId);
  const setActiveAccountId = useTradingStore((s) => s.setActiveAccountId);
  const [hb, setHb] = useState<HeartbeatResponse | null>(null);

  useEffect(() => {
    let active = true;
    const poll = async () => {
      try {
        const data = await fetchHeartbeat();
        if (active) setHb(data);
      } catch { /* ignore */ }
    };
    poll();
    const id = setInterval(poll, 5000);
    return () => { active = false; clearInterval(id); };
  }, []);

  const latencyMap = new Map<string, number | null>();
  if (hb) {
    for (const b of hb.brokers) {
      latencyMap.set(b.account_id, b.latency_ms);
    }
  }

  const entries = Object.entries(accounts);
  if (entries.length === 0) {
    return (
      <div className="flex items-center px-4 py-1.5" style={{ borderBottom: `1px solid ${colors.cardBorder}`, background: colors.bg }}>
        <span className="text-[11px]" style={{ color: colors.dim, fontFamily: "var(--font-mono)" }}>No accounts configured</span>
      </div>
    );
  }

  return (
    <div className="flex items-center gap-2 px-4 py-1.5 overflow-x-auto" style={{ borderBottom: `1px solid ${colors.cardBorder}`, background: colors.bg }}>
      {entries.map(([id, info]) => {
        const isSelected = activeAccountId === id;
        const lat = latencyMap.get(id);
        const latMs = lat !== undefined ? lat : null;
        return (
          <button
            key={id}
            data-testid={`account-${id}`}
            onClick={() => setActiveAccountId(id)}
            className="flex items-center gap-2 px-3 py-1 rounded-full cursor-pointer border-none shrink-0 transition-all"
            style={{
              background: isSelected ? `${colors.green}15` : colors.card,
              border: `1px solid ${isSelected ? colors.green : colors.cardBorder}`,
              fontFamily: "var(--font-mono)",
            }}
          >
            <span
              className="inline-block w-1.5 h-1.5 rounded-full"
              style={{ background: info.connected ? latencyColor(latMs) : colors.red }}
            />
            <span className="text-[11px]" style={{ color: isSelected ? colors.text : colors.muted }}>
              {info.display_name || id}
            </span>
            <span
              className="font-bold px-1 rounded"
              style={{
                fontSize: 9,
                lineHeight: "14px",
                background: info.sandbox_mode ? "#8B6914" : "#166534",
                color: "#fff",
              }}
            >
              {info.sandbox_mode ? "PAPER" : "LIVE"}
            </span>
            <span className="text-[11px] font-semibold" style={{ color: colors.green }}>
              ${info.equity.toLocaleString(undefined, { maximumFractionDigits: 0 })}
            </span>
            <span className="text-[11px]" style={{ color: latencyColor(latMs) }}>
              {latMs !== null ? `${latMs}ms` : "—"}
            </span>
          </button>
        );
      })}
      {hb?.halt_active && (
        <span className="text-[11px] font-bold px-2 py-0.5 rounded" style={{ color: colors.red, background: "rgba(255,30,30,0.1)", fontFamily: "var(--font-mono)" }}>
          HALTED
        </span>
      )}
    </div>
  );
}
