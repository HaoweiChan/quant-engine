import { AllocationSlider } from "./AllocationSlider";
import { SessionCard } from "./SessionCard";
import { colors } from "@/lib/theme";
import type { WarRoomSession } from "@/lib/api";

interface SessionGridProps {
  sessions: WarRoomSession[];
  bindings?: { slug: string; symbol: string }[];
  accountId?: string;
  onAction: () => void;
}

export function SessionGrid({ sessions, bindings, accountId, onAction }: SessionGridProps) {
  if (sessions.length === 0) {
    return (
      <div className="p-3 text-[11px]" style={{ color: colors.dim, fontFamily: "var(--font-mono)" }}>
        No strategies bound to this account. Add one below.
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-2 p-2 overflow-y-auto" style={{ flex: 1 }}>
      {sessions.length >= 2 && (
        <AllocationSlider sessions={sessions} onCommit={onAction} />
      )}
      {sessions.map((s) => (
        <SessionCard
          key={s.session_id}
          session={s}
          allBindings={bindings}
          accountId={accountId}
          onAction={onAction}
        />
      ))}
    </div>
  );
}
