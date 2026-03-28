import { colors } from "@/lib/theme";


export interface RiskGuard {
  label: string;
  current: number;
  limit: number;
  unit?: string;
}

function utilizationColor(pct: number): string {
  if (pct >= 1.0) return colors.red;
  if (pct >= 0.8) return "#D4A017";
  return colors.green;
}

export function RiskLimiterPanel({ guards }: { guards: RiskGuard[] }) {
  if (guards.length === 0) {
    return (
      <div className="text-[10px] py-2" style={{ color: colors.dim, fontFamily: "var(--font-mono)" }}>
        No risk guards configured.
      </div>
    );
  }

  return (
    <div className="space-y-2">
      {guards.map((g) => {
        const pct = g.limit > 0 ? g.current / g.limit : 0;
        const clamped = Math.min(pct, 1);
        const col = utilizationColor(pct);
        const breached = pct >= 1.0;
        return (
          <div key={g.label}>
            <div className="flex items-center justify-between mb-0.5">
              <span className="text-[9px]" style={{ color: colors.muted, fontFamily: "var(--font-mono)" }}>
                {g.label}
              </span>
              <span className="text-[9px]" style={{ color: col, fontFamily: "var(--font-mono)" }}>
                {g.current.toLocaleString()}{g.unit ? ` ${g.unit}` : ""} / {g.limit.toLocaleString()}{g.unit ? ` ${g.unit}` : ""}
                {breached && (
                  <span className="ml-1 px-1 py-0.5 rounded text-[8px] font-bold" style={{ background: "rgba(255,30,30,0.15)", color: colors.red }}>
                    BREACHED
                  </span>
                )}
              </span>
            </div>
            <div className="w-full h-1.5 rounded-full overflow-hidden" style={{ background: "rgba(255,255,255,0.05)" }}>
              <div
                className="h-full rounded-full transition-all"
                style={{ width: `${clamped * 100}%`, background: col }}
              />
            </div>
          </div>
        );
      })}
    </div>
  );
}
