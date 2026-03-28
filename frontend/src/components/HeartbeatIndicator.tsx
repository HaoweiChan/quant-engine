import { useEffect, useState } from "react";
import { fetchHeartbeat } from "@/lib/api";
import type { HeartbeatResponse } from "@/lib/api";
import { colors } from "@/lib/theme";


function latencyColor(ms: number | null): string {
  if (ms === null) return colors.red;
  if (ms < 100) return colors.green;
  if (ms < 500) return "#D4A017";
  return colors.red;
}

export function HeartbeatIndicator() {
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

  if (!hb) {
    return (
      <span className="text-[9px] px-2 py-0.5 rounded" style={{ color: colors.dim, fontFamily: "var(--font-mono)", background: "rgba(255,255,255,0.03)" }}>
        HB: —
      </span>
    );
  }

  return (
    <div className="flex items-center gap-2">
      {hb.brokers.map((b) => (
        <span
          key={b.account_id}
          className="text-[9px] px-2 py-0.5 rounded flex items-center gap-1"
          style={{ fontFamily: "var(--font-mono)", background: "rgba(255,255,255,0.03)" }}
        >
          <span
            className="inline-block w-1.5 h-1.5 rounded-full"
            style={{ background: latencyColor(b.latency_ms) }}
          />
          <span style={{ color: colors.muted }}>{b.broker}</span>
          <span style={{ color: latencyColor(b.latency_ms) }}>
            {b.latency_ms !== null ? `${b.latency_ms}ms` : "DOWN"}
          </span>
        </span>
      ))}
      {hb.halt_active && (
        <span className="text-[9px] font-bold px-2 py-0.5 rounded" style={{ color: colors.red, background: "rgba(255,30,30,0.1)", fontFamily: "var(--font-mono)" }}>
          HALTED
        </span>
      )}
    </div>
  );
}
