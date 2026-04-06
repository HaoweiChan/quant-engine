import { SessionCard } from "./SessionCard";
import { colors } from "@/lib/theme";
import type { WarRoomSession } from "@/lib/api";

interface SessionGridProps {
  sessions: WarRoomSession[];
  onAction: () => void;
}

export function SessionGrid({ sessions, onAction }: SessionGridProps) {
  if (sessions.length === 0) {
    return (
      <div className="p-3 text-[9px]" style={{ color: colors.dim, fontFamily: "var(--font-mono)" }}>
        No strategies bound to this account. Add one below.
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-2 p-2 overflow-y-auto" style={{ flex: 1 }}>
      {sessions.map((s) => (
        <SessionCard key={s.session_id} session={s} onAction={onAction} />
      ))}
    </div>
  );
}
