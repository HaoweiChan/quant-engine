import { useEffect, useRef, useState } from "react";

import { colors } from "@/lib/theme";
import { updateEquityShare, batchUpdateEquityShare } from "@/lib/api";
import type { WarRoomSession } from "@/lib/api";

interface AllocationSliderProps {
  /** All sessions that belong to the same account. Typically 2. */
  sessions: WarRoomSession[];
  onCommit: () => void;
  /** When true, render a static read-only summary (per-member %) instead
   *  of the interactive slider/inputs. Used for live portfolios where the
   *  weights come from the original optimization and must not be edited
   *  post-creation. */
  readOnly?: boolean;
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
export function AllocationSlider({ sessions, onCommit, readOnly }: AllocationSliderProps) {
  const [pendingShares, setPendingShares] = useState<Record<string, number>>({});
  const [draftPct, setDraftPct] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const prevSharesRef = useRef<string>("");

  // Only reset local state when upstream equity_share values actually change,
  // not on every poll. Prevents overwriting the user's in-progress edits.
  useEffect(() => {
    const shareKey = sessions.map((s) => `${s.session_id}:${s.equity_share}`).join(",");
    if (shareKey === prevSharesRef.current) return;
    prevSharesRef.current = shareKey;
    const next: Record<string, number> = {};
    const nextDraft: Record<string, string> = {};
    for (const s of sessions) {
      next[s.session_id] = s.equity_share;
      nextDraft[s.session_id] = String(Math.round(s.equity_share * 100));
    }
    setPendingShares(next);
    setDraftPct(nextDraft);
    setError(null);
  }, [sessions]);

  if (sessions.length === 0) return null;
  if (sessions.length === 1) {
    const s = sessions[0];
    return (
      <div
        className="text-[11px] px-2 py-1.5 rounded"
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

  if (readOnly) {
    // Live portfolios: weights come from the original optimization and
    // are not editable here. Render a static per-member summary.
    void onCommit;
    return (
      <div
        className="flex flex-col gap-1 p-2 rounded"
        style={{
          background: colors.card,
          border: `1px solid ${colors.cardBorder}`,
          fontFamily: "var(--font-mono)",
        }}
      >
        <div className="text-[11px] font-semibold tracking-wider" style={{ color: colors.muted }}>
          ALLOCATION ({sessions.length} strategies)
        </div>
        {sessions.map((s) => (
          <div key={s.session_id} className="flex items-center justify-between gap-2 text-[11px]">
            <span className="truncate" style={{ color: colors.text }} title={s.strategy_slug}>
              {s.strategy_slug.split("/").pop()}
            </span>
            <span className="shrink-0 font-semibold" style={{ color: colors.blue }}>
              {Math.round((s.equity_share ?? 0) * 100)}%
            </span>
          </div>
        ))}
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
      if (sessions.length >= 3) {
        // Use batch endpoint for 3+ sessions - validates final state atomically
        const allocations = sessions.map((s) => ({
          session_id: s.session_id,
          share: pendingShares[s.session_id] ?? s.equity_share,
        }));
        await batchUpdateEquityShare(allocations);
      } else {
        // Original 2-session logic: shrink first, then expand
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

  // Handle free-form text input for multi-strategy allocation
  const handleDraftChange = (sessionId: string, value: string) => {
    // Allow any input (including empty) for free typing
    setDraftPct((prev) => ({ ...prev, [sessionId]: value }));

    // Parse and update pendingShares if it's a valid number
    const parsed = parseInt(value, 10);
    if (!isNaN(parsed)) {
      setPendingShares((prev) => ({ ...prev, [sessionId]: parsed / 100 }));
    }
    setError(null);
  };

  // Validate allocation constraints for 3+ strategies
  const getValidationState = () => {
    const values = sessions.map((s) => {
      const draft = draftPct[s.session_id];
      const parsed = parseInt(draft ?? "", 10);
      return { sessionId: s.session_id, value: parsed, valid: !isNaN(parsed) && parsed >= 0 };
    });

    const allValid = values.every((v) => v.valid);
    const total = values.reduce((sum, v) => sum + (v.valid ? v.value : 0), 0);
    const anyBelowMin = values.some((v) => v.valid && v.value < 5);
    const anyAboveMax = values.some((v) => v.valid && v.value > 95);

    return { allValid, total, anyBelowMin, anyAboveMax, canApply: allValid && total === 100 };
  };

  if (sessions.length >= 3) {
    const validation = getValidationState();
    const { total, canApply, anyBelowMin } = validation;

    return (
      <div
        className="flex flex-col gap-1.5 p-2 rounded"
        style={{
          background: colors.card,
          border: `1px solid ${colors.cardBorder}`,
        }}
      >
        <div
          className="text-[11px] font-semibold tracking-wider"
          style={{ color: colors.muted, fontFamily: "var(--font-mono)" }}
        >
          ALLOCATION ({sessions.length} strategies)
        </div>
        <div className="flex flex-col gap-1.5">
          {sessions.map((s) => {
            const draft = draftPct[s.session_id] ?? String(Math.round(s.equity_share * 100));
            const parsed = parseInt(draft, 10);
            const isInvalid = isNaN(parsed) || parsed < 0;
            return (
              <div
                key={s.session_id}
                className="flex items-center justify-between gap-2"
              >
                <span
                  className="text-[11px] flex-1 truncate"
                  style={{ color: colors.text, fontFamily: "var(--font-mono)" }}
                  title={s.strategy_slug}
                >
                  {s.strategy_slug.split("/").pop()}
                </span>
                <div className="flex items-center gap-1">
                  <input
                    type="text"
                    inputMode="numeric"
                    value={draft}
                    onChange={(e) => handleDraftChange(s.session_id, e.target.value)}
                    disabled={busy}
                    className="w-14 text-right text-[11px] px-1.5 py-1 rounded border-none"
                    style={{
                      background: "var(--color-qe-input)",
                      color: isInvalid ? colors.red : colors.text,
                      fontFamily: "var(--font-mono)",
                    }}
                  />
                  <span
                    className="text-[11px]"
                    style={{ color: colors.muted, fontFamily: "var(--font-mono)" }}
                  >
                    %
                  </span>
                </div>
              </div>
            );
          })}
        </div>
        <div className="flex items-center justify-between">
          <span
            className="text-[11px]"
            style={{
              color: canApply ? colors.green : colors.red,
              fontFamily: "var(--font-mono)",
            }}
          >
            Total: {total}%{total !== 100 && " (must equal 100%)"}
            {anyBelowMin && total === 100 && " (min 5% each)"}
          </span>
          <button
            type="button"
            onClick={handleCommit}
            disabled={!hasChanges || !canApply || anyBelowMin || busy}
            className="text-[11px] font-semibold py-1 px-3 rounded cursor-pointer border-none"
            style={{
              background: hasChanges && canApply && !anyBelowMin ? colors.green : "rgba(255,255,255,0.08)",
              color: hasChanges && canApply && !anyBelowMin ? "#fff" : colors.dim,
              letterSpacing: "0.5px",
              opacity: busy ? 0.6 : 1,
            }}
          >
            {busy ? "..." : "APPLY"}
          </button>
        </div>
        {error && (
          <div
            className="text-[11px] px-1.5 py-0.5 rounded"
            style={{
              background: "rgba(255,82,82,0.12)",
              color: colors.red,
              fontFamily: "var(--font-mono)",
            }}
          >
            {error}
          </div>
        )}
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
      className="flex flex-col gap-1.5 p-2 rounded"
      style={{
        background: colors.card,
        border: `1px solid ${colors.cardBorder}`,
      }}
    >
      <div
        className="flex items-center justify-between text-[11px]"
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
          className="text-[12px] font-semibold"
          style={{ color: colors.green, fontFamily: "var(--font-mono)", minWidth: 28 }}
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
          className="text-[12px] font-semibold"
          style={{ color: colors.blue, fontFamily: "var(--font-mono)", minWidth: 28 }}
        >
          {secondPct}%
        </span>
      </div>
      {error && (
        <div
          className="text-[11px] px-1.5 py-0.5 rounded"
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
          className="text-[11px] font-semibold py-1 px-3 rounded cursor-pointer border-none"
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
