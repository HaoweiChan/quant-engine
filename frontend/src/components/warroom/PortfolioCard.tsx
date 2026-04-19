import { useState, type ReactNode } from "react";
import { colors } from "@/lib/theme";
import {
  deleteLivePortfolio,
  detachMemberFromPortfolio,
  startSession,
  stopSession,
  updateAccountStrategies,
} from "@/lib/api";
import type { LivePortfolio, WarRoomSession } from "@/lib/api";
import { AllocationSlider } from "./AllocationSlider";

interface PortfolioCardProps {
  portfolio: LivePortfolio;
  members: WarRoomSession[];
  accountId: string;
  /** Current account bindings — needed to compute the post-remove binding list. */
  bindings: { slug: string; symbol: string }[];
  onAction: () => void;
  /** Member SessionCards rendered inside the card body. */
  children?: ReactNode;
}

type BusyKind = "toggle" | "remove" | null;

function ConfirmDialog({
  open, title, message, onConfirm, onCancel,
}: { open: boolean; title: string; message: string; onConfirm: () => void; onCancel: () => void }) {
  if (!open) return null;
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center"
      style={{ background: "rgba(0,0,0,0.6)", backdropFilter: "blur(2px)" }}
      onClick={onCancel}
    >
      <div
        className="flex flex-col gap-3 rounded-lg p-5 shadow-xl"
        style={{
          background: colors.card, border: `1px solid ${colors.cardBorder}`,
          minWidth: 340, maxWidth: 420, fontFamily: "var(--font-mono)",
        }}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center gap-2">
          <span className="text-[18px]" style={{ color: colors.red }}>⚠</span>
          <span className="text-[13px] font-bold" style={{ color: colors.text }}>{title}</span>
        </div>
        <p className="text-[11px] leading-relaxed m-0" style={{ color: colors.muted }}>{message}</p>
        <div className="flex items-center justify-end gap-2 mt-1">
          <button
            onClick={onCancel}
            className="text-[11px] px-4 py-1.5 rounded cursor-pointer border-none font-semibold"
            style={{ background: colors.cardBorder, color: colors.text }}
          >
            Cancel
          </button>
          <button
            onClick={onConfirm}
            className="text-[11px] px-4 py-1.5 rounded cursor-pointer border-none font-semibold text-white"
            style={{ background: colors.red }}
          >
            Remove
          </button>
        </div>
      </div>
    </div>
  );
}

/**
 * PortfolioCard — visual wrapper around all sessions that belong to one
 * LivePortfolio. Renders:
 *   * header with mode chip, name, member count, and an "×" remove button,
 *   * a single START ALL ↔ STOP ALL toggle derived from current member state,
 *   * the detailed per-member allocation editor (when 2+ members),
 *   * the member SessionCards, visually nested inside the card.
 */
export function PortfolioCard({
  portfolio,
  members,
  accountId,
  bindings,
  onAction,
  children,
}: PortfolioCardProps) {
  const [busy, setBusy] = useState<BusyKind>(null);
  const [error, setError] = useState<string | null>(null);
  const [showConfirm, setShowConfirm] = useState(false);

  const anyRunning = members.some(
    (m) => m.status === "active" || m.status === "paused",
  );

  const runActionOnMembers = async (
    op: (s: WarRoomSession) => Promise<unknown>,
  ): Promise<string[]> => {
    const failures: string[] = [];
    await Promise.all(
      members.map(async (s) => {
        try {
          await op(s);
        } catch (e) {
          failures.push(
            `${s.strategy_slug.split("/").pop()}: ${e instanceof Error ? e.message : String(e)}`,
          );
        }
      }),
    );
    return failures;
  };

  const handleToggleAll = async () => {
    setBusy("toggle");
    setError(null);
    const op = anyRunning
      ? (s: WarRoomSession) => stopSession(s.session_id)
      : (s: WarRoomSession) => startSession(s.session_id);
    const failures = await runActionOnMembers(op);
    setBusy(null);
    setError(failures.length > 0 ? failures.join(" · ") : null);
    onAction();
  };

  const handleRemove = () => setShowConfirm(true);

  const executeRemove = async () => {
    setShowConfirm(false);
    setBusy("remove");
    setError(null);
    const failures: string[] = [];
    try {
      await Promise.all(
        members
          .filter((s) => s.status === "active" || s.status === "paused")
          .map(async (s) => {
            try {
              await stopSession(s.session_id);
            } catch (e) {
              failures.push(
                `stop ${s.session_id.slice(0, 6)}: ${e instanceof Error ? e.message : String(e)}`,
              );
            }
          }),
      );
      await Promise.all(
        members.map(async (s) => {
          try {
            await detachMemberFromPortfolio(portfolio.portfolio_id, s.session_id);
          } catch (e) {
            failures.push(
              `detach ${s.session_id.slice(0, 6)}: ${e instanceof Error ? e.message : String(e)}`,
            );
          }
        }),
      );
      const memberKeys = new Set(
        members.map((s) => `${s.strategy_slug}|${s.symbol}`),
      );
      const remaining = bindings.filter(
        (b) => !memberKeys.has(`${b.slug}|${b.symbol}`),
      );
      try {
        await updateAccountStrategies(accountId, remaining);
      } catch (e) {
        failures.push(`unbind: ${e instanceof Error ? e.message : String(e)}`);
      }
      try {
        await deleteLivePortfolio(portfolio.portfolio_id);
      } catch (e) {
        failures.push(`delete: ${e instanceof Error ? e.message : String(e)}`);
      }
    } finally {
      setBusy(null);
      if (failures.length > 0) setError(failures.join(" · "));
      onAction();
    }
  };

  const accent = portfolio.mode === "live" ? colors.red : colors.gold;
  const isBusy = busy !== null;
  const toggleLabel = busy === "toggle" ? "…" : anyRunning ? "STOP ALL" : "START ALL";
  // Muted action colors — dark enough to sit alongside the rest of the sidebar
  // chrome without competing with live data for attention.
  const MUTED_GREEN = "#2a7a4a";
  const MUTED_RED = "#8c3333";
  const toggleBg = busy === "toggle"
    ? colors.dim
    : anyRunning
      ? MUTED_RED
      : MUTED_GREEN;

  return (
    <>
    <ConfirmDialog
      open={showConfirm}
      title={`Remove "${portfolio.name}"?`}
      message={`This will stop and unbind ${members.length} strategies from this account. Positions will NOT be flattened.`}
      onConfirm={executeRemove}
      onCancel={() => setShowConfirm(false)}
    />
    <div
      className="flex flex-col rounded overflow-hidden"
      style={{
        background: `${accent}0D`,
        border: `1px solid ${accent}40`,
        borderLeft: `3px solid ${accent}`,
        fontFamily: "var(--font-mono)",
      }}
    >
      {/* Header: mode chip + name + count + × */}
      <div
        className="flex items-center gap-2 px-2 py-1.5"
        style={{ borderBottom: `1px solid ${accent}25` }}
      >
        <span
          className="px-1.5 py-0.5 rounded text-[10px] font-bold tracking-wider shrink-0"
          style={{
            background: `${accent}26`,
            color: accent,
            border: `1px solid ${accent}55`,
          }}
        >
          {portfolio.mode.toUpperCase()}
        </span>
        <span
          className="text-[11px] font-semibold truncate flex-1"
          style={{ color: colors.text }}
          title={portfolio.name}
        >
          {portfolio.name}
        </span>
        <span
          className="text-[10px] px-1 rounded shrink-0"
          style={{ color: colors.muted, background: "rgba(255,255,255,0.04)" }}
          title={`${members.length} member strategies`}
        >
          {members.length}
        </span>
        <button
          onClick={handleRemove}
          disabled={isBusy}
          className="cursor-pointer border-none bg-transparent text-[14px] leading-none px-1 py-0 shrink-0"
          style={{
            color: busy === "remove" ? colors.dim : colors.muted,
            opacity: isBusy ? 0.4 : 1,
          }}
          title="Remove portfolio (stop, detach, unbind, delete)"
        >
          ×
        </button>
      </div>

      {/* Toggle: START ALL ↔ STOP ALL */}
      <div className="px-2 py-1">
        <button
          onClick={handleToggleAll}
          disabled={isBusy}
          className="w-full text-[11px] font-semibold py-0.5 rounded cursor-pointer border-none text-white"
          style={{
            background: toggleBg,
            opacity: isBusy ? 0.6 : 1,
            letterSpacing: "0.5px",
          }}
          title={anyRunning ? "Stop every running member" : "Start every stopped member"}
        >
          {toggleLabel}
        </button>
      </div>

      {error && (
        <div
          className="mx-2 mb-1 text-[10px] px-1.5 py-0.5 rounded"
          style={{ color: colors.red, background: "rgba(255,82,82,0.1)" }}
        >
          {error}
        </div>
      )}

      {/* Detailed allocation editor (scoped to this portfolio's members) */}
      {members.length >= 2 && (
        <div className="px-2 pb-2">
          <AllocationSlider sessions={members} onCommit={onAction} />
        </div>
      )}

      {/* Member strategy cards */}
      <div
        className="flex flex-col gap-2 p-2"
        style={{ borderTop: `1px solid ${accent}20`, background: "rgba(0,0,0,0.15)" }}
      >
        {children}
      </div>
    </div>
    </>
  );
}
