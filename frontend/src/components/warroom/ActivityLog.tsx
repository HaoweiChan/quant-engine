import { colors } from "@/lib/theme";
import type { DeployLogEntry } from "@/lib/api";

interface ActivityLogProps {
  deployHistory: DeployLogEntry[];
  accountId: string | null;
}

export function ActivityLog({ deployHistory, accountId }: ActivityLogProps) {
  const filtered = accountId
    ? deployHistory.filter((d) => d.account_id === accountId)
    : deployHistory;

  return (
    <div className="h-full flex flex-col">
      <div className="p-2 overflow-y-auto flex-1 text-[9px]" style={{ fontFamily: "var(--font-mono)" }}>
        {filtered.length === 0 ? (
          <div className="py-1" style={{ color: colors.dim }}>No recent activity.</div>
        ) : (
          filtered.slice(0, 20).map((d) => (
            <div key={d.id} className="flex gap-3 py-0.5 border-b last:border-b-0" style={{ borderColor: colors.cardBorder, color: colors.muted }}>
              <span style={{ color: colors.dim }}>{d.deployed_at?.slice(0, 16).replace("T", " ")}</span>
              <span style={{ color: colors.cyan }}>DEPLOY</span>
              <span style={{ color: colors.text }}>{d.strategy.split("/").pop()}</span>
              <span>{d.symbol}</span>
              <span style={{ color: colors.dim }}>candidate #{d.candidate_id}</span>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
