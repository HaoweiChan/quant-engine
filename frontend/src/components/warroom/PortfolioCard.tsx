import { useEffect, useState, type ReactNode } from "react";
import { colors } from "@/lib/theme";
import {
  deleteLivePortfolio,
  detachMemberFromPortfolio,
  resetPortfolioEquity,
  startSession,
  stopSession,
  updateAccountStrategies,
  updatePortfolioInitialEquity,
} from "@/lib/api";
import type { LivePortfolio, WarRoomSession } from "@/lib/api";
import { AllocationSlider } from "./AllocationSlider";

interface PortfolioCardProps {
  portfolio: LivePortfolio;
  members: WarRoomSession[];
  accountId: string;
  /** Current account bindings — needed to compute the post-remove binding list. */
  bindings: { slug: string; symbol: string }[];
  /** Latest aggregated equity for this portfolio (sum of member runner equities). */
  currentEquity?: number | null;
  onAction: () => void;
  /** Member SessionCards rendered inside the card body. */
  children?: ReactNode;
}

type BusyKind = "toggle" | "remove" | "reset" | null;

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
  currentEquity,
  onAction,
  children,
}: PortfolioCardProps) {
  const [busy, setBusy] = useState<BusyKind>(null);
  const [error, setError] = useState<string | null>(null);
  const [showConfirm, setShowConfirm] = useState(false);
  const [showResetConfirm, setShowResetConfirm] = useState(false);
  // Local draft for the editable Init $ input. Synced from props when the
  // server-side value changes (e.g. after a successful commit or refetch).
  const [initDraft, setInitDraft] = useState<string>(
    portfolio.initial_equity != null ? String(portfolio.initial_equity) : "",
  );
  const [savingInit, setSavingInit] = useState(false);
  useEffect(() => {
    setInitDraft(portfolio.initial_equity != null ? String(portfolio.initial_equity) : "");
  }, [portfolio.initial_equity]);

  const commitInitialEquity = async () => {
    const parsed = Number(initDraft);
    if (!Number.isFinite(parsed) || parsed <= 0) return;
    if (parsed === portfolio.initial_equity) return;
    setSavingInit(true);
    setError(null);
    try {
      await updatePortfolioInitialEquity(portfolio.portfolio_id, parsed);
      onAction();
    } catch (e) {
      setError(`init equity: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setSavingInit(false);
    }
  };

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
  const handleReset = () => setShowResetConfirm(true);

  const executeReset = async () => {
    setShowResetConfirm(false);
    setBusy("reset");
    setError(null);
    try {
      await resetPortfolioEquity(portfolio.portfolio_id);
    } catch (e) {
      setError(`reset: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setBusy(null);
      onAction();
    }
  };

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
    <ConfirmDialog
      open={showResetConfirm}
      title={`Reset paper equity for "${portfolio.name}"?`}
      message={`Wipes this portfolio's equity history and re-anchors each member runner's budget to ${portfolio.initial_equity != null ? `$${portfolio.initial_equity.toLocaleString()}` : "the portfolio's seed equity"}. The other portfolios on this account are not touched.`}
      onConfirm={executeReset}
      onCancel={() => setShowResetConfirm(false)}
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
      {/* Row 1 (always): mode chip · name · members count · current equity · ×.
          Action controls (INIT $ / RESET) live on Row 2 so they cannot push
          × past the parent's overflow:hidden boundary in narrow sidebars. */}
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
        {currentEquity != null && (
          <span
            className="text-[10px] tabular-nums shrink-0"
            style={{ color: colors.green }}
            title="Latest aggregated portfolio equity"
          >
            ${currentEquity.toLocaleString(undefined, { maximumFractionDigits: 0 })}
          </span>
        )}
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

      {/* Row 2 (paper only): INIT $ input · RESET. Live portfolios get no
          row-2 chrome — they're driven by the broker, not a chosen seed. */}
      {portfolio.mode === "paper" && (
        <div
          className="flex items-center gap-2 px-2 py-1"
          style={{ borderBottom: `1px solid ${accent}20` }}
        >
          <span
            className="flex items-center gap-1 flex-1 min-w-0"
            title="Initial paper equity used to seed this portfolio's curve. Edit and commit to persist; press RESET to wipe history at the new value."
          >
            <span className="text-[9px] tracking-wider shrink-0" style={{ color: colors.dim }}>INIT $</span>
            <input
              type="number"
              min={0}
              step={1000}
              value={initDraft}
              placeholder="set seed"
              disabled={isBusy || savingInit}
              onChange={(e) => setInitDraft(e.target.value)}
              onBlur={() => void commitInitialEquity()}
              onKeyDown={(e) => {
                if (e.key === "Enter") (e.target as HTMLInputElement).blur();
                if (e.key === "Escape") {
                  setInitDraft(portfolio.initial_equity != null ? String(portfolio.initial_equity) : "");
                  (e.target as HTMLInputElement).blur();
                }
              }}
              className="text-[10px] tabular-nums px-1 py-0 rounded outline-none flex-1 min-w-0"
              style={{
                background: colors.card,
                color: colors.text,
                border: `1px solid ${colors.cardBorder}`,
                fontFamily: "var(--font-mono)",
              }}
            />
            {savingInit && <span className="text-[9px] shrink-0" style={{ color: colors.dim }}>…</span>}
          </span>
          <button
            onClick={handleReset}
            disabled={isBusy || !portfolio.initial_equity}
            className="text-[9px] font-bold px-1.5 py-0.5 rounded cursor-pointer border-none shrink-0 tracking-wider"
            style={{
              background: "rgba(139,105,20,0.25)",
              color: busy === "reset" ? colors.dim : "#D4A017",
              opacity: isBusy || !portfolio.initial_equity ? 0.4 : 1,
              fontFamily: "var(--font-mono)",
            }}
            title={
              portfolio.initial_equity
                ? `Reset paper equity to $${portfolio.initial_equity.toLocaleString()}`
                : "Set initial_equity on this portfolio to enable reset"
            }
          >
            {busy === "reset" ? "…" : "RESET"}
          </button>
        </div>
      )}

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

      {/* Per-strategy allocation editor. Live portfolios are read-only
          (weights come from the original optimization). Paper portfolios
          are interactive — users can rebalance the seed equity across
          strategies in the sandbox. */}
      {members.length >= 2 && (
        <div className="px-2 pb-2">
          <AllocationSlider
            sessions={members}
            onCommit={onAction}
            readOnly={portfolio.mode === "live"}
          />
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
