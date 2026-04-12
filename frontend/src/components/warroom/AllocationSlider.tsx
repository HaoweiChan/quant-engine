import { useEffect, useState } from "react";

import { colors } from "@/lib/theme";
import { updateEquityShare } from "@/lib/api";
import type { WarRoomSession } from "@/lib/api";

interface AllocationSliderProps {
  /** All sessions that belong to the same account. Typically 2. */
  sessions: WarRoomSession[];
  onCommit: () => void;
}

/**
 * AllocationSlider — shows per-session equity share as a stacked bar with
 * inline numeric editors.
 *
 * For now we only render an interactive editor when there are exactly 2
 * sessions on the account (the 60/40 use case). With one session the
 * component is a passive display, and with 3+ sessions it falls back to a
 * read-only summary — a full n-way slider is a follow-up.
 */
export function AllocationSlider({ sessions, onCommit }: AllocationSliderProps) {
  const [pendingShares, setPendingShares] = useState<Record<string, number>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Whenever the upstream sessions change (e.g. after a poll), refresh the
  // local pending state so we don't show stale values post-commit.
  useEffect(() => {
    const next: Record<string, number> = {};
    for (const s of sessions) next[s.session_id] = s.equity_share;
    setPendingShares(next);
    setError(null);
  }, [sessions]);

  if (sessions.length === 0) return null;
  if (sessions.length === 1) {
    const s = sessions[0];
    return (
      <div
        className="text-[9px] px-2 py-1 rounded"
        style={{
          background: colors.card,
          border: `1px solid ${colors.cardBorder}`,
          fontFamily: "var(--font-mono)",
          color: colors.muted,
        }}
      >
        Allocation: 100% → {s.strategy_slug.split("/").pop()}
      </div>
    );
  }

  const handleTwoWaySlider = (ev: React.ChangeEvent<HTMLInputElement>) => {
    const first = sessions[0];
    const second = sessions[1];
    const firstShare = Math.min(0.95, Math.max(0.05, Number(ev.target.value) / 100));
    setPendingShares({
      [first.session_id]: firstShare,
      [second.session_id]: Number((1 - firstShare).toFixed(4)),
    });
    setError(null);
  };

  const handleCommit = async () => {
    setBusy(true);
    setError(null);
    try {
      // Always shrink first, then expand — prevents the sum-of-shares
      // overflow check on the server from rejecting valid 60/40 swaps.
      const shrinking: string[] = [];
      const growing: string[] = [];
      for (const s of sessions) {
        const next = pendingShares[s.session_id];
        if (next < s.equity_share) shrinking.push(s.session_id);
        else if (next > s.equity_share) growing.push(s.session_id);
      }
      for (const sid of shrinking) {
        await updateEquityShare(sid, pendingShares[sid]);
      }
      for (const sid of growing) {
        await updateEquityShare(sid, pendingShares[sid]);
      }
      onCommit();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Commit failed");
    } finally {
      setBusy(false);
    }
  };

  const hasChanges = sessions.some(
    (s) => pendingShares[s.session_id] !== undefined && pendingShares[s.session_id] !== s.equity_share,
  );

  if (sessions.length >= 3) {
    return (
      <div
        className="text-[9px] px-2 py-1 rounded"
        style={{
          background: colors.card,
          border: `1px solid ${colors.cardBorder}`,
          fontFamily: "var(--font-mono)",
          color: colors.muted,
        }}
      >
        Allocation (3+ sessions) — read only:{" "}
        {sessions
          .map(
            (s) => `${s.strategy_slug.split("/").pop()} ${Math.round(s.equity_share * 100)}%`,
          )
          .join("  ")}
      </div>
    );
  }

  // Exactly 2 sessions — interactive slider
  const first = sessions[0];
  const second = sessions[1];
  const firstPct = Math.round((pendingShares[first.session_id] ?? first.equity_share) * 100);
  const secondPct = 100 - firstPct;

  return (
    <div
      className="flex flex-col gap-1 p-2 rounded"
      style={{
        background: colors.card,
        border: `1px solid ${colors.cardBorder}`,
      }}
    >
      <div
        className="flex items-center justify-between text-[9px]"
        style={{ fontFamily: "var(--font-mono)" }}
      >
        <span style={{ color: colors.text }}>
          {first.strategy_slug.split("/").pop()}
          <span style={{ color: colors.muted }}> · {first.symbol}</span>
        </span>
        <span style={{ color: colors.text }}>
          {second.strategy_slug.split("/").pop()}
          <span style={{ color: colors.muted }}> · {second.symbol}</span>
        </span>
      </div>
      <div className="flex items-center gap-1.5">
        <span
          className="text-[10px] font-semibold"
          style={{ color: colors.green, fontFamily: "var(--font-mono)", minWidth: 24 }}
        >
          {firstPct}%
        </span>
        <input
          type="range"
          min={5}
          max={95}
          value={firstPct}
          onChange={handleTwoWaySlider}
          disabled={busy}
          className="flex-1 cursor-pointer"
          style={{ accentColor: colors.green }}
        />
        <span
          className="text-[10px] font-semibold"
          style={{ color: colors.blue, fontFamily: "var(--font-mono)", minWidth: 24 }}
        >
          {secondPct}%
        </span>
      </div>
      {error && (
        <div
          className="text-[8px] px-1.5 py-0.5 rounded"
          style={{
            background: "rgba(255,82,82,0.12)",
            color: colors.red,
            fontFamily: "var(--font-mono)",
          }}
        >
          {error}
        </div>
      )}
      <div className="flex justify-end">
        <button
          type="button"
          onClick={handleCommit}
          disabled={!hasChanges || busy}
          className="text-[8px] font-semibold py-0.5 px-2 rounded cursor-pointer border-none"
          style={{
            background: hasChanges ? colors.green : "rgba(255,255,255,0.08)",
            color: hasChanges ? "#fff" : colors.dim,
            letterSpacing: "0.5px",
            opacity: busy ? 0.6 : 1,
          }}
        >
          {busy ? "..." : "APPLY"}
        </button>
      </div>
    </div>
  );
}
