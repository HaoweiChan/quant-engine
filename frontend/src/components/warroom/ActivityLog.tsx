import { colors } from "@/lib/theme";
import type { DeployLogEntry, AccountFill } from "@/lib/api";

interface MockFill extends AccountFill {
  is_session_close?: boolean;
  signal_reason?: string;
  triggered?: boolean;
}

interface ActivityLogProps {
  deployHistory: DeployLogEntry[];
  accountId: string | null;
  fills?: MockFill[];
  playbackMode?: boolean;
  bindings?: { slug: string; symbol: string }[];
}

function fillActionLabel(fill: MockFill): { label: string; color: string } {
  if (fill.is_session_close) return { label: "SESSION CLOSE", color: colors.orange };
  if (fill.signal_reason?.includes("stop")) return { label: "STOP", color: colors.red };
  if (fill.side.toUpperCase() === "BUY") return { label: "BUY", color: colors.green };
  return { label: "SELL", color: colors.red };
}

export function ActivityLog({ deployHistory, accountId, fills, playbackMode, bindings }: ActivityLogProps) {
  if (playbackMode && fills && fills.length > 0) {
    return (
      <div className="h-full flex flex-col">
        <div className="p-2 overflow-y-auto flex-1 text-[11px]" style={{ fontFamily: "var(--font-mono)" }}>
          {fills.slice(0, 50).map((f, i) => {
            const action = fillActionLabel(f);
            return (
              <div key={i} className="flex gap-3 py-0.5 border-b last:border-b-0" style={{ borderColor: colors.cardBorder, color: colors.muted }}>
                <span style={{ color: colors.dim }}>{f.timestamp.slice(0, 16).replace("T", " ")}</span>
                <span style={{ color: action.color }}>{action.label}</span>
                <span style={{ color: colors.text }}>{f.strategy_slug?.split("/").pop() ?? "—"}</span>
                <span>{f.symbol}</span>
                <span style={{ color: colors.muted }}>{f.quantity}@${f.price.toLocaleString()}</span>
                {f.signal_reason && (
                  <span style={{ color: colors.dim }}>{f.signal_reason}</span>
                )}
              </div>
            );
          })}
        </div>
      </div>
    );
  }

  const filtered = accountId
    ? deployHistory.filter((d) =>
        d.account_id === accountId &&
        (!bindings || bindings.some((b) => b.slug === d.strategy))
      )
    : deployHistory;

  return (
    <div className="h-full flex flex-col">
      <div className="p-2 overflow-y-auto flex-1 text-[11px]" style={{ fontFamily: "var(--font-mono)" }}>
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
